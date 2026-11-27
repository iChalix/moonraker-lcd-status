/*
  MoonrakerLcdStatus - Statusanzeige fuer Klipper/Moonraker

  Der Arduino zeigt nur an, was der Dienst auf dem Raspberry Pi vorgibt, und
  meldet den Drehgeber zurueck. Seiten, Menues und Sprache liegen auf dem Pi,
  der Sketch muss fuer Aenderungen daran nicht neu geflasht werden.

  Hardware: Uno/Nano (ATmega328P, 5 V), HD44780-Text-LCD mit PCF8574-Adapter
  (I2C), optional Drehgeber (z. B. KY-040).

    LCD         GND->GND  VCC->5V  SDA->A4  SCL->A5
    Drehgeber   GND->GND  +->5V    CLK->D2  DT->D3  SW->D4

  Keine Zusatzbibliotheken noetig (nur Wire). Protokoll: docs/protokoll.md
*/

#include <Wire.h>

// ------------------------------------------------------------ Einstellungen

// Displaygroesse: 20x4 oder 16x2 (andere Groessen bis 20x4 gehen auch)
#define LCD_COLS 20
#define LCD_ROWS 4

// 0 = I2C-Adresse selbst suchen (0x20-0x27, 0x38-0x3F), sonst fest, z. B. 0x27
#define LCD_ADDRESS 0

#define ENCODER_CLK 2
#define ENCODER_DT 3
#define ENCODER_SW 4
// Flanken pro Rastung: 0 = selbst erkennen, sonst fest 4 oder 2.
// Erkennung: Bleibt der Drehgeber in der Mittelstellung (CLK und DT LOW)
// stehen, hat er 2 Flanken pro Rastung (manche HW-040/KY-040), sonst 4.
#define ENCODER_STEPS 0

#define SERIAL_BAUD 57600

// Ohne Nachricht vom Dienst wird das Display nach dieser Zeit dunkel (ms)
#define HOST_TIMEOUT 30000UL

// ---------------------------------------------------------------- Konstanten

#define SKETCH_VERSION "1.0.1"
#define PROTOCOL_VERSION "1"

#define BUTTON_DEBOUNCE 30UL
#define BUTTON_LONG 800UL
#define ROTATE_REPORT 30UL
#define ENCODER_REST 500UL  // so lange in der Mittelstellung = 2 Flanken pro Rastung
#define LCD_RETRY 2000UL

// PCF8574: P0=RS P1=RW P2=E P3=Beleuchtung P4..P7=D4..D7
#define PCF_RS 0x01
#define PCF_E 0x04
#define PCF_BL 0x08

// -------------------------------------------------------------------- LCD

uint8_t lcdAddress = 0;    // 0 = kein Display gefunden
bool backlight = true;     // Wunsch des Dienstes
bool asleep = false;       // dunkel, weil der Dienst schweigt
unsigned long lcdRetryAt = 0;

uint8_t want[LCD_ROWS][LCD_COLS];  // Sollinhalt (Codes wie im Protokoll)
uint32_t dirty[LCD_ROWS];          // Bit je Spalte: muss neu geschrieben werden
uint8_t glyphs[8][8];
uint8_t glyphDirty = 0;
int8_t hwRow = -1, hwCol = -1;     // wo der Schreibzeiger des LCD steht

uint8_t lightBit() { return (backlight && !asleep) ? PCF_BL : 0; }

bool probe(uint8_t address) {
  Wire.beginTransmission(address);
  return Wire.endTransmission() == 0;
}

