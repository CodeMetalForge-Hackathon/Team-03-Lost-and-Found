#include <Wire.h>
#include <DHT.h>   // Install via Library Manager: "DHT sensor library" by Adafruit

// ===== Settings =====
#define DOG_ID     "DOG1"
#define TEST_MODE  0       // 1 = readable sensor printout for bench testing, 0 = normal CSV output

// ===== Ports (Base Shield v2.1) =====
#define LOUD_PIN   A0      // Loudness sensor
#define THERM_PIN  A1      // Temperature sensor (thermistor), optional
#define DHT_PIN    2       // Temp & Humidity sensor (DHT11)
#define US_PIN     4       // Ultrasonic Ranger
#define MMA        0x4C    // 3-Axis Accelerometer (I2C port)
#define GPS        0x10    // GPS (I2C), only used if USE_GPS = 1

// ===== Optional hardware: 1 = plugged in, 0 = not plugged in =====
#define USE_THERM  1       // Set to 0 if nothing is on A1 (a floating pin gives garbage)
#define USE_GPS    0       // Set to 1 if an I2C GPS is plugged in

// ===== Thresholds =====
#define MOVE_TH        6      // Activity above this = dog is moving
#define STILL_MS       2000   // Still this long after moving = dog stopped
#define TILT_COS       0.87   // ~30 degree tilt = dog sat down
#define TILT_COOLDOWN  3000
#define BARK_DELTA     300    // Sound this far above the (moving) baseline = loud sound
#define BARK_COOLDOWN  2000
#define HEAT_C         45.0   // Temperature above this = HEAT alert
#define THERM_K        3.47   // Thermistor calibration: makes A1 match the DHT11 at room temp (1.0 = Seeed default)
#define HEAT_COOLDOWN  10000

// ===== Timing =====
#define ACC_MS     50      // Accelerometer read interval
#define FAST_MS    200     // Ultrasonic + thermistor read interval
#define DHT_MS     2000    // DHT11 read interval (it can't go faster than ~1 s)
#define HB_MS      (TEST_MODE ? 5000 : 1000)   // Test printout every 5 s, normal heartbeat every 1 s

DHT dht(DHT_PIN, DHT11);

unsigned long seq = 0;

// Accelerometer state
float bx, by, bz, act = 0;
int px, py, pz;
unsigned long lastMove = 0, lastTilt = 0;
bool wasMoving = false, tilted = false;

// Sound state
float loudBase = 0;   // slowly follows the room's background noise
int loud = 0;
unsigned long lastBark = 0;

// Environment state
float tempC = NAN, hum = NAN, thermC = NAN;
long distCm = -1;
bool hot = false;

// Debug state (shown in TEST_MODE)
long distRaw = -1;      // ultrasonic echo time in microseconds
int thermRaw = 0;       // thermistor raw ADC value (0-1023)
bool accOk = true;      // accelerometer answered on I2C at startup
bool dhtOk = false;     // last DHT11 read succeeded
unsigned long lastHeat = 0;

// GPS state
char line[90];
byte len = 0;
char prev = 0;
float lat = 0, lon = 0;
bool fix = false;

unsigned long lastHB = 0, lastAcc = 0, lastFast = 0, lastDHT = 0, ledOff = 0;

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

// ---------- Ultrasonic Ranger (single signal pin) ----------
long readDistanceCm() {
  pinMode(US_PIN, OUTPUT);
  digitalWrite(US_PIN, LOW);  delayMicroseconds(2);
  digitalWrite(US_PIN, HIGH); delayMicroseconds(10);   // 10 us trigger works on all Grove ranger versions
  digitalWrite(US_PIN, LOW);
  pinMode(US_PIN, INPUT);
  unsigned long d = pulseIn(US_PIN, HIGH, 25000UL);  // ~4 m max, blocks at most 25 ms
  distRaw = d;
  if (d == 0) return -1;                             // no echo / out of range
  return d / 29 / 2;
}

