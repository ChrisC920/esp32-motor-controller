#!/usr/bin/env python3
"""Interactive UART controller for the project's ESP32 motor-only firmware."""
import argparse
import signal
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("Install pySerial first: sudo apt install python3-serial")


def exchange(port, command, expected=None):
    """Read a bounded reply; never claim motion without an ESP32 acknowledgement."""
    port.reset_input_buffer()
    port.write((command + "\n").encode("ascii"))
    deadline = time.monotonic() + 2.0
    matched = False
    while time.monotonic() < deadline:
        line = port.read_until(b"\n", size=256).decode("utf-8", errors="replace").strip()
        if not line:
            continue
        print("ESP32:", line, flush=True)
        if expected and line == expected:
            return True
        if not expected:
            matched = True
    return matched


def parse_command(text):
    words = text.strip().lower().split()
    if words in (["s"], ["help"]):
        return words[0]
    if len(words) == 2 and words[0] == "m":
        try:
            speed = int(words[1])
        except ValueError:
            return None
        if -255 <= speed <= 255:
            return f"m {speed}"
    return None


def interrupted(signum, frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="/dev/serial0", help="Pi GPIO UART device")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    try:
        with serial.Serial(args.port, 115200, timeout=0.1, write_timeout=1,
                           exclusive=True, rtscts=False, dsrdtr=False) as port:
            try:
                print(f"Opened {args.port} at 115200 baud, 8N1.")
                if not exchange(port, "s", "Motor stopped."):
                    print("No stop acknowledgement. Check UART wiring and upload the UART motor-only firmware.", file=sys.stderr)
                    return 1
                print("m 150 = forward; m -150 = reverse; s = stop; help = firmware help; q = quit")
                print("Commands expire after 10 seconds. Repeat a motor command to continue running.")
                print("To reverse: send s, wait at least 0.5 seconds, then send the opposite speed.")
                while True:
                    text = input("motor> ")
                    if text.strip().lower() in ("q", "quit", "exit"):
                        break
                    command = parse_command(text)
                    if command is None:
                        print("Use m <integer -255..255>, s, help, or q.")
                        continue
                    expected = None
                    if command == "s":
                        expected = "Motor stopped."
                    elif command.startswith("m "):
                        expected = "Motor PWM: " + command[2:]
                    if not exchange(port, command, expected):
                        print("Requested command was not acknowledged. Sending stop.", file=sys.stderr)
                        if not exchange(port, "s", "Motor stopped."):
                            print("No stop reply. ESP32 command timeout remains the fallback.", file=sys.stderr)
                            return 1
            finally:
                # Normal quit, Ctrl+C, EOF, SIGTERM and SSH hangup attempt a stop.
                try:
                    port.write(b"s\n")
                    time.sleep(0.05)
                except (serial.SerialException, OSError):
                    pass
    except (KeyboardInterrupt, EOFError):
        print("\nExited; stop requested.")
    except (serial.SerialException, OSError) as error:
        print(f"UART error: {error}\nCheck UART enablement, dialout membership, and other serial monitors.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
