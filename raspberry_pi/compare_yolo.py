#!/usr/bin/env python3
"""Compare YOLO26n and YOLO11n, PyTorch and NCNN, using the same camera images."""

import argparse
import csv
from datetime import datetime
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import time

from camera_test import pi_health, positive_int, save_image

MODELS = ("yolo26n", "yolo11n")


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--imgsz", type=positive_int, default=320)
    parser.add_argument("--frames", type=positive_int, default=60)
    parser.add_argument("--repeats", type=positive_int, default=2)
    parser.add_argument("--warmup", type=positive_int, default=5)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--input", type=Path, help="reuse a folder of JPEG images instead of capturing")
    parser.add_argument("--output", type=Path, help="new result folder")
    parser.add_argument("--seed", type=int, default=42, help="seed for shuffled test order")
    parser.add_argument("--cooldown", type=int, default=10, help="seconds between tests")
    # Internal subprocess options. Every case gets a fresh process to release model memory.
    parser.add_argument("--worker", choices=("export", "benchmark"), help=argparse.SUPPRESS)
    parser.add_argument("--model", help=argparse.SUPPRESS)
    parser.add_argument("--format", choices=("pt", "ncnn"), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.imgsz % 32:
        parser.error("--imgsz must be a multiple of 32")
    if not 0 <= args.conf <= 1:
        parser.error("--conf must be between 0 and 1")
    if args.camera < 0 or args.cooldown < 0:
        parser.error("--camera and --cooldown must be zero or greater")
    return args


def capture_images(args, destination):
    import cv2
    from picamera2 import Picamera2

    cameras = Picamera2.global_camera_info()
    if args.camera >= len(cameras):
        raise RuntimeError("Camera not found. Run camera_test.py --list-cameras first.")
    destination.mkdir()
    camera = Picamera2(args.camera)
    started = False
    try:
        camera.configure(camera.create_video_configuration(
            main={"size": (640, 480), "format": "RGB888"},
            controls={"FrameRate": 10}, buffer_count=4,
        ))
        print("Starting camera; initial IMX500 firmware loading can take several minutes.", flush=True)
        camera.start()
        started = True
        time.sleep(2)
        print(f"Capturing {args.frames} reference images. Keep your test objects in view.", flush=True)
        for index in range(args.frames):
            save_image(cv2, destination / f"{index:05d}.jpg", camera.capture_array("main"))
    finally:
        try:
            if started:
                camera.stop()
        finally:
            camera.close()
    return cameras[args.camera]


def worker(args):
    import torch
    from ultralytics import YOLO

    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    model = YOLO(args.model, task="detect")
    if args.worker == "export":
        # FP32 exports, fixed square input, no embedded NMS.
        exported = model.export(format="ncnn", imgsz=args.imgsz, half=False,
                                batch=1, device="cpu")
        (args.output / "export.json").write_text(json.dumps({"path": str(Path(exported).resolve())}))
        return

    import cv2
    paths = [Path(path) for path in json.loads((args.input / "manifest.json").read_text())]
    first = cv2.imread(str(paths[0]))
    if first is None:
        raise RuntimeError(f"Cannot read {paths[0]}")

    def predict(frame):
        return model.predict(frame, imgsz=args.imgsz, conf=args.conf, iou=0.7,
                             max_det=300, device="cpu", half=False, rect=False, verbose=False)[0]

    # Initializes the backend before measuring. Model loading and compilation are excluded.
    for _ in range(args.warmup):
        predict(first)
    health_before = pi_health()
    rows = []
    started = time.perf_counter()
    first_result = last_result = None
    for index, path in enumerate(paths):
        frame = cv2.imread(str(path))
        if frame is None:
            raise RuntimeError(f"Cannot read {path}")
        begin = time.perf_counter()
        result = predict(frame)
        duration = (time.perf_counter() - begin) * 1000
        rows.append({"frame": index, "predict_ms": duration, "detections": len(result.boxes)})
        if first_result is None:
            first_result = result
        last_result = result
    elapsed = time.perf_counter() - started
    # Drawing and writing results happen after the timed loop for all four cases.
    health_after = pi_health()
    save_image(cv2, args.output / "first_detections.jpg", first_result.plot())
    save_image(cv2, args.output / "last_detections.jpg", last_result.plot())
    latencies = sorted(row["predict_ms"] for row in rows)
    summary = {
        "model": args.model, "format": args.format, "frames": len(rows),
        "imgsz": args.imgsz, "confidence": args.conf, "warmup": args.warmup,
        "predict_mean_ms": statistics.mean(latencies),
        "predict_median_ms": statistics.median(latencies),
        "predict_p95_ms": latencies[math.ceil(len(latencies) * .95) - 1],
        "prediction_fps": len(rows) * 1000 / sum(latencies),
        "replay_fps": len(rows) / elapsed, "elapsed_s": elapsed,
        "mean_detections": statistics.mean(row["detections"] for row in rows),
        "health_before": health_before, "health_after": health_after,
    }
    with (args.output / "frames.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


def child(options, cwd=None):
    env = dict(os.environ, OMP_NUM_THREADS="4", MKL_NUM_THREADS="4", OPENBLAS_NUM_THREADS="4")
    subprocess.run([sys.executable, str(Path(__file__).resolve()), *options],
                   cwd=cwd, env=env, check=True)


def compare(args):
    output = (args.output or Path("camera_results") / datetime.now().strftime("compare_%Y%m%d_%H%M%S_%f")).resolve()
    output.mkdir(parents=True, exist_ok=False)
    images = output / "images"
    source_camera = None
    if args.input:
        # Copy the inputs so this result folder is self-contained.
        import shutil
        paths = sorted(path for path in args.input.resolve().iterdir()
                       if path.is_file() and path.suffix.lower() in (".jpg", ".jpeg"))[:args.frames]
        if not paths:
            raise RuntimeError("--input contains no JPEG images")
        images.mkdir()
        for index, path in enumerate(paths):
            shutil.copyfile(path, images / f"{index:05d}.jpg")
    else:
        source_camera = capture_images(args, images)
    paths = sorted(images.glob("*.jpg"))
    (images / "manifest.json").write_text(json.dumps([str(path) for path in paths]))
    cases = []
    for name in MODELS:
        directory = output / "models" / name
        directory.mkdir(parents=True)
        print(f"Preparing {name} PyTorch weights and NCNN export at {args.imgsz}...", flush=True)
        child(["--worker", "export", "--model", name + ".pt", "--imgsz", str(args.imgsz),
               "--output", str(directory)], cwd=directory)
        exported = json.loads((directory / "export.json").read_text())["path"]
        cases.extend([(name, "pt", str(directory / (name + ".pt"))), (name, "ncnn", exported)])
    versions = {}
    for package in ("ultralytics", "torch", "ncnn", "numpy", "opencv-python"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            pass
    records = []
    schedule = []
    rng = random.Random(args.seed)
    for repeat in range(1, args.repeats + 1):
        order = list(cases)
        rng.shuffle(order)
        schedule.extend((repeat, *case) for case in order)
    (output / "settings.json").write_text(json.dumps({
        "imgsz": args.imgsz, "frames": len(paths), "repeats": args.repeats,
        "confidence": args.conf, "iou": 0.7, "max_det": 300,
        "warmup": args.warmup, "seed": args.seed,
        "cooldown_s": args.cooldown, "square_input": True,
        "torch_threads": 4, "ncnn_threads": "Ultralytics backend default",
        "precision": "FP32 export; backend optimizations remain enabled",
        "python": sys.version, "platform": platform.platform(),
        "packages": versions, "camera": source_camera, "schedule": schedule,
    }, indent=2, default=str) + "\n")
    fields = ("model", "format", "repeat", "predict_mean_ms", "predict_median_ms",
              "predict_p95_ms", "prediction_fps", "replay_fps", "mean_detections")
    with (output / "comparison.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for number, (repeat, name, fmt, path) in enumerate(schedule, 1):
            print(f"Test {number}/{len(schedule)}: {name} {fmt}, repeat {repeat}. "
                  f"Cooling pause {args.cooldown}s...", flush=True)
            time.sleep(args.cooldown)
            folder = output / f"{name}_{fmt}_repeat{repeat}"
            folder.mkdir()
            child(["--worker", "benchmark", "--model", path, "--format", fmt,
                   "--input", str(images), "--output", str(folder),
                   "--imgsz", str(args.imgsz), "--conf", str(args.conf), "--warmup", str(args.warmup)])
            summary = json.loads((folder / "summary.json").read_text())
            row = {key: summary[key] for key in fields if key not in ("model", "repeat")}
            row.update(model=name, repeat=repeat)
            records.append(row)
            writer.writerow(row)
            handle.flush()
            print(f"{name} {fmt}: {summary['predict_mean_ms']:.1f} ms, "
                  f"{summary['prediction_fps']:.2f} prediction FPS", flush=True)
    print("\nAverage across repeats:")
    print(f"{'Model':12} {'Format':7} {'Mean ms':>10} {'Predict FPS':>12} {'Replay FPS':>11}")
    for name, fmt, _ in cases:
        selected = [row for row in records if row["model"] == name and row["format"] == fmt]
        print(f"{name:12} {fmt:7} {statistics.mean(r['predict_mean_ms'] for r in selected):10.1f} "
              f"{statistics.mean(r['prediction_fps'] for r in selected):12.2f} "
              f"{statistics.mean(r['replay_fps'] for r in selected):11.2f}")
    print(f"\nSaved results and detection images to {output}")


def main(argv=None):
    args = arguments(argv)
    try:
        if args.worker:
            worker(args)
        else:
            compare(args)
        return 0
    except KeyboardInterrupt:
        print("Stopped. Completed results remain in the output directory.", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"Comparison failed: {error}\nCompleted results are preserved. See CAMERA.md.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
