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

# Change this one value to select a different enabled Pi 4 UART.
DEFAULT_UART = "primary"

# BCM GPIO numbers and physical header pins for Raspberry Pi 4 Model B.
UARTS = {
    "primary": {
        "device": "/dev/serial0",
        "tx_gpio": 14,
        "tx_pin": 8,
        "rx_gpio": 15,
        "rx_pin": 10,
        "overlay": None,
    },
    "uart2": {
        "device": "/dev/ttyAMA1",
        "tx_gpio": 0,
        "tx_pin": 27,
        "rx_gpio": 1,
        "rx_pin": 28,
        "overlay": "uart2",
    },
    "uart3": {
        "device": "/dev/ttyAMA2",
        "tx_gpio": 4,
        "tx_pin": 7,
        "rx_gpio": 5,
        "rx_pin": 29,
        "overlay": "uart3",
    },
    "uart4": {
        "device": "/dev/ttyAMA3",
        "tx_gpio": 8,
        "tx_pin": 24,
        "rx_gpio": 9,
        "rx_pin": 21,
        "overlay": "uart4",
    },
    "uart5": {
        "device": "/dev/ttyAMA4",
        "tx_gpio": 12,
        "tx_pin": 32,
        "rx_gpio": 13,
        "rx_pin": 33,
        "overlay": "uart5",
    },
}


def print_uarts():
    for name, config in UARTS.items():
        overlay = f", enable with dtoverlay={config['overlay']}" if config["overlay"] else ""
        print(
            f"{name:7} {config['device']:12} "
            f"TX GPIO{config['tx_gpio']} pin {config['tx_pin']}, "
            f"RX GPIO{config['rx_gpio']} pin {config['rx_pin']}{overlay}"
        )


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
        if -100 <= speed <= 100:
            return f"m {speed}"
    return None


def interrupted(signum, frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--uart", choices=UARTS, default=DEFAULT_UART,
        help=f"Pi 4 UART/pin preset (default: {DEFAULT_UART})",
    )
    parser.add_argument(
        "--port", help="override the preset's Linux serial device path",
    )
    parser.add_argument(
        "--list-uarts", action="store_true", help="show Pi 4 UART presets and exit",
    )
    args = parser.parse_args()
    if args.list_uarts:
        print_uarts()
        return 0
    uart = UARTS[args.uart]
    device = args.port or uart["device"]
    print(
        f"Using {args.uart}: Pi TX GPIO{uart['tx_gpio']} (pin {uart['tx_pin']}) "
        f"to ESP32 GPIO16, Pi RX GPIO{uart['rx_gpio']} (pin {uart['rx_pin']}) "
        f"to ESP32 GPIO17."
    )
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    try:
        with serial.Serial(device, 115200, timeout=0.1, write_timeout=1,
                           exclusive=True, rtscts=False, dsrdtr=False) as port:
            try:
                print(f"Opened {device} at 115200 baud, 8N1.")
                if not exchange(port, "s", "Motor stopped."):
                    print("No stop acknowledgement. Check UART wiring and upload the UART motor-only firmware.", file=sys.stderr)
                    return 1
                print("m 60 = 60% forward; m -60 = 60% reverse; s = stop; help = firmware help; q = quit")
                print("The motor keeps running until you send s, m 0, reset the ESP32, or remove power.")
                print("To reverse: send s, wait at least 0.5 seconds, then send the opposite speed.")
                while True:
                    text = input("motor> ")
                    if text.strip().lower() in ("q", "quit", "exit"):
                        break
                    command = parse_command(text)
                    if command is None:
                        print("Use m <integer -100..100 percent>, s, help, or q.")
                        continue
                    expected = None
                    if command == "s":
                        expected = "Motor stopped."
                    elif command.startswith("m "):
                        expected = "Motor: " + command[2:] + "%"
                    if not exchange(port, command, expected):
                        print("Requested command was not acknowledged. Sending stop.", file=sys.stderr)
                        if not exchange(port, "s", "Motor stopped."):
                            print("No stop reply. Manually stop or reset the ESP32 before approaching the motor.", file=sys.stderr)
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
