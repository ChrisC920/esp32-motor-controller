#!/usr/bin/env python3
"""Isolate native-library crashes without accessing the camera or downloading models."""

import importlib.metadata
import platform
from pathlib import Path
import signal
import subprocess
import sys


PROBES = (
    ("NumPy import and matrix multiplication",
     "import numpy as np; print(np.__version__, np.__file__, flush=True); "
     "print((np.ones((32,32)) @ np.ones((32,32)))[0,0], flush=True)"),
    ("OpenCV import and image conversion",
     "import cv2, numpy as np; print(cv2.__version__, cv2.__file__, flush=True); "
     "print(cv2.cvtColor(np.zeros((32,32,3), dtype=np.uint8), cv2.COLOR_BGR2GRAY).shape, flush=True)"),
    ("PyTorch import",
     "import torch; print(torch.__version__, torch.__file__, flush=True)"),
    ("PyTorch CPU convolution",
     "import torch; torch.set_num_threads(4); print(torch.__version__, flush=True); "
     "layer=torch.nn.Conv2d(3,16,3).eval(); "
     "print(layer(torch.zeros(1,3,64,64)).shape, flush=True)"),
    ("Torchvision import and CPU NMS",
     "import torch, torchvision; print(torchvision.__version__, torchvision.__file__, flush=True); "
     "print(torchvision.ops.nms(torch.tensor([[0.,0.,10.,10.]]), torch.tensor([0.9]), 0.5), flush=True)"),
    ("Ultralytics YOLO import",
     "import ultralytics; from ultralytics import YOLO; "
     "print(ultralytics.__version__, ultralytics.__file__, flush=True)"),
    ("NCNN import", "import ncnn; print(ncnn.__file__, flush=True)"),
)


def probe(label, code):
    print(f"\n--- {label} ---", flush=True)
    # Prevent large core dumps on Linux. The diagnostic itself imports only the standard library.
    prefix = "import resource; resource.setrlimit(resource.RLIMIT_CORE, (0, 0)); " if sys.platform == "linux" else ""
    try:
        result = subprocess.run([sys.executable, "-u", "-c", prefix + code],
                                capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        print("TIMEOUT after 60 seconds", flush=True)
        return False
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip())
    if result.returncode == 0:
        print("PASS", flush=True)
        return True
    if result.returncode < 0:
        number = -result.returncode
        try:
            name = signal.Signals(number).name
        except ValueError:
            name = str(number)
        print(f"CRASH: {name}" + (" (Illegal instruction)" if number == signal.SIGILL else ""), flush=True)
    else:
        print(f"FAILED: exit code {result.returncode}", flush=True)
    return False


def main():
    print(f"Python: {sys.version}\nExecutable: {sys.executable}\nMachine: {platform.machine()}")
    for path in ("/etc/os-release", "/proc/device-tree/model"):
        try:
            print(f"{path}:\n{Path(path).read_text().strip().strip(chr(0))}")
        except OSError:
            pass
    print("\nInstalled package versions, read without importing the packages:")
    for package in ("numpy", "opencv-python", "opencv-python-headless", "torch", "torchvision", "ultralytics", "ncnn"):
        try:
            print(f"{package}: {importlib.metadata.version(package)}")
        except importlib.metadata.PackageNotFoundError:
            print(f"{package}: no pip metadata; may be absent or installed through apt")
    failures = [label for label, code in PROBES if not probe(label, code)]
    print("\nFailing probes:", "; ".join(failures) or "none")
    print("An absent NCNN package is expected before the first NCNN export.")
    print("Passing these probes does not verify YOLO model loading or inference.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
