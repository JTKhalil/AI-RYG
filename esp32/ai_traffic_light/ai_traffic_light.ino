/*
 * Cursor AI 状态信号灯 - ESP32-C3 固件
 * 分支：feature/yfrobot-two-pin-module
 *
 * 适配 YFROBOT 两线编码红绿灯模块，黄灯呼吸沿用 main 分支原方案（余弦 + gamma + LEDC PWM）：
 *   PIN1=0 PIN2=0  全灭
 *   PIN1=0 PIN2=1  红灯
 *   PIN1=1 PIN2=0  黄灯  <- PIN1 做 PWM 呼吸
 *   PIN1=1 PIN2=1  绿灯
 *
 * 串口命令：Y=黄(思考·PWM呼吸)  C=黄/红交替 0.2 亮度(等待确认)  G=绿(完成)  R=红(报错·闪烁)  O=熄灭
 *
 * 接线（模块 4P：PIN2 / PIN1 / VCC / GND）：
 *   模块 GND -> ESP32 GND
 *   模块 VCC -> ESP32 3V3 或 5V
 *   模块 PIN1 -> GPIO 4
 *   模块 PIN2 -> GPIO 5
 */

#include <math.h>

#define PIN1       4
#define PIN2       5
#define PIN_YELLOW PIN1
#define PIN_RED    PIN2

#define SERIAL_BAUD  115200

#define BREATH_CYCLE_MS     2000UL
#define BREATH_MIN_BRIGHT       0.03f
#define MAX_YELLOW_BRIGHT       0.40f
#define MAX_GREEN_BRIGHT        0.20f
#define MAX_RED_BRIGHT          0.20f
#define MAX_CONFIRM_BRIGHT      0.20f
#define BREATH_PWM_FREQ     5000
#define BREATH_PWM_BITS     8
#define RED_BLINK_MS         500UL

#ifndef PI
#define PI 3.14159265358979323846
#endif

enum LightState {
  STATE_OFF,
  STATE_YELLOW,
  STATE_GREEN,
  STATE_CONFIRM,
  STATE_RED
};

LightState currentState = STATE_OFF;

unsigned long breathPhaseStartMs = 0;
unsigned long redBlinkLastToggleMs = 0;
bool redBlinkOn = true;
uint8_t lastBreathDuty = 0;
bool confirmShowRed = false;

bool pin1PwmActive = false;
bool pin2PwmActive = false;

uint8_t peakDutyFor(float maxBright) {
  return (uint8_t)(255.0f * maxBright + 0.5f);
}

void setPinLow(int pin) {
  pinMode(pin, OUTPUT);
  digitalWrite(pin, LOW);
}

void setPinHigh(int pin) {
  pinMode(pin, OUTPUT);
  digitalWrite(pin, HIGH);
}

uint8_t breathDutyFromBrightness(float brightness) {
  int maxDuty = (int)peakDutyFor(MAX_YELLOW_BRIGHT);
  float gamma = powf(brightness, 0.65f);
  int duty = (int)(gamma * (float)maxDuty + 0.5f);
  int minDuty = (int)(BREATH_MIN_BRIGHT * (float)maxDuty);
  if (duty < minDuty) {
    duty = minDuty;
  }
  if (duty > maxDuty) {
    duty = maxDuty;
  }
  return (uint8_t)duty;
}

void detachPwmPin(int pin, bool &active) {
  if (!active) {
    return;
  }
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcDetach(pin);
#else
  ledcDetachPin(pin);
#endif
  pinMode(pin, OUTPUT);
  active = false;
}

void ensurePwmPin(int pin, bool &active) {
  if (active) {
    return;
  }
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(pin, BREATH_PWM_FREQ, BREATH_PWM_BITS);
#else
  int channel = (pin == PIN1) ? 0 : 1;
  ledcSetup(channel, BREATH_PWM_FREQ, BREATH_PWM_BITS);
  ledcAttachPin(pin, channel);
#endif
  active = true;
}

void writePwmPin(int pin, bool &active, uint8_t duty) {
  ensurePwmPin(pin, active);
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWrite(pin, duty);
#else
  int channel = (pin == PIN1) ? 0 : 1;
  ledcWrite(channel, duty);
#endif
}

void stopAllPwm() {
  detachPwmPin(PIN1, pin1PwmActive);
  detachPwmPin(PIN2, pin2PwmActive);
}

void allColorsOff() {
  stopAllPwm();
  setPinLow(PIN1);
  setPinLow(PIN2);
}

void writeYellowPwm(uint8_t duty) {
  detachPwmPin(PIN2, pin2PwmActive);
  setPinLow(PIN2);
  writePwmPin(PIN_YELLOW, pin1PwmActive, duty);
}

void applyGreen() {
  stopAllPwm();
  setPinLow(PIN1);
  setPinLow(PIN2);
  uint8_t duty = peakDutyFor(MAX_GREEN_BRIGHT);
  writePwmPin(PIN1, pin1PwmActive, duty);
  writePwmPin(PIN2, pin2PwmActive, duty);
}

