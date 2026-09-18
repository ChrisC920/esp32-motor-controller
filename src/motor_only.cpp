#include <Arduino.h>
#include <ctype.h>
#include <stdlib.h>
#include <string.h>

// GPIO numbers for a classic ESP32 development board.
constexpr uint8_t MOTOR_ENA = 25, MOTOR_IN1 = 26, MOTOR_IN2 = 27;
constexpr uint8_t PWM_CHANNEL = 0;
constexpr uint8_t UART_RX = 16, UART_TX = 17;
constexpr uint32_t UART_BAUD = 115200;
HardwareSerial motorUart(2);

struct CommandBuffer {
  char line[48] = {};
  size_t length = 0;
  bool overflow = false;
};
CommandBuffer usbBuffer, uartBuffer;
constexpr uint32_t REVERSE_PAUSE_MS = 500;
int motorSpeed = 0, lastDirection = 0;
uint32_t stoppedAt = 0;

uint8_t percentToPwm(int percent) {
  return static_cast<uint8_t>((abs(percent) * 255 + 50) / 100);
}

void stopMotor() {
  ledcWrite(PWM_CHANNEL, 0);
  digitalWrite(MOTOR_IN1, LOW);
  digitalWrite(MOTOR_IN2, LOW);
  if (motorSpeed != 0) stoppedAt = millis();
  motorSpeed = 0;
}

void setMotor(int speed, HardwareSerial &port) {
  if (speed == 0) {
    stopMotor();
    return;
  }
  const int direction = speed > 0 ? 1 : -1;
  if (lastDirection != 0 && direction != lastDirection) {
    stopMotor();
    // Require another command after coasting, without blocking serial.
    if (millis() - stoppedAt < REVERSE_PAUSE_MS) {
      port.println("Stopped. Wait 0.5 s, then resend to reverse.");
      return;
    }
  }
  digitalWrite(MOTOR_IN1, direction > 0 ? HIGH : LOW);
  digitalWrite(MOTOR_IN2, direction < 0 ? HIGH : LOW);
  ledcWrite(PWM_CHANNEL, percentToPwm(speed));
  motorSpeed = speed;
  lastDirection = direction;
}

void printHelp(HardwareSerial &port) {
  port.println("Commands, followed by Enter:");
  port.println("  m 60    forward at 60%");
  port.println("  m -60   reverse at 60%");
  port.println("  s       stop/coast");
  port.println("  help    show commands");
  port.println("Motor keeps running until s, m 0, reset, or power-off.");
}

void handleCommand(char *line, HardwareSerial &port) {
  while (isspace(static_cast<unsigned char>(*line))) ++line;
  size_t length = strlen(line);
  while (length && isspace(static_cast<unsigned char>(line[length - 1])))
    line[--length] = '\0';
  if (!length) return;
  if (strcmp(line, "s") == 0) {
    stopMotor();
    port.println("Motor stopped.");
  } else if (strcmp(line, "help") == 0) {
    printHelp(port);

  } else if (line[0] == 'm' && isspace(static_cast<unsigned char>(line[1]))) {
    char *number = line + 1;
    while (isspace(static_cast<unsigned char>(*number))) ++number;
    char *end = nullptr;
    const long speed = strtol(number, &end, 10);
    if (end == number || *end != '\0' || speed < -100 || speed > 100) {
      port.println("Use m followed by an integer from -100 to 100 percent.");
      return;
    }
    setMotor(static_cast<int>(speed), port);
    port.printf("Motor: %d%%\n", motorSpeed);
  } else {
    port.println("Unknown command. Send help.");
  }
}

void pollSerial(HardwareSerial &port, CommandBuffer &buffer) {
  auto &line = buffer.line;
  auto &length = buffer.length;
  auto &overflow = buffer.overflow;
  // Bound each pass so continuous input cannot starve other work.
  for (int budget = 64; budget > 0 && port.available(); --budget) {
    const char c = port.read();
    if (c == '\n' || c == '\r') {
      if (overflow) port.println("Command too long; discarded.");
      else {
        line[length] = '\0';
        handleCommand(line, port);
      }
      length = 0;
      overflow = false;
    } else if (!overflow) {
      if (length < sizeof(line) - 1) line[length++] = c;
      else overflow = true;
    }
  }
}

void setup() {
  pinMode(MOTOR_ENA, OUTPUT);
  digitalWrite(MOTOR_ENA, LOW);
  pinMode(MOTOR_IN1, OUTPUT);
  pinMode(MOTOR_IN2, OUTPUT);
  digitalWrite(MOTOR_IN1, LOW);
  digitalWrite(MOTOR_IN2, LOW);
  ledcSetup(PWM_CHANNEL, 1000, 8);
  ledcAttachPin(MOTOR_ENA, PWM_CHANNEL);
  stopMotor();
  Serial.begin(UART_BAUD);
  motorUart.begin(UART_BAUD, SERIAL_8N1, UART_RX, UART_TX);
  Serial.println("Motor-only program ready. Motor starts stopped.");
  printHelp(Serial);
  motorUart.println("UART motor control ready. Motor starts stopped.");
  printHelp(motorUart);
}

void loop() {
  pollSerial(Serial, usbBuffer);
  pollSerial(motorUart, uartBuffer);
  delay(1);
}
