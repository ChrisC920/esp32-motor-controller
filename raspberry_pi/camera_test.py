#!/usr/bin/env python3
"""Test CSI camera capture or benchmark YOLO on the Raspberry Pi CPU."""

import argparse
import csv
from datetime import datetime
import json
import math
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import time


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def positive_float(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be finite and greater than zero")
    return number


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("camera", "yolo"), default="camera")
    parser.add_argument("--list-cameras", action="store_true")
    parser.add_argument("--camera", type=int, default=0, help="camera index, default 0")
    parser.add_argument("--seconds", type=positive_float, default=10,
                        help="measurement duration after startup/warmup, default 10")
    parser.add_argument("--width", type=positive_int, default=640)
    parser.add_argument("--height", type=positive_int, default=480)
    parser.add_argument("--fps", type=positive_float, default=30,
                        help="requested camera frame rate; not a YOLO FPS guarantee")
    parser.add_argument("--preview", action="store_true", help="local desktop window; Q exits")
    parser.add_argument("--output", type=Path, help="new output directory, default camera_results/timestamp")
    parser.add_argument("--model", default="yolo26n.pt", help="YOLO weights or exported NCNN directory")
    parser.add_argument("--imgsz", type=positive_int, default=320)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--threads", type=positive_int, default=4)
    parser.add_argument("--warmup", type=positive_int, default=3, help="unmeasured YOLO predictions")
    args = parser.parse_args(argv)
    if args.camera < 0:
        parser.error("--camera must be zero or greater")
    if not 0 <= args.conf <= 1:
        parser.error("--conf must be between 0 and 1")
    if args.imgsz % 32:
        parser.error("--imgsz must be a multiple of 32")
    if args.preview and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        parser.error("--preview needs a Pi desktop display; omit it over SSH")
    return args


def pi_health():
    health = {}
    try:
        health["cpu_temperature_c"] = float(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000
    except (OSError, ValueError):
        pass
    try:
        result = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True,
                                text=True, timeout=2, check=True)
        health["throttled"] = result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return health


def save_image(cv2, path, frame):
    if not cv2.imwrite(str(path), frame):
        raise RuntimeError(f"Could not save image: {path}")


def interrupted(signum, frame):
    raise KeyboardInterrupt


