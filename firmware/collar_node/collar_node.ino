#include <Wire.h>

// ===== Ports: change to match where things are plugged in =====
#define DOG_ID     "DOG1"
#define LOUD_PIN   A0      // Loudness sensor on A0
#define BTN_PIN    2       // Button module on D2
#define LED_PIN    3       // LED on the button module (optional)
#define MMA        0x4C    // Accelerometer (I2C)
#define GPS        0x10    // GPS (I2C)

// ===== Thresholds =====
#define MOVE_TH        6      // Activity above this = dog is moving
#define STILL_MS       2000   // Still this long after moving = dog stopped
#define TILT_COS       0.87   // ~30 degree tilt = dog sat down
#define TILT_COOLDOWN  3000
#define BARK_DELTA     200    // Sound this far above baseline = bark
#define BARK_COOLDOWN  2000

unsigned long seq = 0;

// Accelerometer state
float bx, by, bz, act = 0;
int px, py, pz;
unsigned long lastMove = 0, lastTilt = 0;
bool wasMoving = false, tilted = false;

// Sound state
int loudBase = 0;
unsigned long lastBark = 0;

// Button state
int btnIdle;
bool btnDown = false;
unsigned long btnChange = 0;

// GPS state
char line[90];
byte len = 0;
char prev = 0;
float lat = 0, lon = 0;
bool fix = false;

unsigned long lastHB = 0, lastAcc = 0, ledOff = 0;

// ---------- Accelerometer ----------
void writeReg(byte r, byte v) {
  Wire.beginTransmission(MMA); Wire.write(r); Wire.write(v); Wire.endTransmission();
}

int8_t readAxis(byte r) {
  int8_t v = 0;
  for (byte i = 0; i < 5; i++) {
    Wire.beginTransmission(MMA); Wire.write(r); Wire.endTransmission(false);
    Wire.requestFrom(MMA, 1);
    v = Wire.read();
    if (!(v & 0x40)) break;   // bit 6 set = value updating, read again
  }
  v &= 0x3F;
  if (v & 0x20) v -= 64;      // 6-bit signed, about 21 counts = 1g
  return v;
}

// ---------- GPS ----------
float nmeaToDeg(const char *s, char hemi) {
  float v = atof(s);
  int d = (int)(v / 100);
  float deg = d + (v - d * 100) / 60.0;
  if (hemi == 'S' || hemi == 'W') deg = -deg;
  return deg;
}

void parseRMC() {
  char *f[8];
  byte n = 0;
  f[n++] = line;
  for (char *p = line; *p && n < 8; p++) {
    if (*p == ',') { *p = 0; f[n++] = p + 1; }
  }
  if (n < 7) return;
  fix = (f[2][0] == 'A');     // A = valid fix, V = no fix
  if (fix && f[3][0] && f[5][0]) {
    lat = nmeaToDeg(f[3], f[4][0]);
    lon = nmeaToDeg(f[5], f[6][0]);
  }
}

void pollGPS() {
  Wire.requestFrom(GPS, 32);
  while (Wire.available()) {
    char c = Wire.read();
    if (c == '\n' && prev != '\r') { prev = c; continue; }  // skip filler bytes
    prev = c;
    if (c == '$') len = 0;
    if (c == '\r' || c == '\n') {
      line[len] = 0;
      if (len > 6 && strncmp(line + 3, "RMC", 3) == 0) parseRMC();
      len = 0;
      continue;
    }
    if (len < sizeof(line) - 1) line[len++] = c;
  }
}

// ---------- Output ----------
void printPos() {
  Serial.print(',');
  if (fix) { Serial.print(lat, 6); Serial.print(','); Serial.print(lon, 6); }
  else Serial.print(',');
  Serial.print(',');
  Serial.println(fix ? 1 : 0);
}

// Heartbeat: HB,dog_id,seq,t_ms,activity,state,lat,lon,fix
void sendHB(unsigned long now) {
  Serial.print("HB,"); Serial.print(DOG_ID); Serial.print(',');
  Serial.print(seq++); Serial.print(','); Serial.print(now); Serial.print(',');
  Serial.print(act, 1); Serial.print(',');
  Serial.print((now - lastMove < STILL_MS) ? "MOVING" : "STILL");
  printPos();
}

// Alert: AL,dog_id,seq,t_ms,type,lat,lon,fix
void sendAlert(const char *type) {
  unsigned long now = millis();
  Serial.print("AL,"); Serial.print(DOG_ID); Serial.print(',');
  Serial.print(seq++); Serial.print(','); Serial.print(now); Serial.print(',');
  Serial.print(type);
  printPos();
  digitalWrite(LED_PIN, HIGH);
  ledOff = now + 1000;
}

// ---------- Main ----------
void setup() {
  Serial.begin(9600);
  Wire.begin();
  pinMode(BTN_PIN, INPUT);
  pinMode(LED_PIN, OUTPUT);

  writeReg(0x07, 0x00);   // standby
  writeReg(0x08, 0x00);   // 120 Hz sample rate
  writeReg(0x07, 0x01);   // active
  delay(100);

  // Calibrate: standing posture and room noise level
  long ls = 0;
  for (int i = 0; i < 20; i++) {
    bx += readAxis(0); by += readAxis(1); bz += readAxis(2);
    ls += analogRead(LOUD_PIN);
    delay(20);
  }
  bx /= 20; by /= 20; bz /= 20;
  loudBase = ls / 20;
  px = bx; py = by; pz = bz;
  btnIdle = digitalRead(BTN_PIN);   // state at boot = not pressed
  Serial.println("READY");
}

void loop() {
  unsigned long now = millis();
  pollGPS();

  // Accelerometer: stopped / sat down
  if (now - lastAcc >= 50) {
    lastAcc = now;
    int x = readAxis(0), y = readAxis(1), z = readAxis(2);
    int motion = abs(x - px) + abs(y - py) + abs(z - pz);
    px = x; py = y; pz = z;
    act = 0.8 * act + 0.2 * motion;

    if (act > MOVE_TH) { lastMove = now; wasMoving = true; }
    if (wasMoving && now - lastMove > STILL_MS) { sendAlert("STILL"); wasMoving = false; }

    float dot = x * bx + y * by + z * bz;
    float n = sqrt((float)x * x + y * y + z * z) * sqrt(bx * bx + by * by + bz * bz);
    float c = (n > 0) ? dot / n : 1;
    if (!tilted && c < TILT_COS && now - lastTilt > TILT_COOLDOWN) {
      sendAlert("TILT"); tilted = true; lastTilt = now;
    }
    if (tilted && c > 0.95) tilted = false;
  }

  // Sound: bark
  int loud = analogRead(LOUD_PIN);
  if (loud > loudBase + BARK_DELTA && now - lastBark > BARK_COOLDOWN) {
    lastBark = now;
    sendAlert("BARK");
  }

  // Button: handler manual report
  bool pressed = digitalRead(BTN_PIN) != btnIdle;
  if (pressed != btnDown && now - btnChange > 50) {
    btnDown = pressed; btnChange = now;
    if (pressed) sendAlert("BUTTON");
  }

  // Heartbeat once per second
  if (now - lastHB >= 1000) { lastHB = now; sendHB(now); }

  if (ledOff && now > ledOff) { digitalWrite(LED_PIN, LOW); ledOff = 0; }
}