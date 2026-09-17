# ESP32 motor and accelerometer

Controls one brushed DC motor through channel A of an L298N module and prints LIS2DH/LIS2DH12 acceleration over USB serial. The sensor does not control the motor. Uses the existing NodeMCU-32S target for a classic ESP32. GPIO assignments may need adjustment for a different development board.

## Wiring

Disconnect power before wiring. Use GPIO numbers printed on the board, not header positions.

- ESP32 GPIO25 to L298N ENA. Remove the ENA jumper so PWM controls this input. Add a 10 kΩ resistor from ENA to GND to keep the motor disabled during reset.
- ESP32 GPIO26 to L298N IN1.
- ESP32 GPIO27 to L298N IN2.
- Motor wires to L298N OUT1 and OUT2.
- External motor supply positive to the L298N motor supply terminal, often marked +12V or VS. Choose voltage and current for your motor and module, allowing for driver voltage drop and motor stall current. Do not power the motor from the ESP32.
- Motor supply negative, L298N GND, ESP32 GND and accelerometer GND must connect together.
- ESP32 3V3 to accelerometer VCC.
- ESP32 GPIO22 to accelerometer SDA.
- ESP32 GPIO23 to accelerometer SCL.

Power the ESP32 by USB. The L298N also needs its logic supply: follow your module's instructions for the separate 5V regulator jumper. That jumper is different from ENA. Do not connect the L298N 5V terminal to ESP32 3V3 or a USB-powered ESP32 power rail. Keep I²C pull-ups at 3.3V. If the sensor exposes CS, hold CS high for I²C; hold SA0 low for address 0x18 or high for 0x19. Breakout boards often handle these connections already. INT pins are unused.

This assumes a complete L298N module with flyback diodes, not a bare L298N chip. Secure the motor before testing. The stop command lets it coast; it is not a mechanical brake. A 0.5-second reversal pause does not guarantee that every motor has stopped spinning.

## Build and use

1. Build with PlatformIO's Build button or `pio run`.
2. Connect the ESP32 by USB, then use Upload or `pio run -t upload`.
3. Open the serial monitor at 115200 baud with newline line endings. With the CLI, use `pio device monitor`. Press reset to see startup messages if needed.
4. Send `m 150` to run forward at PWM duty 150 out of 255. Send `s` to stop. Send `m -150` to run in reverse. Send `m 0` to stop as well.

Motor commands accept integers from -255 to 255. Direction names depend on motor wiring. Small PWM values may not start the motor. The motor starts stopped, and stops after 10 seconds without another valid motor command. Repeat the command to continue running. Change `COMMAND_TIMEOUT_MS` in `src/main.cpp` if needed. On a direction change, the firmware stops first; wait at least 0.5 seconds and resend the command to reverse.

Acceleration prints five times per second as `ax`, `ay`, and `az` in g, alongside the current motor PWM. The sensor runs at 100 Hz in high-resolution ±2g mode. Readings include gravity, so a stationary, level sensor should show about ±1g on the vertical axis and near zero on the other two. These are acceleration readings, not speed or position.

The firmware probes I²C addresses 0x18 and 0x19 and checks the device identity. If the sensor is absent or a read fails, it prints an error. Motor commands remain available independently. After correcting wiring with power off and reconnecting, reset or send `retry` to stop the motor and initialize the sensor again. Send `help` to show commands.

The V2.0 breakout manufacturer is unconfirmed. The register interface follows the LIS2DH/LIS2DH12 family; verify the module's pin labels before connecting it. No external sensor library is required.

## Motor-only program

`src/motor_only.cpp` runs the same motor controls without initializing I²C or reading the IMU. It uses ENA GPIO25, IN1 GPIO26 and IN2 GPIO27 for the same single motor on channel A. Serial commands, the 10-second command timeout and reversal pause are unchanged.

Select **motor-only** in PlatformIO's Project Tasks to build or upload it, or run:

```sh
pio run -e motor-only
pio run -e motor-only -t upload
pio device monitor -e motor-only
```

At 115200 baud, send `m 150`, `m -150`, or `s` followed by Enter. The motor starts stopped. No accelerometer is required. The motion dashboard has no acceleration data in this mode.

The original program remains in `src/main.cpp`. Use `pio run -e nodemcu-32s -t upload` to restore motor plus IMU operation. Each environment compiles only its own source file, avoiding duplicate `setup()` and `loop()` definitions. The default environment remains `nodemcu-32s`.

## UART motor commands

The motor-only program also accepts commands over UART2 at **115200 baud, 8 data bits, no parity, 1 stop bit**, without flow control. Connect a 3.3V UART controller or USB-to-TTL serial adapter:

- Controller TX → ESP32 GPIO16 RX.
- Controller RX → ESP32 GPIO17 TX.
- Controller GND → ESP32 GND, shared with L298N GND and motor supply negative.

Use 3.3V signal levels, not 5V TTL or RS-232 voltages. With the ESP32 powered through USB, leave the adapter's power pin disconnected. Motor pins remain ENA GPIO25, IN1 GPIO26 and IN2 GPIO27. UART goes to the ESP32, not directly to the L298N.

Upload the `motor-only` environment again after this change. Send `help\n`, `m 150\n`, `m -150\n`, or `s\n`; `\n` means an actual newline byte. Replies return on the same serial connection that received the command. USB serial remains available with its own command buffer. Both inputs control the same motor; the latest valid motor command wins and refreshes the shared 10-second timeout. Only one controller should send motor commands at a time. Send `s`, wait at least 0.5 seconds, then send the opposite direction to reverse.

The external UART uses a separate adapter port on your computer. Open that adapter at 115200 baud for UART2, or the ESP32's onboard USB serial port for the original USB commands. Each port can be opened by only one monitor at a time.

## Live motion dashboard

Run `python3 -m http.server 8765 --bind 127.0.0.1 --directory tools` from this project, then open http://127.0.0.1:8765/motion.html in desktop Chrome or Edge. Close the PlatformIO serial monitor first so the browser can own the port. Click **Connect ESP32** and select the USB serial device. The dashboard uses the existing firmware output, so no firmware change or upload is needed.

The viewer shows a 20-second XYZ acceleration plot, vector magnitude, and a gravity-direction indicator. It reads serial data only and sends no motor commands. Tilt estimates are useful when the sensor is nearly stationary; acceleration alone cannot track position or yaw. A disconnected or stalled feed is marked explicitly. Click Disconnect before reopening the PlatformIO serial monitor.

## References

- [ST LIS2DH12 datasheet](https://www.st.com/resource/en/datasheet/lis2dh12.pdf)
- [DFRobot LIS2DH module documentation](https://wiki.dfrobot.com/sen0224)
- [ST L298 datasheet](https://www.st.com/resource/en/datasheet/l298.pdf)

Compilation verifies the firmware target. Motor operation, sensor readings and wiring require testing on the actual hardware.
