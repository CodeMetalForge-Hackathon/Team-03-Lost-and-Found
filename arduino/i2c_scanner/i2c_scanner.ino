// I2C scanner: lists every device that answers on the I2C bus.
// Put this in a folder named i2c_scanner, upload, open Serial Monitor at 9600.
#include <Wire.h>

void setup() {
  Serial.begin(9600);
  Wire.begin();
  delay(500);
}

void loop() {
  Serial.println("Scanning I2C...");
  byte found = 0;
  for (byte addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      Serial.print("  Device found at 0x");
      if (addr < 16) Serial.print('0');
      Serial.println(addr, HEX);
      found++;
    }
  }
  if (!found) Serial.println("  Nothing found - check the cable is in an I2C port and fully seated");
  Serial.println();
  delay(3000);
}