bool pcfWrite(uint8_t value) {
  Wire.beginTransmission(lcdAddress);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

void lcdLost() {
  lcdAddress = 0;
  lcdRetryAt = millis() + LCD_RETRY;
}

void queueNibble(uint8_t high, uint8_t rs) {
  uint8_t base = (high & 0xF0) | rs | lightBit();
  Wire.write(base);
  Wire.write((uint8_t)(base | PCF_E));
  Wire.write(base);
}

void lcdSend(uint8_t value, uint8_t rs) {
  if (!lcdAddress) return;
  Wire.beginTransmission(lcdAddress);
  queueNibble(value, rs);
  queueNibble((uint8_t)(value << 4), rs);
  if (Wire.endTransmission() != 0) lcdLost();
}

void lcdCommand(uint8_t value) { lcdSend(value, 0); }

void lcdNibble(uint8_t high) {
  if (!lcdAddress) return;
  Wire.beginTransmission(lcdAddress);
  queueNibble(high, 0);
  if (Wire.endTransmission() != 0) lcdLost();
}

void markAllDirty() {
  for (uint8_t r = 0; r < LCD_ROWS; r++) dirty[r] = (1UL << LCD_COLS) - 1;
  glyphDirty = 0xFF;
  hwRow = hwCol = -1;
}

// Initialisierung aus jedem Zustand heraus, ohne den Inhalt zu loeschen. Damit
// laesst sich ein durch Stoerimpulse verwirrtes LCD ohne Flackern auffangen.
void lcdInit() {
  lcdNibble(0x30); delay(5);
  lcdNibble(0x30); delay(1);
  lcdNibble(0x30); delay(1);
  lcdNibble(0x20); delay(1);
  lcdCommand(0x28);                  // 4 Bit, 2 Zeilen (gilt auch fuer 4), 5x8
  lcdCommand(asleep ? 0x08 : 0x0C);  // Display an/aus, kein Cursor
  lcdCommand(0x06);                  // Zeiger wandert nach rechts
  markAllDirty();
}

void lcdSearch() {
  if (LCD_ADDRESS) {
    if (probe(LCD_ADDRESS)) lcdAddress = LCD_ADDRESS;
  } else {
    for (uint8_t i = 0; i < 16 && !lcdAddress; i++) {
      uint8_t address = i < 8 ? 0x27 - i : 0x3F - (i - 8);
      if (probe(address)) lcdAddress = address;
    }
  }
  if (lcdAddress) {
    delay(50);
    lcdInit();
  } else {
    lcdRetryAt = millis() + LCD_RETRY;
  }
}

// Pro Durchlauf hoechstens ein Zeichen schreiben: so bleibt loop() schnell
// genug, um die serielle Schnittstelle und den Drehgeber zu bedienen.
void lcdStep() {
  if (!lcdAddress) {
    if ((long)(millis() - lcdRetryAt) >= 0) lcdSearch();
    return;
  }
  if (glyphDirty) {
    for (uint8_t n = 0; n < 8; n++) {
      if (!(glyphDirty & (1 << n))) continue;
      lcdCommand(0x40 | (n << 3));
      for (uint8_t i = 0; i < 8; i++) lcdSend(glyphs[n][i], PCF_RS);
      if (lcdAddress) glyphDirty &= ~(1 << n);
      hwRow = hwCol = -1;
      return;
    }
  }
  for (uint8_t r = 0; r < LCD_ROWS; r++) {
    if (!dirty[r]) continue;
    for (uint8_t c = 0; c < LCD_COLS; c++) {
      if (!(dirty[r] & (1UL << c))) continue;
      if (hwRow != r || hwCol != c) {
        static const uint8_t base[4] = {0x00, 0x40, LCD_COLS, 0x40 + LCD_COLS};
        lcdCommand(0x80 | (base[r] + c));
      }
      uint8_t code = want[r][c];
      if (code >= 0x80 && code <= 0x87) code -= 0x80;  // eigene Zeichen 0-7
      lcdSend(code, PCF_RS);
      if (!lcdAddress) return;
      dirty[r] &= ~(1UL << c);
      hwRow = r;
      hwCol = c + 1;
      if (hwCol >= LCD_COLS) hwRow = hwCol = -1;
      return;
    }
  }
}

void setCell(uint8_t row, uint8_t col, uint8_t code) {
  if (want[row][col] == code) return;
  want[row][col] = code;
  dirty[row] |= 1UL << col;
}

void setRow(uint8_t row, const char *text, uint8_t length) {
  for (uint8_t c = 0; c < LCD_COLS; c++) {
    setCell(row, c, c < length ? (uint8_t)text[c] : ' ');
  }
}

void clearRows() {
  for (uint8_t r = 0; r < LCD_ROWS; r++) setRow(r, "", 0);
}

void setAsleep(bool value) {
  if (asleep == value) return;
  asleep = value;
  lcdCommand(asleep ? 0x08 : 0x0C);
}

void setBacklight(bool value) {
  backlight = value;
  if (lcdAddress && !pcfWrite(lightBit())) lcdLost();
}

// --------------------------------------------------------------- Protokoll

#define BUFFER_SIZE 40
char buffer[BUFFER_SIZE];
uint8_t bufferLength = 0;
bool bufferOverflow = false;
unsigned long lastHost = 0;

const char HEX_DIGITS[] = "0123456789ABCDEF";

void sendMessage(const char *payload) {
  uint8_t sum = 0;
  for (const char *p = payload; *p; p++) sum ^= (uint8_t)*p;
  Serial.print(payload);
  Serial.write('*');
  Serial.write(HEX_DIGITS[sum >> 4]);
  Serial.write(HEX_DIGITS[sum & 15]);
  Serial.write('\n');
}

int8_t hexValue(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  return -1;
}

void sendIdent() {
  char text[32];
  char address[3] = {HEX_DIGITS[lcdAddress >> 4], HEX_DIGITS[lcdAddress & 15], 0};
  // MLS = Kennung, daran erkennt der Dienst den richtigen Arduino
  snprintf(text, sizeof(text), "IMLS %s %s %d %d %s", PROTOCOL_VERSION, SKETCH_VERSION,
           LCD_COLS, LCD_ROWS, address);
  sendMessage(text);
}

bool handleGlyph(const char *text, uint8_t length) {
  if (length != 17 || text[0] < '0' || text[0] > '7') return false;
  uint8_t pattern[8];
  for (uint8_t i = 0; i < 8; i++) {
    int8_t high = hexValue(text[1 + i * 2]);
    int8_t low = hexValue(text[2 + i * 2]);
    if (high < 0 || low < 0) return false;
    pattern[i] = ((high << 4) | low) & 0x1F;
  }
  uint8_t n = text[0] - '0';
  memcpy(glyphs[n], pattern, 8);
  glyphDirty |= 1 << n;
  return true;
}

bool handleCommand(const char *text, uint8_t length) {
  switch (text[0]) {
    case 'L':  // Zeile: L<Zeile><Text>
      if (length < 2 || text[1] < '0' || text[1] >= '0' + LCD_ROWS) return false;
      setRow(text[1] - '0', text + 2, length - 2);
      return true;
    case 'G':  // eigenes Zeichen: G<0-7><16 Hex-Ziffern>
      return handleGlyph(text + 1, length - 1);
    case 'B':  // Beleuchtung: B0 / B1
      if (length != 2) return false;
      setBacklight(text[1] == '1');
      return true;
    case 'C':  // alles loeschen
      clearRows();
      return true;
    case 'Z':  // LCD neu initialisieren und alles neu schreiben
      if (lcdAddress) lcdInit();
      return true;
    case 'P':  // Lebenszeichen
      return true;
  }
  return false;
}

void handleLine() {
  if (bufferOverflow || bufferLength < 4 || buffer[bufferLength - 3] != '*') {
    sendMessage("NF");  // Format
    return;
  }
  int8_t high = hexValue(buffer[bufferLength - 2]);
  int8_t low = hexValue(buffer[bufferLength - 1]);
  uint8_t length = bufferLength - 3;
  uint8_t sum = 0;
  for (uint8_t i = 0; i < length; i++) sum ^= (uint8_t)buffer[i];
  if (high < 0 || low < 0 || sum != (uint8_t)((high << 4) | low)) {
    sendMessage("NC");  // Pruefsumme
    return;
  }
  lastHost = millis();
  if (asleep) {
    setAsleep(false);
    setBacklight(backlight);
  }
  if (buffer[0] == '?') {
    sendIdent();
    return;
  }
  buffer[length] = 0;
  sendMessage(handleCommand(buffer, length) ? "K" : "NU");  // unbekannt/ungueltig
}

void serialStep() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (bufferLength || bufferOverflow) handleLine();
      bufferLength = 0;
      bufferOverflow = false;
      return;
    }
    if (bufferLength < BUFFER_SIZE - 1) buffer[bufferLength++] = c;
    else bufferOverflow = true;
  }
}

