#!/usr/bin/env python3
"""Test PyTorch convolution with MKLDNN disabled, without accessing the camera."""

import sys

from check_vision_install import probe


CONVOLUTION_TEST = """
import torch
print("Torch:", torch.__version__, flush=True)
torch.backends.mkldnn.enabled = False
torch.set_num_threads(4)
print("MKLDNN enabled:", torch.backends.mkldnn.enabled, flush=True)
with torch.no_grad():
    layer = torch.nn.Conv2d(3, 16, 3).eval()
    result = layer(torch.zeros(1, 3, 64, 64))
print("Convolution passed:", result.shape, flush=True)
"""


def main():
    print(f"Python executable: {sys.executable}", flush=True)
    if probe("PyTorch CPU convolution with MKLDNN disabled", CONVOLUTION_TEST):
        print("This convolution passed. Full YOLO inference still needs testing.")
        return 0
    print("The test failed with MKLDNN disabled. Share the output to choose the next repair.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
