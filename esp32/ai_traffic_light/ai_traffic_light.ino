/*
 * Cursor AI 状态信号灯 - ESP32-C3 固件
 *
 * 串口命令：Y=黄(思考·PWM呼吸)  C=黄常亮+红闪(等待确认)  G=绿(完成·常亮)  R=红(报错·闪烁)  O=熄灭
 *
 * 黄灯呼吸/确认常亮最高 40%；绿·红灯最高 30%
 *
 * 接线（红 / 黄 / 绿 各一根 + GND）：
 *   模块 GND -> ESP32 GND
 *   模块 R   -> GPIO 4
 *   模块 Y   -> GPIO 5
 *   模块 G   -> GPIO 6
 *
 * 若是共阳模块（COM 接 VCC），将 LED_ACTIVE_LOW 改为 true
 */

#include <math.h>

#define PIN_RED    4
#define PIN_YELLOW 5
#define PIN_GREEN  6

#define LED_ACTIVE_LOW false
#define SERIAL_BAUD  115200

#define BREATH_CYCLE_MS     2000UL
#define BREATH_MIN_BRIGHT       0.03f
#define MAX_YELLOW_BRIGHT       0.40f
#define MAX_GREEN_BRIGHT        0.30f
#define MAX_RED_BRIGHT          0.30f
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

bool redPwmActive = false;
bool yellowPwmActive = false;
bool greenPwmActive = false;

uint8_t peakDutyFor(float maxBright) {
  return (uint8_t)(255.0f * maxBright + 0.5f);
}

void setPin(int pin, bool on) {
  if (LED_ACTIVE_LOW) {
    digitalWrite(pin, on ? LOW : HIGH);
  } else {
    digitalWrite(pin, on ? HIGH : LOW);
  }
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
  int channel = 0;
  if (pin == PIN_RED) {
    channel = 0;
  } else if (pin == PIN_YELLOW) {
    channel = 1;
  } else if (pin == PIN_GREEN) {
    channel = 2;
  }
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
  int channel = 0;
  if (pin == PIN_RED) {
    channel = 0;
  } else if (pin == PIN_YELLOW) {
    channel = 1;
  } else if (pin == PIN_GREEN) {
    channel = 2;
  }
  ledcWrite(channel, duty);
#endif
}

void stopAllPwm() {
  detachPwmPin(PIN_RED, redPwmActive);
  detachPwmPin(PIN_YELLOW, yellowPwmActive);
  detachPwmPin(PIN_GREEN, greenPwmActive);
}

void allColorsOff() {
  setPin(PIN_RED, false);
  setPin(PIN_YELLOW, false);
  setPin(PIN_GREEN, false);
}

void applyState(LightState state) {
  stopAllPwm();
  allColorsOff();

  switch (state) {
    case STATE_RED:
      writePwmPin(PIN_RED, redPwmActive, peakDutyFor(MAX_RED_BRIGHT));
      break;
    case STATE_GREEN:
      writePwmPin(PIN_GREEN, greenPwmActive, peakDutyFor(MAX_GREEN_BRIGHT));
      break;
    case STATE_YELLOW:
    case STATE_CONFIRM:
      break;
    case STATE_OFF:
    default:
      break;
  }
}

void writeYellowPwm(uint8_t duty) {
  if (redPwmActive) {
    detachPwmPin(PIN_RED, redPwmActive);
  }
  if (greenPwmActive) {
    detachPwmPin(PIN_GREEN, greenPwmActive);
  }
  setPin(PIN_RED, false);
  setPin(PIN_GREEN, false);
  writePwmPin(PIN_YELLOW, yellowPwmActive, duty);
}

void applyConfirmYellowSolid() {
  if (greenPwmActive) {
    detachPwmPin(PIN_GREEN, greenPwmActive);
  }
  setPin(PIN_GREEN, false);
  writePwmPin(PIN_YELLOW, yellowPwmActive, peakDutyFor(MAX_YELLOW_BRIGHT));
}

void applyConfirmRedPhase(bool redOn) {
  applyConfirmYellowSolid();
  if (redOn) {
    writePwmPin(PIN_RED, redPwmActive, peakDutyFor(MAX_RED_BRIGHT));
  } else if (redPwmActive) {
    detachPwmPin(PIN_RED, redPwmActive);
    setPin(PIN_RED, false);
  } else {
    setPin(PIN_RED, false);
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

  if (state == STATE_CONFIRM) {
    breathPhaseStartMs = now;
    lastBreathDuty = 0;
    redBlinkLastToggleMs = now;
    redBlinkOn = false;
    applyConfirmRedPhase(false);
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
    redBlinkOn = !redBlinkOn;
    applyConfirmRedPhase(redBlinkOn);
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
  pinMode(PIN_RED, OUTPUT);
  pinMode(PIN_YELLOW, OUTPUT);
  pinMode(PIN_GREEN, OUTPUT);

  applyState(STATE_OFF);

  Serial.begin(SERIAL_BAUD);
#if ARDUINO_USB_CDC_ON_BOOT
  delay(500);
#else
  while (!Serial && millis() < 3000) {
    delay(10);
  }
#endif

  Serial.println(F("Cursor AI Traffic Light Ready (ESP32-C3)"));
  Serial.println(F("Module: R/Y/G + GND | Commands: Y C G R O"));
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