def run(args, Picamera2, cv2):
    cameras = Picamera2.global_camera_info()
    print("Detected cameras:", json.dumps(cameras, default=str), flush=True)
    if args.list_cameras:
        return 0 if cameras else 1
    if args.camera >= len(cameras):
        raise RuntimeError("Camera not found. Check rpicam-hello --list-cameras, CSI cable and imx500-all.")
    model = None
    if args.mode == "yolo":
        try:
            import torch
            from ultralytics import YOLO
        except ImportError as error:
            raise RuntimeError("Install Ultralytics in the Pi virtual environment. See CAMERA.md.") from error
        torch.set_num_threads(args.threads)
        model = YOLO(args.model, task="detect")
        print(f"YOLO on Pi CPU: {args.model}, input={args.imgsz}, threads={args.threads}", flush=True)

    output = args.output or Path("camera_results") / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output.mkdir(parents=True, exist_ok=False)
    health_before = pi_health()
    camera = Picamera2(args.camera)
    started = False
    rows = []
    last_image = None
    status = "completed"
    begin = None
    elapsed = 0.0
    try:
        config = camera.create_video_configuration(
            # libcamera RGB888 gives BGR bytes, matching OpenCV and Ultralytics.
            main={"size": (args.width, args.height), "format": "RGB888"},
            controls={"FrameRate": args.fps}, buffer_count=4,
        )
        camera.configure(config)
        print("Starting camera. Initial IMX500 firmware loading can take several minutes.", flush=True)
        camera.start()
        started = True
        time.sleep(2)  # Let automatic exposure and white balance settle.

        def predict(frame):
            return model.predict(frame, imgsz=args.imgsz, conf=args.conf,
                                 device="cpu", rect=False, verbose=False)[0]

        if model is not None:
            print(f"Warming up with {args.warmup} predictions...", flush=True)
            for _ in range(args.warmup):
                predict(camera.capture_array("main"))

        begin = time.perf_counter()
        next_log = begin
        with (output / "frames.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=(
                "frame", "elapsed_s", "capture_ms", "predict_ms", "detections", "sensor_timestamp_ns",
            ))
            writer.writeheader()
            while time.perf_counter() - begin < args.seconds:
                capture_begin = time.perf_counter()
                request = camera.capture_request()
                try:
                    frame = request.make_array("main")
                    metadata = request.get_metadata()
                finally:
                    request.release()
                capture_ms = (time.perf_counter() - capture_begin) * 1000
                if frame is None or frame.size == 0:
                    raise RuntimeError("Camera returned an empty frame")
                prediction = None
                predict_ms = None
                if model is not None:
                    predict_begin = time.perf_counter()
                    prediction = predict(frame)
                    predict_ms = (time.perf_counter() - predict_begin) * 1000
                now = time.perf_counter()
                count = len(prediction.boxes) if prediction is not None else 0
                row = dict(frame=len(rows) + 1, elapsed_s=now - begin,
                           capture_ms=capture_ms, predict_ms=predict_ms,
                           detections=count, sensor_timestamp_ns=metadata.get("SensorTimestamp"))
                rows.append(row)
                writer.writerow(row)
                # Plot only the first frame, log frames and preview frames to reduce drawing overhead.
                if last_image is None or args.preview or now >= next_log:
                    last_image = prediction.plot() if prediction is not None else frame.copy()
                if len(rows) == 1:
                    save_image(cv2, output / "first_frame.jpg", last_image)
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    print(f"Image {frame.shape[1]}x{frame.shape[0]}: brightness={gray.mean():.1f}/255, "
                          f"contrast std={gray.std():.1f}", flush=True)
                    if gray.mean() < 5 or gray.std() < 2:
                        print("Image is dark or nearly uniform. Check lens cover, light and saved image.", flush=True)
                if now >= next_log:
                    print(f"{len(rows)} frames, {len(rows) / (now - begin):.2f} processed FPS"
                          + (f", predict={predict_ms:.1f} ms, detections={count}" if model else ""), flush=True)
                    if prediction is not None:
                        detections = prediction.boxes
                        names = [f"{prediction.names[int(c)]} {s:.2f}" for c, s in zip(
                            detections.cls.tolist(), detections.conf.tolist())]
                        print("Objects:", ", ".join(names[:10]) or "none above confidence threshold", flush=True)
                    handle.flush()
                    next_log = now + 1
                if args.preview:
                    cv2.imshow("Pi camera test (Q quits)", last_image)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        status = "stopped"
                        break
    except KeyboardInterrupt:
        status = "interrupted"
    finally:
        if begin is not None:
            elapsed = time.perf_counter() - begin
        try:
            if started:
                camera.stop()
        finally:
            camera.close()
            if args.preview:
                cv2.destroyAllWindows()
    if not rows:
        raise RuntimeError("No measured frames captured. Test did not pass.")
    last_image = prediction.plot() if prediction is not None else frame
    save_image(cv2, output / "last_frame.jpg", last_image)
    latencies = sorted(row["predict_ms"] for row in rows if row["predict_ms"] is not None)
    summary = {
        "status": status, "mode": args.mode, "camera": cameras[args.camera],
        "requested_capture_size": [args.width, args.height], "requested_camera_fps": args.fps,
        "frames": len(rows), "elapsed_s": elapsed, "processed_fps": len(rows) / elapsed,
        "health_before": health_before, "health_after": pi_health(),
    }
    if latencies:
        summary.update(model=args.model, inference_device="Pi CPU", imgsz=args.imgsz,
                       threads=args.threads, confidence=args.conf, warmup_frames=args.warmup,
                       predict_mean_ms=statistics.mean(latencies),
                       predict_median_ms=statistics.median(latencies),
                       predict_p95_ms=latencies[math.ceil(len(latencies) * 0.95) - 1],
                       frames_with_detections=sum(row["detections"] > 0 for row in rows))
    (output / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps(summary, indent=2, default=str))
    print(f"Saved results to {output.resolve()}")
    print("Capture succeeded. Inspect the JPEG to confirm focus, colours and scene visibility.")
    return 130 if status == "interrupted" else 0


def main(argv=None):
    args = parse_args(argv)
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    try:
        from picamera2 import Picamera2
        import cv2
    except ImportError:
        print("Run on Raspberry Pi OS with: sudo apt install python3-picamera2 python3-opencv\n"
              "For a virtual environment, use --system-site-packages. See CAMERA.md.", file=sys.stderr)
        return 1
    try:
        return run(args, Picamera2, cv2)
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(f"Test failed: {error}\nSee CAMERA.md for setup and troubleshooting.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
