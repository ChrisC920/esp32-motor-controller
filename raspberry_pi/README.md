# Raspberry Pi 4 B controller

This Python program runs on Raspberry Pi OS and sends UART commands to the ESP32. The ESP32 needs the updated `motor-only` firmware from this project. The Pi does not run the ESP32 C++ code.

## Wire with power disconnected

- Pi physical pin 8, GPIO14 TX → ESP32 GPIO16 RX.
- Pi physical pin 10, GPIO15 RX → ESP32 GPIO17 TX.
- Pi physical pin 6, GND → ESP32 GND.
- Keep ESP32 GND, L298N GND and motor supply negative connected together.
- Keep L298N ENA → ESP32 GPIO25, IN1 → GPIO26, IN2 → GPIO27. Remove ENA's jumper.

UART is 3.3V logic. Power the Pi and ESP32 through their usual power connections; do not join their 5V or 3V3 pins. Motor power comes from the external motor supply through the L298N.

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

Reconnect with SSH after reboot. Confirm the UART exists and run the controller:

```sh
ls -l /dev/serial0
python3 ~/motor_control.py
```

The script uses `/dev/serial0`, 115200 baud, 8N1, no flow control. It sends stop on startup and requires the ESP32's stop acknowledgement before accepting motor commands. An error opening the port means UART configuration, permissions or another monitor needs attention. No acknowledgement usually means incorrect TX/RX wiring, missing common ground, or the ESP32 still running firmware without UART2 support.

## Commands

Type each command and press Enter:

```text
help
m 150
s
m -150
s
q
```

The motor starts stopped. `m 255` requests full forward PWM; the usable starting duty depends on the motor and load. Send `s`, wait at least 0.5 seconds, then send the opposite speed to reverse. The script displays ESP32 replies and stops if a motor command isn't acknowledged. An acknowledgement confirms the firmware accepted a command, not that the motor physically moved.

The ESP32 stops after 10 seconds without a motor command. Repeat the command to continue. This script deliberately sends no automatic keepalive. `q`, Ctrl+C, EOF, termination and SSH hangup attempt a stop; if communication is lost, the ESP32 timeout is the fallback. Messages produced while the script waits at its prompt are not streamed continuously.

Upload the ESP32 firmware from the Mac with `pio run -e motor-only -t upload`. Disconnect the browser motion viewer and close other serial monitors before uploading. The Pi controller uses GPIO UART, not the Mac USB serial port; avoid sending motor commands from both controllers at once.

## Sources

- [Raspberry Pi serial configuration](https://www.raspberrypi.com/documentation/computers/configuration.html)
- [pySerial API](https://pyserial.readthedocs.io/en/stable/pyserial_api.html)