// ---------- Thermistor (Grove Temperature Sensor) ----------
float readThermC() {
  const float B = 4275.0;
  int a = analogRead(THERM_PIN);
  thermRaw = a;
  if (a <= 0) return NAN;
  float ratio = THERM_K * (1023.0 / a - 1.0);   // thermistor resistance / R0
  return 1.0 / (log(ratio) / B + 1.0 / 298.15) - 273.15;
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
void printVal(float v, byte digits) {   // empty field if no reading
  if (!isnan(v)) Serial.print(v, digits);
}

void printPos() {
  Serial.print(',');
  if (fix) { Serial.print(lat, 6); Serial.print(','); Serial.print(lon, 6); }
  else Serial.print(',');
  Serial.print(',');
  Serial.print(fix ? 1 : 0);
}

// Heartbeat: HB,dog_id,seq,t_ms,activity,state,lat,lon,fix,temp_c,humidity,therm_c,dist_cm
// (New fields are at the end, so a parser that reads the first 9 fields still works.)
void sendHB(unsigned long now) {
  Serial.print("HB,"); Serial.print(DOG_ID); Serial.print(',');
  Serial.print(seq++); Serial.print(','); Serial.print(now); Serial.print(',');
  Serial.print(act, 1); Serial.print(',');
  Serial.print((now - lastMove < STILL_MS) ? "MOVING" : "STILL");
  printPos();
  Serial.print(','); printVal(tempC, 1);
  Serial.print(','); printVal(hum, 0);
  Serial.print(','); printVal(thermC, 1);
  Serial.print(','); if (distCm >= 0) Serial.print(distCm);
  Serial.println();
}

// Which sensor triggers each alert type (for test-mode printout)
const char *alertSource(const char *type) {
  if (!strcmp(type, "STILL") || !strcmp(type, "TILT")) return "ACCEL (I2C 0x4C)";
  if (!strcmp(type, "BARK")) return "LOUD (A0)";
  if (!strcmp(type, "HEAT")) return USE_THERM ? "THERM (A1)" : "DHT11 (D2)";
  return "?";
}

// Alert: AL,dog_id,seq,t_ms,type,lat,lon,fix
void sendAlert(const char *type) {
  unsigned long now = millis();
  digitalWrite(LED_BUILTIN, HIGH);   // onboard LED flashes on every alert
  ledOff = now + 1000;

  if (TEST_MODE) {
    Serial.print(">>> ALERT "); Serial.print(type);
    Serial.print("  from "); Serial.print(alertSource(type));
    Serial.print("  at t="); Serial.print(now); Serial.println(" ms");
    return;
  }

  Serial.print("AL,"); Serial.print(DOG_ID); Serial.print(',');
  Serial.print(seq++); Serial.print(','); Serial.print(now); Serial.print(',');
  Serial.print(type);
  printPos();
  Serial.println();
}

// Test mode: one labeled line per sensor, with its port, raw value, converted value and status
void status(const char *s) { Serial.print("  -> "); Serial.println(s); }

void printTest() {
  Serial.print("========== t="); Serial.print(millis()); Serial.println(" ms ==========");

  // Accelerometer
  Serial.print("[ACCEL  | I2C 0x4C] x="); Serial.print(px);
  Serial.print(" y="); Serial.print(py); Serial.print(" z="); Serial.print(pz);
  Serial.print("  (21 = 1g)  activity="); Serial.print(act, 1);
  Serial.print(" state="); Serial.print((millis() - lastMove < STILL_MS) ? "MOVING" : "STILL");
  status(accOk ? "OK" : "NOT FOUND - check I2C cable");

  // Loudness
  Serial.print("[LOUD   | A0      ] raw="); Serial.print(loud);
  Serial.print("  baseline="); Serial.print((int)loudBase);
  Serial.print("  alert above "); Serial.print((int)loudBase + BARK_DELTA);
  status((loud <= 1 || loud >= 1022) ? "CHECK - stuck at min/max" : "OK");

  // Ultrasonic
  Serial.print("[ULTRA  | D4      ] echo="); Serial.print(distRaw); Serial.print("us  dist=");
  if (distCm >= 0) { Serial.print(distCm); Serial.print("cm"); } else Serial.print("--");
  status(distCm >= 0 ? "OK" : "NO ECHO - check D4 or nothing in range");

  // DHT11
  Serial.print("[DHT11  | D2      ] temp="); printVal(tempC, 1);
  Serial.print("C ("); printVal(tempC * 1.8 + 32, 1); Serial.print("F)  humidity=");
  printVal(hum, 0); Serial.print('%');
  status(dhtOk ? "OK" : (isnan(tempC) ? "NO DATA - check D2 / library" : "LAST READ FAILED - showing old value"));

  // Thermistor
  Serial.print("[THERM  | A1      ] ");
  if (USE_THERM) {
    Serial.print("raw="); Serial.print(thermRaw); Serial.print("  temp="); printVal(thermC, 1);
    Serial.print("C ("); printVal(thermC * 1.8 + 32, 1); Serial.print("F)");
    status(isnan(thermC) ? "NO DATA - check A1" : "OK");
  } else {
    status("OFF (USE_THERM = 0)");
  }

  // GPS
  Serial.print("[GPS    | I2C 0x10] ");
  if (USE_GPS) {
    if (fix) { Serial.print(lat, 6); Serial.print(", "); Serial.print(lon, 6); }
    status(fix ? "FIX" : "NO FIX (normal indoors)");
  } else {
    status("OFF (USE_GPS = 0)");
  }
  Serial.println();
}

// ---------- Main ----------
void setup() {
  Serial.begin(9600);
  Wire.begin();
  dht.begin();
  pinMode(LED_BUILTIN, OUTPUT);

  // Check the accelerometer answers on I2C
  Wire.beginTransmission(MMA);
  accOk = (Wire.endTransmission() == 0);
  if (!accOk) Serial.println("WARN,accelerometer not found at 0x4C");

  writeReg(0x07, 0x00);   // standby
  writeReg(0x08, 0x00);   // 120 Hz sample rate
  writeReg(0x07, 0x01);   // active
  delay(100);

  // Calibrate: standing posture and room noise level (keep the dog still and quiet)
  long ls = 0;
  for (int i = 0; i < 20; i++) {
    bx += readAxis(0); by += readAxis(1); bz += readAxis(2);
    ls += analogRead(LOUD_PIN);
    delay(20);
  }
  bx /= 20; by /= 20; bz /= 20;
  loudBase = ls / 20;
  px = bx; py = by; pz = bz;
  Serial.println("READY");
}

void loop() {
  unsigned long now = millis();
  if (USE_GPS) pollGPS();

  // Accelerometer: stopped / sat down
  if (now - lastAcc >= ACC_MS) {
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

  // Sound: loud event
  loud = analogRead(LOUD_PIN);
  if (loud > loudBase + BARK_DELTA && now - lastBark > BARK_COOLDOWN) {
    lastBark = now;
    sendAlert("BARK");
  }

  // Ultrasonic + thermistor
  if (now - lastFast >= FAST_MS) {
    lastFast = now;
    distCm = readDistanceCm();
    if (USE_THERM) thermC = readThermC();
    // Let the sound baseline drift toward the current noise level (~4 s to adapt),
    // so a noisy room doesn't trigger BARK alerts nonstop
    loudBase = 0.95 * loudBase + 0.05 * loud;
  }

  // DHT11 (slow sensor)
  if (now - lastDHT >= DHT_MS) {
    lastDHT = now;
    float t = dht.readTemperature();
    float h = dht.readHumidity();
    dhtOk = !isnan(t) && !isnan(h);
    if (!isnan(t)) tempC = t;   // keep last good value if a read fails
    if (!isnan(h)) hum = h;
  }

  // Heat: uses the thermistor if present (wider range), otherwise the DHT11
  float heatSrc = USE_THERM ? thermC : tempC;
  if (!isnan(heatSrc)) {
    if (!hot && heatSrc > HEAT_C && now - lastHeat > HEAT_COOLDOWN) {
      sendAlert("HEAT"); hot = true; lastHeat = now;
    }
    if (hot && heatSrc < HEAT_C - 3) hot = false;
  }

  // Heartbeat
  if (now - lastHB >= HB_MS) {
    lastHB = now;
    if (TEST_MODE) printTest(); else sendHB(now);
  }

  if (ledOff && now > ledOff) { digitalWrite(LED_BUILTIN, LOW); ledOff = 0; }
}
