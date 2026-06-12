/*
 * Cursor AI 状态信号灯 - ESP32-C3 固件
 *
 * 串口命令：Y=黄(思考·PWM呼吸)  C=黄闪(等待确认·30%)  G=绿(完成·常亮)  R=红(报错·闪烁)  O=熄灭
 *
 * 黄灯呼吸最高 40%；确认闪烁 / 绿·红灯最高 30%
 *
 * 四线模块（PIN1 / PIN2 / VCC / GND）：
 *   VCC  -> ESP32 5V（或 3V）
 *   GND  -> ESP32 GND
 *   PIN1 -> GPIO 4
 *   PIN2 -> GPIO 5
 *
 * 本模块实测编码：
 *   PIN1=0 PIN2=0  全灭
 *   PIN1=0 PIN2=1  红灯
 *   PIN1=1 PIN2=0  黄灯
 *   PIN1=1 PIN2=1  绿灯
 */

#include <math.h>

#define TWO_PIN_MODULE true

#define PIN1       4
#define PIN2       5

#define PIN_RED    4
#define PIN_YELLOW 5
#define PIN_GREEN  6

#define LED_ACTIVE_LOW false
#define SERIAL_BAUD  115200

#define BREATH_CYCLE_MS     2000UL
#define BREATH_MIN_BRIGHT       0.03f
#define MAX_YELLOW_BRIGHT       0.40f
#define MAX_CONFIRM_BRIGHT      0.30f
#define MAX_GREEN_BRIGHT        0.30f
#define MAX_RED_BRIGHT          0.30f
#define BREATH_PWM_FREQ     5000
#define BREATH_PWM_BITS     8
#define LEDC_CH_PIN1        0
#define LEDC_CH_PIN2        1
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
unsigned long confirmBlinkLastToggleMs = 0;
bool redBlinkOn = true;
bool confirmBlinkOn = true;
bool pin1PwmActive = false;
bool pin2PwmActive = false;
uint8_t lastBreathDuty = 0;

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

#if TWO_PIN_MODULE

void detachPin1Pwm() {
  if (!pin1PwmActive) {
    return;
  }
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcDetach(PIN1);
#else
  ledcDetachPin(PIN1);
#endif
  pinMode(PIN1, OUTPUT);
  pin1PwmActive = false;
}

void detachPin2Pwm() {
  if (!pin2PwmActive) {
    return;
  }
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcDetach(PIN2);
#else
  ledcDetachPin(PIN2);
#endif
  pinMode(PIN2, OUTPUT);
  pin2PwmActive = false;
}

void stopAllPwm() {
  detachPin1Pwm();
  detachPin2Pwm();
}

void ensurePin1Pwm() {
  if (pin1PwmActive) {
    return;
  }
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(PIN1, BREATH_PWM_FREQ, BREATH_PWM_BITS);
#else
  ledcSetup(LEDC_CH_PIN1, BREATH_PWM_FREQ, BREATH_PWM_BITS);
  ledcAttachPin(PIN1, LEDC_CH_PIN1);
#endif
  pin1PwmActive = true;
}

void ensurePin2Pwm() {
  if (pin2PwmActive) {
    return;
  }
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(PIN2, BREATH_PWM_FREQ, BREATH_PWM_BITS);
#else
  ledcSetup(LEDC_CH_PIN2, BREATH_PWM_FREQ, BREATH_PWM_BITS);
  ledcAttachPin(PIN2, LEDC_CH_PIN2);
#endif
  pin2PwmActive = true;
}

void writePin1Duty(uint8_t duty) {
  ensurePin1Pwm();
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWrite(PIN1, duty);
#else
  ledcWrite(LEDC_CH_PIN1, duty);
#endif
}

void writePin2Duty(uint8_t duty) {
  ensurePin2Pwm();
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWrite(PIN2, duty);
#else
  ledcWrite(LEDC_CH_PIN2, duty);
#endif
}

void applyState(LightState state) {
  stopAllPwm();
  switch (state) {
    case STATE_RED:
      setPin(PIN1, false);
      writePin2Duty(peakDutyFor(MAX_RED_BRIGHT));
      break;
    case STATE_YELLOW:
      setPin(PIN2, false);
      writePin1Duty(peakDutyFor(MAX_YELLOW_BRIGHT));
      break;
    case STATE_GREEN:
      writePin1Duty(peakDutyFor(MAX_GREEN_BRIGHT));
      writePin2Duty(peakDutyFor(MAX_GREEN_BRIGHT));
      break;
    case STATE_OFF:
    default:
      setPin(PIN1, false);
      setPin(PIN2, false);
      break;
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

void applyConfirmYellow() {
  stopAllPwm();
  setPin(PIN2, false);
  writePin1Duty(peakDutyFor(MAX_CONFIRM_BRIGHT));
}

void writeYellowPwm(uint8_t duty) {
  if (pin2PwmActive) {
    detachPin2Pwm();
  }
  setPin(PIN2, false);
  writePin1Duty(duty);
}

#else

void applyState(LightState state) {
  setPin(PIN_RED, false);
  setPin(PIN_YELLOW, false);
  setPin(PIN_GREEN, false);

  switch (state) {
    case STATE_YELLOW:
      setPin(PIN_YELLOW, true);
      break;
    case STATE_GREEN:
      setPin(PIN_GREEN, true);
      break;
    case STATE_RED:
      setPin(PIN_RED, true);
      break;
    case STATE_OFF:
    default:
      break;
  }
}

#endif

void enterState(LightState state) {
  if (state == currentState) {
    return;
  }

  currentState = state;
  unsigned long now = millis();
  breathPhaseStartMs = now;
  redBlinkLastToggleMs = now;
  confirmBlinkLastToggleMs = now;
  redBlinkOn = true;
  confirmBlinkOn = true;
  lastBreathDuty = 0;

  if (state == STATE_YELLOW) {
    // 亮度由 updateYellowBreathing() 通过 PWM 连续调节
  } else if (state == STATE_RED) {
    applyState(STATE_RED);
  } else if (state == STATE_CONFIRM) {
#if TWO_PIN_MODULE
    applyConfirmYellow();
#else
    setPin(PIN_YELLOW, true);
#endif
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
  if (now - confirmBlinkLastToggleMs >= RED_BLINK_MS) {
    confirmBlinkLastToggleMs = now;
    confirmBlinkOn = !confirmBlinkOn;
#if TWO_PIN_MODULE
    if (confirmBlinkOn) {
      applyConfirmYellow();
    } else {
      applyState(STATE_OFF);
    }
#else
    setPin(PIN_RED, false);
    setPin(PIN_GREEN, false);
    setPin(PIN_YELLOW, confirmBlinkOn);
#endif
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
#if TWO_PIN_MODULE
  pinMode(PIN1, OUTPUT);
  pinMode(PIN2, OUTPUT);
#else
  pinMode(PIN_RED, OUTPUT);
  pinMode(PIN_YELLOW, OUTPUT);
  pinMode(PIN_GREEN, OUTPUT);
#endif

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
  Serial.println(F("Commands: Y=breathing C=confirm-blink G=steady R=blink O=off"));
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