// --------------------------------------------------------------- Drehgeber

volatile int8_t encoderDetents = 0;
volatile int8_t encoderAccu = 0;
volatile uint8_t encoderState = 3;
volatile bool encoderHalf = ENCODER_STEPS == 2;  // 2 Flanken pro Rastung
volatile unsigned long encoderChanged = 0;

// Bis zur Raststellung aufgelaufene Flanken als Rastung werten
void encoderCount() {
  int8_t need = encoderHalf ? 1 : 2;
  if (encoderAccu >= need) encoderDetents++;
  else if (encoderAccu <= -need) encoderDetents--;
  encoderAccu = 0;
}

// Zustandstabelle: Kontaktprellen hebt sich auf, gezaehlt wird erst in der
// Raststellung. Verlorene Flanken koennen sich so nicht aufsummieren.
void encoderISR() {
  static const int8_t table[16] = {0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0};
  uint8_t now = (digitalRead(ENCODER_CLK) << 1) | digitalRead(ENCODER_DT);
  if (now == encoderState) return;
  encoderAccu += table[(encoderState << 2) | now];
  encoderState = now;
  encoderChanged = millis();
  if (now == 3 || (encoderHalf && now == 0)) encoderCount();
}

// Ein Drehgeber mit 4 Flanken rastet nur bei CLK und DT HIGH ein. Ruht er
// laenger mit beiden LOW, rastet er auch dort: 2 Flanken pro Rastung. Gilt bis
// zum naechsten Reset (der Dienst setzt den Nano beim Oeffnen des Ports zurueck).
void encoderDetect() {
#if ENCODER_STEPS == 0
  if (encoderHalf) return;
  noInterrupts();
  if (encoderState == 0 && millis() - encoderChanged >= ENCODER_REST) {
    encoderHalf = true;
    encoderCount();  // die Rastung, die bis hierher gefuehrt hat
  }
  interrupts();
#endif
}