void applyRedPwm() {
  detachPwmPin(PIN1, pin1PwmActive);
  setPinLow(PIN1);
  writePwmPin(PIN_RED, pin2PwmActive, peakDutyFor(MAX_RED_BRIGHT));
}

void applyState(LightState state) {
  stopAllPwm();
  setPinLow(PIN1);
  setPinLow(PIN2);

  switch (state) {
    case STATE_RED:
      applyRedPwm();
      break;
    case STATE_GREEN:
      applyGreen();
      break;
    case STATE_YELLOW:
    case STATE_CONFIRM:
      break;
    case STATE_OFF:
    default:
      break;
  }
}

void applyConfirmYellow() {
  detachPwmPin(PIN2, pin2PwmActive);
  setPinLow(PIN2);
  writePwmPin(PIN_YELLOW, pin1PwmActive, peakDutyFor(MAX_CONFIRM_BRIGHT));
}

void applyConfirmRed() {
  detachPwmPin(PIN1, pin1PwmActive);
  setPinLow(PIN1);
  writePwmPin(PIN_RED, pin2PwmActive, peakDutyFor(MAX_CONFIRM_BRIGHT));
}

void applyConfirmPhase(bool showRed) {
  if (showRed) {
    applyConfirmRed();
  } else {
    applyConfirmYellow();
  }
}

void enterState(LightState state) {
  if (state == currentState) {
    return;
  }

  LightState previous = currentState;
  currentState = state;
  unsigned long now = millis();
  redBlinkLastToggleMs = now;
  redBlinkOn = true;
  confirmShowRed = false;

  if (state == STATE_CONFIRM) {
    breathPhaseStartMs = now;
    lastBreathDuty = 0;
    applyConfirmPhase(false);
    return;
  }

  if (state == STATE_YELLOW) {
    if (previous != STATE_YELLOW) {
      breathPhaseStartMs = now;
      lastBreathDuty = 0;
    }
    return;
  }

  breathPhaseStartMs = now;
  lastBreathDuty = 0;
  if (state == STATE_RED) {
    applyState(STATE_RED);
  } else {
    applyState(state);
  }
}

void updateYellowBreathing() {
  unsigned long nowMs = millis();
  unsigned long elapsed = (nowMs - breathPhaseStartMs) % BREATH_CYCLE_MS;
  float phase = (float)elapsed / (float)BREATH_CYCLE_MS;
  float wave = (1.0f - cosf(phase * 2.0f * PI)) * 0.5f;
  float brightness = BREATH_MIN_BRIGHT + (1.0f - BREATH_MIN_BRIGHT) * wave;
  uint8_t duty = breathDutyFromBrightness(brightness);
  if (duty != lastBreathDuty) {
    lastBreathDuty = duty;
    writeYellowPwm(duty);
  }
}

void updateRedBlink() {
  unsigned long now = millis();
  if (now - redBlinkLastToggleMs >= RED_BLINK_MS) {
    redBlinkLastToggleMs = now;
    redBlinkOn = !redBlinkOn;
    applyState(redBlinkOn ? STATE_RED : STATE_OFF);
  }
}

void updateConfirmBlink() {
  unsigned long now = millis();
  if (now - redBlinkLastToggleMs >= RED_BLINK_MS) {
    redBlinkLastToggleMs = now;
    confirmShowRed = !confirmShowRed;
    applyConfirmPhase(confirmShowRed);
  }
}

void updateAnimation() {
  switch (currentState) {
    case STATE_YELLOW:
      updateYellowBreathing();
      break;
    case STATE_CONFIRM:
      updateConfirmBlink();
      break;
    case STATE_RED:
      updateRedBlink();
      break;
    default:
      break;
  }
}

void handleCommand(char cmd) {
  switch (cmd) {
    case 'Y':
    case 'y':
      enterState(STATE_YELLOW);
      Serial.println(F("OK:YELLOW"));
      break;
    case 'G':
    case 'g':
      enterState(STATE_GREEN);
      Serial.println(F("OK:GREEN"));
      break;
    case 'C':
    case 'c':
      enterState(STATE_CONFIRM);
      Serial.println(F("OK:CONFIRM"));
      break;
    case 'R':
    case 'r':
      enterState(STATE_RED);
      Serial.println(F("OK:RED"));
      break;
    case 'O':
    case 'o':
      enterState(STATE_OFF);
      Serial.println(F("OK:OFF"));
      break;
    default:
      Serial.print(F("ERR:UNKNOWN:"));
      Serial.println(cmd);
      break;
  }
}

void setup() {
  pinMode(PIN1, OUTPUT);
  pinMode(PIN2, OUTPUT);
  allColorsOff();

  Serial.begin(SERIAL_BAUD);
#if ARDUINO_USB_CDC_ON_BOOT
  delay(500);
#else
  while (!Serial && millis() < 3000) {
    delay(10);
  }
#endif

  Serial.println(F("Cursor AI Traffic Light Ready (ESP32-C3)"));
  Serial.println(F("Module: YFROBOT 2-pin (PIN1/PIN2) | Commands: Y C G R O"));
}

void loop() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() > 0) {
      handleCommand(line.charAt(0));
    }
  }
  updateAnimation();
}
