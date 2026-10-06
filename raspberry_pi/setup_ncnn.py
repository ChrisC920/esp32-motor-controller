#!/usr/bin/env python3
"""Install NCNN in the current virtual environment and verify it in a fresh process."""

import os
from pathlib import Path
import subprocess
import sys


def check_import():
    code = "import ncnn; print('NCNN imported:', ncnn.__file__, flush=True); net = ncnn.Net(); print('NCNN Net created', flush=True)"
    if sys.platform == "linux":
        code = "import resource; resource.setrlimit(resource.RLIMIT_CORE, (0, 0)); " + code
    result = subprocess.run([sys.executable, "-u", "-c", code], capture_output=True, text=True, timeout=60)
    if result.stdout:
        print(result.stdout.strip(), flush=True)
    if result.stderr:
        print(result.stderr.strip(), flush=True)
    if result.returncode == -4:
        print("NCNN crashed with SIGILL (Illegal instruction). This is a native build issue.", flush=True)
    return result


def main():
    print(f"Installing/checking NCNN for: {sys.executable}", flush=True)
    if sys.prefix == sys.base_prefix:
        print("Activate .venv-pi4 or .venv first. This script installs only inside a virtual environment.", file=sys.stderr)
        return 1
    try:
        initial = check_import()
        if initial.returncode == 0:
            print("NCNN is already available. Rerun the original camera/benchmark command.")
            return 0
        if "No module named 'ncnn'" not in initial.stderr:
            print("NCNN exists but failed to load. Share the error above; no packages were changed.", file=sys.stderr)
            return 1
        environment = dict(os.environ)
        constraints = Path(sys.prefix) / "vision-constraints.txt"
        if constraints.exists():
            environment["PIP_CONSTRAINT"] = str(constraints)
        # Use a wheel rather than starting a long source build implicitly on the Pi.
        subprocess.run([sys.executable, "-m", "pip", "install", "--only-binary=:all:", "ncnn"],
                       check=True, env=environment)
        if check_import().returncode != 0:
            print("Installation completed, but NCNN failed its fresh-process check.", file=sys.stderr)
            return 1
        print("NCNN import and Net creation passed. Rerun the original command; model inference still needs testing.")
        return 0
    except subprocess.CalledProcessError:
        print("NCNN installation failed. Share pip's final error lines. No source build was attempted.", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print("NCNN import timed out after 60 seconds.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