void encoderStep() {
  static unsigned long last = 0;
  encoderDetect();
  if (millis() - last < ROTATE_REPORT) return;
  noInterrupts();
  int8_t detents = encoderDetents;
  encoderDetents = 0;
  interrupts();
  if (!detents) return;
  last = millis();
  char text[8];
  snprintf(text, sizeof(text), "R%d", detents);
  sendMessage(text);
}

void buttonStep() {
  static bool pressed = false, raw = false, longSent = false;
  static unsigned long changed = 0, since = 0;
  bool now = digitalRead(ENCODER_SW) == LOW;
  if (now != raw) {
    raw = now;
    changed = millis();
  }
  if (raw != pressed && millis() - changed >= BUTTON_DEBOUNCE) {
    pressed = raw;
    if (pressed) {
      since = millis();
      longSent = false;
    } else if (!longSent) {
      sendMessage("S");
    }
  }
  if (pressed && !longSent && millis() - since >= BUTTON_LONG) {
    longSent = true;
    sendMessage("H");
  }
}

// --------------------------------------------------------------------- main

void setup() {
  Serial.begin(SERIAL_BAUD);
  pinMode(ENCODER_CLK, INPUT_PULLUP);
  pinMode(ENCODER_DT, INPUT_PULLUP);
  pinMode(ENCODER_SW, INPUT_PULLUP);
  encoderState = (digitalRead(ENCODER_CLK) << 1) | digitalRead(ENCODER_DT);
  encoderChanged = millis();
  attachInterrupt(digitalPinToInterrupt(ENCODER_CLK), encoderISR, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ENCODER_DT), encoderISR, CHANGE);

  Wire.begin();
#if defined(WIRE_HAS_TIMEOUT)
  Wire.setWireTimeout(5000, true);  // haengender I2C-Bus darf nichts blockieren
#endif

  memset(want, ' ', sizeof(want));
  setRow(0, "Moonraker LCD " SKETCH_VERSION, 14 + sizeof(SKETCH_VERSION) - 1);
  setRow(1, "waiting for host", 16);
  lcdSearch();
  lastHost = millis();
  sendIdent();
}

void loop() {
  serialStep();
  encoderStep();
  buttonStep();
  lcdStep();
  if (!asleep && millis() - lastHost >= HOST_TIMEOUT) {
    setAsleep(true);
    setBacklight(backlight);  // schaltet die Beleuchtung aus, der Wunsch bleibt
  }
}
