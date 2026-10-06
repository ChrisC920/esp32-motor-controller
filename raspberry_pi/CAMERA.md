# Raspberry Pi 4B AI Camera test

`camera_test.py` is a separate Python program that runs on the Pi. It uses Picamera2 for the CSI camera and OpenCV for images and optional preview. No PlatformIO build or ESP32 is involved.

Start with camera capture, then test the IMX500's bundled detector, then benchmark YOLO26n on the Pi CPU. These tests answer different questions. A working image does not prove the AI processor works, and a detector finding no objects does not mean the camera is broken.

## Connect and install

Power off the Pi before inserting the ribbon cable. Use the Pi 4B's 15-pin CSI camera connector, not the display connector. Seat the correct cable straight and latch both ends. Follow the [Raspberry Pi camera installation instructions](https://www.raspberrypi.com/documentation/accessories/camera.html) for cable orientation.

Use 64-bit Raspberry Pi OS Bookworm or newer with current camera packages. On the Pi:

```sh
sudo apt update
sudo apt full-upgrade
sudo apt install imx500-all python3-picamera2 python3-opencv python3-venv python3-pip
sudo reboot
```

The [official AI Camera setup](https://www.raspberrypi.com/documentation/accessories/ai-camera.html) supports Pi 4B and requires the IMX500 firmware. Initial firmware/model loading can take several minutes. Wait for startup rather than interrupting it immediately.

Copy the program and this guide from the Mac, replacing `YOUR_PI_USER` and `YOUR_PI_HOST` with your SSH login and host:

```sh
ssh YOUR_PI_USER@YOUR_PI_HOST 'mkdir -p ~/camera-test'
scp raspberry_pi/camera_test.py raspberry_pi/CAMERA.md YOUR_PI_USER@YOUR_PI_HOST:~/camera-test/
ssh YOUR_PI_USER@YOUR_PI_HOST
cd ~/camera-test
```

## 1. Check the camera image

```sh
rpicam-hello --list-cameras
python3 camera_test.py --list-cameras
python3 camera_test.py --seconds 10
```

The camera list should identify `imx500`. The program defaults to camera index 0 and requests a 640 x 480 stream at 30 FPS. It saves `first_frame.jpg`, `last_frame.jpg`, `frames.csv` and `summary.json` in a new directory under `camera_results/`. Check the JPEG for a visible scene, correct colours and focus. The test checks streaming, not the full 12MP resolution or every sensor mode. The lens focus is manually adjustable; follow the camera's focus instructions if the image is blurry.

Headless operation is the default, so this works through SSH. Copy images back with `scp -r YOUR_PI_USER@YOUR_PI_HOST:~/camera-test/camera_results ./pi-camera-results` from the Mac. On a Pi with a desktop display, add `--preview` for a live window. Press Q or Ctrl+C to stop. Use `--camera 1` if the camera list indicates a different index. `--output my-test` selects a new result directory; existing directories are rejected to preserve earlier results.

## 2. Check the camera's AI processor

Run the bundled MobileNet SSD detector before trying a custom model. The [official example](https://www.raspberrypi.com/documentation/accessories/ai-camera.html) runs inference on the IMX500 and draws boxes on the Pi. With a local desktop display:

```sh
rpicam-hello -t 0s --post-process-file /usr/share/rpi-camera-assets/imx500_mobilenet_ssd.json --viewfinder-width 640 --viewfinder-height 480 --framerate 30
```

Over SSH without a display, save a 10-second annotated video:

```sh
rpicam-vid --nopreview -t 10s -o imx500_detection.h264 --post-process-file /usr/share/rpi-camera-assets/imx500_mobilenet_ssd.json --width 640 --height 480 --framerate 30
```

Copy the video to the Mac and open it in a player supporting raw H.264, such as VLC. Point the camera at a person or familiar everyday objects. Correct boxes and labels demonstrate that the on-sensor detector and host post-processing work. This demo does not measure per-inference latency. The requested video FPS is not a measurement of fresh AI results per second.

## 3. Test YOLO26n on the Pi CPU

The [Ultralytics Pi guide](https://docs.ultralytics.com/guides/raspberry-pi/) supports YOLO26 on Pi 4 and Pi 5 and recommends NCNN for ARM inference. Its [IMX500 integration guide](https://docs.ultralytics.com/integrations/sony-imx500/) explicitly limits on-sensor support to YOLOv8n and YOLO11n. YOLO26 is marked unsupported there, despite a generic export table displaying a YOLO26 IMX path. Use YOLO11n if the goal is YOLO running inside the camera. A `.pt` file or NCNN model runs on the Pi CPU in this program.

Create a virtual environment that can access the system Picamera2/libcamera packages:

```sh
cd ~/camera-test
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install 'ultralytics>=8.4.0'
python camera_test.py --mode yolo --model yolo26n.pt --imgsz 320 --seconds 30
```

The first YOLO run downloads the weights and needs internet access. Installation needs enough free disk space for PyTorch and dependencies. Start at input size 320, then try 640 to compare detection quality and speed. Stream size defaults to 640 x 480 independently of model input size. Both inference and drawing boxes require CPU time; do not expect the 30 FPS camera request to produce 30 YOLO predictions per second.

For the NCNN comparison, export at the same input size and use the resulting directory:

```sh
python -c 'from ultralytics import YOLO; YOLO("yolo26n.pt").export(format="ncnn", imgsz=320)'
python camera_test.py --mode yolo --model yolo26n_ncnn_model --imgsz 320 --seconds 30
```

Export may install extra dependencies and takes time. Re-export at 640 before testing NCNN with `--imgsz 640`. Keep exported models in separate directories if you want to retain both sizes. Use `--threads 2` or `--threads 4` to compare CPU usage. Add `--preview` on a local desktop to see detections live.

The CSV records capture wait time, prediction time and detection count per processed frame. The JSON includes mean, median and p95 prediction latency, processed FPS and available temperature/throttling readings. Prediction time includes preprocessing, inference and post-processing inside `model.predict`. Processed FPS includes capture, drawing, logging, JPEG writes and optional display. Startup, exposure settling and three warmup predictions are excluded. Camera capture can skip frames while the CPU is busy. These are live pipeline measurements, not isolated neural network inference benchmarks or accuracy measurements. Each invocation gets a separate output folder.

## Troubleshooting

- No `imx500` in the camera list: power down, reseat the ribbon, confirm the CSI socket and cable type, then verify firmware installation and reboot. Do not use the legacy camera stack or `cv2.VideoCapture(0)` for this CSI test.
- Camera busy: close other `rpicam` or Picamera2 processes before starting another test.
- Dark, uniform or blurry image: check the lens cover, illumination and manual focus. Capturing bytes alone is not proof of a useful image.
- Picamera2 missing inside the virtual environment: recreate it with `--system-site-packages`; install Picamera2 and libcamera through apt.
- NumPy or OpenCV import errors after pip installation: check `python -m pip check` and the reported conflicting versions. The camera-only test can still run with system `python3` outside the environment. Recreate the environment with compatible versions rather than replacing OS camera packages with pip packages.
- YOLO install fails: confirm a 64-bit OS with `uname -m`, which should report `aarch64`, and check free space with `df -h`. This program has no GPU or AI HAT backend.
- Low or declining FPS: compare NCNN, smaller input and headless operation. Check cooling, power and `vcgencmd get_throttled`. A nonzero throttle bitmask can include historical events; it is not automatically a current temperature problem.

Local syntax and simulated-camera checks cannot verify the CSI cable, sensor, firmware, installed Pi packages or actual FPS. Run these steps on the Pi to measure your hardware.
