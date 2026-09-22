#!/usr/bin/env python3
"""Read an HC-SR04-style ultrasonic sensor directly from Raspberry Pi GPIO."""

import argparse
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trigger", type=int, default=23,
                        help="BCM GPIO for TRIG (default: 23, physical pin 16)")
    parser.add_argument("--echo", type=int, default=24,
                        help="BCM GPIO for ECHO (default: 24, physical pin 18)")
    parser.add_argument("--interval", type=float, default=0.5,
                        help="seconds between readings (default: 0.5)")
    parser.add_argument("--once", action="store_true",
                        help="read once and exit")
    args = parser.parse_args()
    if args.interval < 0.1:
        parser.error("--interval must be at least 0.1 seconds")
    if args.trigger == args.echo:
        parser.error("TRIG and ECHO must use different GPIO pins")

    try:
        from gpiozero import DistanceSensor
    except ImportError:
        sys.exit("Install GPIO Zero on the Pi: sudo apt install python3-gpiozero")

    print(f"TRIG=GPIO{args.trigger}, ECHO=GPIO{args.echo}; press Ctrl+C to stop.")
    try:
        with DistanceSensor(echo=args.echo, trigger=args.trigger,
                            max_distance=4, queue_len=5) as sensor:
            while True:
                distance_cm = sensor.distance * 100
                if distance_cm >= 399:
                    print("No echo or target beyond 4 m", flush=True)
                else:
                    print(f"distance={distance_cm:.1f} cm", flush=True)
                if args.once:
                    break
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
