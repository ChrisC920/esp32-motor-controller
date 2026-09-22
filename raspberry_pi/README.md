# Raspberry Pi 4 B programs

## Ultrasonic distance sensor on the Pi

`ultrasonic_test.py` reads a four-pin HC-SR04-style sensor directly from the Pi. It needs no ESP32 firmware or serial link. The default BCM GPIO pins do not overlap the UART presets below.

With power disconnected, wire:

- Sensor VCC → Pi 5V, physical pin 2, for a standard 5V HC-SR04.
- Sensor GND → Pi GND, physical pin 6.
- Sensor TRIG → Pi GPIO23, physical pin 16.
- Sensor ECHO → a 330 Ω resistor → Pi GPIO24, physical pin 18.
- Pi GPIO24 → a 470 Ω resistor → Pi GND. The two resistors reduce the sensor's 5V ECHO signal to about 3V.

The divider is required for a 5V ECHO output; Pi GPIO inputs accept 3.3V. A 3.3V-compatible HC-SR04P can connect ECHO directly. See the [GPIO Zero wiring guide](https://gpiozero.readthedocs.io/en/stable/api_input.html#distancesensor-hc-sr04) and [Pi 4 header pinout](https://datasheets.raspberrypi.com/rpi4/raspberry-pi-4-datasheet.pdf).

Copy and run the test on the Pi:

```sh
scp raspberry_pi/ultrasonic_test.py YOUR_USER@PI_ADDRESS:~/ultrasonic_test.py
ssh YOUR_USER@PI_ADDRESS
sudo apt install python3-gpiozero
python3 ~/ultrasonic_test.py
```

The script prints distance in centimeters every 0.5 seconds. Use Ctrl+C to stop or `--once` for one reading. Use `--trigger` and `--echo` with BCM GPIO numbers if you choose different pins. A reading at the 4 m limit is reported as no echo or out of range. Do not connect the sensor's 5V ECHO directly to Pi GPIO.

## UART motor controller

`motor_control.py` runs on Raspberry Pi OS and sends UART commands to the ESP32. The ESP32 needs the matching `motor-only` or `six-motor-pinout` firmware from this project. The Pi does not run the ESP32 C++ code.

For the `six-motor-pinout` firmware, run `python3 ~/motor_control.py --esp32-runtime six-motor-pinout`. In that mode, connect Pi TX to ESP32 GPIO3 and Pi RX to ESP32 GPIO1, plus common GND. The diagram's `PI TX` label at GPIO33 is incorrect. Isolate the board's USB serial chip TX output from GPIO3 before connecting Pi TX; unplugging USB may not isolate it on every board. The six-motor pin map and boot-pin cautions are in the project [README](../README.md#six-motor-diagram-runtime). The UART presets below still select the Pi's own TX and RX pins.

## Choose and wire a UART

Run this to show every preset:

```sh
python3 ~/motor_control.py --list-uarts
```

The Pi 4 choices are:

- `primary`: TX GPIO14, physical pin 8; RX GPIO15, physical pin 10; `/dev/serial0`.
- `uart2`: TX GPIO0, physical pin 27; RX GPIO1, physical pin 28; `/dev/ttyAMA1`.
- `uart3`: TX GPIO4, physical pin 7; RX GPIO5, physical pin 29; `/dev/ttyAMA2`.
- `uart4`: TX GPIO8, physical pin 24; RX GPIO9, physical pin 21; `/dev/ttyAMA3`.
- `uart5`: TX GPIO12, physical pin 32; RX GPIO13, physical pin 33; `/dev/ttyAMA4`.

For any preset, wire with power disconnected:

- Selected Pi TX → ESP32 GPIO16 RX.
- Selected Pi RX → ESP32 GPIO17 TX.
- Pi physical pin 6, GND → ESP32 GND.
- Keep ESP32 GND, L298N GND and motor supply negative connected together.
- Keep L298N ENA → ESP32 GPIO25, IN1 → GPIO26, IN2 → GPIO27. Remove ENA's jumper.

UART is 3.3V logic. Power the Pi and ESP32 through their usual power connections; do not join their 5V or 3V3 pins. Motor power comes from the external motor supply through the L298N. UART2 uses the HAT ID pins, and UART4 shares pins with SPI0, so avoid those presets if the corresponding interface is in use.

## Copy from your Mac

Replace `YOUR_USER` and `PI_ADDRESS` with your Pi login and hostname or IP address. From the project directory:

```sh
scp raspberry_pi/motor_control.py YOUR_USER@PI_ADDRESS:~/motor_control.py
ssh YOUR_USER@PI_ADDRESS
```

## Configure the Pi

In the SSH session:

```sh
sudo apt update
sudo apt install -y python3-serial
sudo usermod -aG dialout "$USER"
sudo raspi-config
```

Choose **Interface Options → Serial Port**. Answer **No** to the serial login shell and **Yes** to serial hardware. Finish and reboot:

```sh
sudo reboot
```

That enables the `primary` preset. To test an additional UART, add exactly one matching overlay under `[all]` in `/boot/firmware/config.txt`, such as:

```text
dtoverlay=uart3
```

Use `uart2`, `uart3`, `uart4`, or `uart5` to match the preset you want. Reboot after changing the overlay. Raspberry Pi OS documents the installed definitions through `dtoverlay -h uart3` and `/boot/firmware/overlays/README`.

Reconnect with SSH after reboot. Select the same preset in the controller:

```sh
python3 ~/motor_control.py --uart uart3
```

The default remains `primary`. You can instead edit `DEFAULT_UART` near the top of `motor_control.py`. The `--uart` option takes precedence over that default. If Linux assigned an unexpected device name, keep the pin preset and override only the device, for example `python3 ~/motor_control.py --uart uart3 --port /dev/ttyAMA2`. Check available names with `ls -l /dev/serial* /dev/ttyAMA*`.

The script uses 115200 baud, 8N1, no flow control. It sends stop on startup and requires the ESP32's stop acknowledgement before accepting motor commands. An error opening the port means the matching overlay is missing, permissions are wrong, or another process owns the device. No acknowledgement usually means TX/RX wiring is reversed, the common ground is missing, the wrong preset was selected, or the ESP32 still runs firmware without UART2 support.

## Commands

Type each command and press Enter:

```text
help
m 60
s
m -60
s
q
```

The motor starts stopped. Commands use signed percentages from -100 to 100, so `m 100` requests full forward output and `m -100` requests full reverse output. The usable starting percentage depends on the motor and load. Send `s`, wait at least 0.5 seconds, then send the opposite direction to reverse. The script displays ESP32 replies and stops if a motor command isn't acknowledged. An acknowledgement confirms the firmware accepted a command, not that the motor physically moved.

The ESP32 keeps its last motor setting until it receives `s` or `m 0`, resets, or loses power. `q`, Ctrl+C, EOF, termination and SSH hangup attempt to send `s`. If UART communication is lost, that stop command may not arrive, so manually reset or power off the ESP32 before approaching the motor. Messages produced while the script waits at its prompt are not streamed continuously.

Upload the ESP32 firmware from the Mac with `pio run -e motor-only -t upload`. Disconnect the browser motion viewer and close other serial monitors before uploading. The Pi controller uses GPIO UART, not the Mac USB serial port; avoid sending motor commands from both controllers at once.

## Sources

- [Raspberry Pi serial configuration](https://www.raspberrypi.com/documentation/computers/configuration.html)
- [pySerial API](https://pyserial.readthedocs.io/en/stable/pyserial_api.html)
