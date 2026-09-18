#include <Arduino.h>
#include <Wire.h>
#include <ctype.h>
#include <stdlib.h>
#include <string.h>

// GPIO numbers for a classic ESP32 development board.
constexpr uint8_t MOTOR_ENA = 25, MOTOR_IN1 = 26, MOTOR_IN2 = 27;
constexpr uint8_t I2C_SDA = 22, I2C_SCL = 23, PWM_CHANNEL = 0;
constexpr uint32_t REVERSE_PAUSE_MS = 500;
int motorSpeed = 0, lastDirection = 0;
uint32_t stoppedAt = 0;
uint8_t sensorAddress = 0;
bool sensorReady = false;

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

void setMotor(int speed) {
  if (speed == 0) {
    stopMotor();
    return;
  }
  const int direction = speed > 0 ? 1 : -1;
  if (lastDirection != 0 && direction != lastDirection) {
    stopMotor();
    // Require another command after coasting, without blocking serial.
    if (millis() - stoppedAt < REVERSE_PAUSE_MS) {
      Serial.println("Stopped. Wait 0.5 s, then resend to reverse.");
      return;
    }
  }
  digitalWrite(MOTOR_IN1, direction > 0 ? HIGH : LOW);
  digitalWrite(MOTOR_IN2, direction < 0 ? HIGH : LOW);
  ledcWrite(PWM_CHANNEL, percentToPwm(speed));
  motorSpeed = speed;
  lastDirection = direction;
}

bool readRegisters(uint8_t reg, uint8_t *data, uint8_t count) {
  Wire.beginTransmission(sensorAddress);
  Wire.write(count > 1 ? reg | 0x80 : reg); // Auto-increment for XYZ burst.
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(sensorAddress, count) != count) return false;
  for (uint8_t i = 0; i < count; ++i) data[i] = Wire.read();
  return true;
}

bool writeRegister(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(sensorAddress);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

bool beginAccelerometer() {
  for (uint8_t address = 0x18; address <= 0x19; ++address) {
    sensorAddress = address;
    uint8_t identity = 0;
    if (!readRegisters(0x0F, &identity, 1) || identity != 0x33) continue;
    // Power down; bypass filters/FIFO; block data update; +/-2g;
    // little endian; high resolution; 100 Hz; XYZ enabled.
    if (!writeRegister(0x20, 0x07) || !writeRegister(0x21, 0x00) ||
        !writeRegister(0x24, 0x00) || !writeRegister(0x23, 0x88) ||
        !writeRegister(0x20, 0x57)) continue;
    delay(100); // Settle the high-resolution filter with the motor stopped.
    Serial.printf("LIS2DH detected at 0x%02X. Acceleration in g.\n", address);
    return true;
  }
  Serial.println("LIS2DH unavailable. Check power and SDA/SCL; send retry.");
  return false;
}

void printHelp() {
  Serial.println("Commands, followed by Enter:");
  Serial.println("  m 60    forward at 60%");
  Serial.println("  m -60   reverse at 60%");
  Serial.println("  s       stop/coast");
  Serial.println("  retry   stop motor and reconnect accelerometer");
  Serial.println("  help    show commands");
  Serial.println("Motor keeps running until s, m 0, reset, or power-off.");
}

void handleCommand(char *line) {
  while (isspace(static_cast<unsigned char>(*line))) ++line;
  size_t length = strlen(line);
  while (length && isspace(static_cast<unsigned char>(line[length - 1])))
    line[--length] = '\0';
  if (!length) return;
  if (strcmp(line, "s") == 0) {
    stopMotor();
    Serial.println("Motor stopped.");
  } else if (strcmp(line, "help") == 0) {
    printHelp();
  } else if (strcmp(line, "retry") == 0) {
    stopMotor();
    sensorReady = beginAccelerometer();
  } else if (line[0] == 'm' && isspace(static_cast<unsigned char>(line[1]))) {
    char *number = line + 1;
    while (isspace(static_cast<unsigned char>(*number))) ++number;
    char *end = nullptr;
    const long speed = strtol(number, &end, 10);
    if (end == number || *end != '\0' || speed < -100 || speed > 100) {
      Serial.println("Use m followed by an integer from -100 to 100 percent.");
      return;
    }
    setMotor(static_cast<int>(speed));
    Serial.printf("Motor: %d%%\n", motorSpeed);
  } else {
    Serial.println("Unknown command. Send help.");
  }
}

void pollSerial() {
  static char line[48];
  static size_t length = 0;
  static bool overflow = false;
  // Bound each pass so continuous input cannot starve other work.
  for (int budget = 64; budget > 0 && Serial.available(); --budget) {
    const char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (overflow) Serial.println("Command too long; discarded.");
      else {
        line[length] = '\0';
        handleCommand(line);
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
  Serial.begin(115200);
  Wire.begin(I2C_SDA, I2C_SCL, 100000);
  Wire.setTimeOut(25);
  sensorReady = beginAccelerometer();
  printHelp();
}

void loop() {
  pollSerial();
  static uint32_t lastSample = 0;
  if (sensorReady && millis() - lastSample >= 200) {
    lastSample = millis();
    uint8_t status = 0, raw[6];
    if (!readRegisters(0x27, &status, 1)) sensorReady = false;
    else if (status & 0x08) { // New data on all three axes.
      if (!readRegisters(0x28, raw, sizeof(raw))) sensorReady = false;
      else {
        float g[3];
        for (uint8_t axis = 0; axis < 3; ++axis) {
          const int16_t sample = static_cast<int16_t>(
              static_cast<uint16_t>(raw[axis * 2]) |
              (static_cast<uint16_t>(raw[axis * 2 + 1]) << 8));
          // Left-aligned 12-bit value, 1 mg per count at +/-2g.
          g[axis] = (sample / 16) * 0.001f;
        }
        Serial.printf("ax=%.3f g  ay=%.3f g  az=%.3f g  motor=%d%%\n",
                      g[0], g[1], g[2], motorSpeed);
      }
    }
    if (!sensorReady) Serial.println("Accelerometer read failed; send retry.");
  }
  delay(1);
}
