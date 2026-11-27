// Laesst den unveraenderten Sketch auf dem PC laufen: Serial an einem pty,
// Wire an einem Modell von PCF8574 + HD44780 (Befehle, DDRAM, CGRAM).
//
// Der Pfad des pty steht in der ersten Ausgabezeile. Befehle auf stdin:
//   SHOW            Display ausgeben (Hex je Zeile, Licht, an/aus, CGRAM-Pruefsumme)
//   CW | CCW        eine Rastung drehen (mit Kontaktprellen)
//   CLICK | LONG    Taster
//   BOUNCE          5 ms Stoerimpuls am Taster - darf nichts ausloesen
//   UNPLUG | PLUG   LCD vom I2C-Bus trennen / wieder anstecken (leer)
//   GARBLE          LCD durcheinanderbringen (Halbbyte verloren, Inhalt zerstoert)
//   RESET           Sketch neu starten
//   SILENCE ms      Zeit vorstellen (millis springt)
#include <fcntl.h>
#include <poll.h>
#include <stdlib.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>
#include <vector>
#include "Arduino.h"
#include "Wire.h"

#include SKETCH

// ------------------------------------------------------------------ HD44780
struct Lcd {
  bool present = true, fourBit = false, half = false, on = false, light = false;
  uint8_t high = 0, address = 0, cg = 0, last = 0;
  bool toCg = false;
  uint8_t ddram[128], cgram[64];
  int errors = 0;
  void power() {
    fourBit = half = on = toCg = false;
    address = cg = last = 0;
    memset(ddram, ' ', sizeof ddram);
    memset(cgram, 0xAA, sizeof cgram);
  }
  void port(uint8_t v) {
    light = v & 0x08;
    if ((last & 0x04) && !(v & 0x04)) {  // fallende Flanke von E
      // RS und Daten muessen waehrend E stabil sein
      if ((last & 0xF1) != (v & 0xF1)) errors++;
      nibble(last & 0xF0, last & 0x01);
    }
    if (!(last & 0x04) && (v & 0x04) && (last & 0xF1) != (v & 0xF1)) errors++;  // Vorlauf
    last = v;
  }
  void nibble(uint8_t n, bool rs) {
    if (!fourBit) { command8(n, rs); return; }
    if (!half) { high = n; half = true; return; }
    half = false;
    byte_(high | (n >> 4), rs);
  }
  void command8(uint8_t v, bool rs) {
    if (!rs && (v & 0xF0) == 0x20) { fourBit = true; half = false; }
  }
  void byte_(uint8_t v, bool rs) {
    if (rs) {
      if (toCg) { cgram[cg & 63] = v; cg++; }
      else {
        ddram[address] = v;
        address++;
        if (address == 0x28) address = 0x40;
        if (address == 0x68) address = 0;
      }
      return;
    }
    if (v & 0x80) { address = v & 0x7F; toCg = false; }
    else if (v & 0x40) { cg = v & 0x3F; toCg = true; }
    else if (v & 0x20) { if (v & 0x10) { fourBit = false; half = false; } }
    else if (v & 0x08) on = v & 0x04;
    else if (v == 0x01) memset(ddram, ' ', sizeof ddram);
  }
} lcd;

// --------------------------------------------------------------------- Wire
HostWire Wire;
static uint8_t wireAddress;
static std::vector<uint8_t> wireData;
void HostWire::beginTransmission(uint8_t a) { wireAddress = a; wireData.clear(); }
void HostWire::write(uint8_t v) { wireData.push_back(v); }
uint8_t HostWire::endTransmission() {
  if (wireAddress != 0x27 || !lcd.present) return 2;
  if (wireData.size() > 32) { lcd.errors++; return 1; }  // Wire-Puffer
  for (uint8_t v : wireData) lcd.port(v);
  usleep(90 * (wireData.size() + 1));  // 100 kHz
  return 0;
}

// ------------------------------------------------------------------- Serial
HostSerial Serial;
static int fd = -1;
static std::string rx;
static size_t overflow = 0;
static void pump() {
  char chunk[256];
  ssize_t n = ::read(fd, chunk, sizeof chunk);
  for (ssize_t i = 0; i < n; i++) {
    if (rx.size() < 63) rx += chunk[i];  // RX-Puffer des ATmega328P
    else overflow++;
  }
}
int HostSerial::available() { pump(); return rx.size(); }
int HostSerial::read() { char c = rx[0]; rx.erase(0, 1); return (unsigned char)c; }
void HostSerial::write(char c) { if (::write(fd, &c, 1) < 0) {} }
void HostSerial::print(const char *t) { if (::write(fd, t, strlen(t)) < 0) {} }

// --------------------------------------------------------------------- Pins
static unsigned long skew = 0;
unsigned long millis() {
  timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  static long long start = t.tv_sec * 1000LL + t.tv_nsec / 1000000;
  return (unsigned long)(t.tv_sec * 1000LL + t.tv_nsec / 1000000 - start) + skew;
}
void delay(unsigned long ms) { usleep(ms * 1000); }
void pinMode(int, int) {}
static int pins[16] = {1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1};
static void (*handlers[16])() = {};
int digitalRead(int pin) { return pins[pin]; }
void attachInterrupt(int i, void (*h)(), int) { handlers[i] = h; }
static void setPin(int pin, int value) {
  pins[pin] = value;
  if (handlers[pin]) handlers[pin]();
}
static void bounce(int pin, int value) {  // prellender Kontakt
  for (int i = 0; i < 3; i++) { setPin(pin, value); setPin(pin, !value); }
  setPin(pin, value);
}
static void detent(int first, int second) {
  bounce(first, 0); bounce(second, 0); bounce(first, 1); bounce(second, 1);
}
// Drehgeber mit 2 Flanken pro Rastung: rastet bei HIGH/HIGH und LOW/LOW
static void halfDetent(int first, int second) {
  int value = pins[first] && pins[second] ? 0 : 1;
  bounce(first, value); bounce(second, value);
}
static void spin(unsigned long ms) {
  unsigned long end = millis() + ms;
  while ((long)(millis() - end) < 0) loop();
}

static void show() {
  static const uint8_t base[4] = {0x00, 0x40, LCD_COLS, 0x40 + LCD_COLS};
  for (int r = 0; r < LCD_ROWS; r++) {
    for (int c = 0; c < LCD_COLS; c++) printf("%02X", lcd.ddram[base[r] + c]);
    printf(" ");
  }
  unsigned sum = 0;
  for (uint8_t v : lcd.cgram) sum = sum * 31 + v;
  printf("%d %d %u %d %zu\n", lcd.light, lcd.on, sum, lcd.errors, overflow);
  fflush(stdout);
}

int main() {
  int slave;
  fd = posix_openpt(O_RDWR | O_NOCTTY);
  grantpt(fd);
  unlockpt(fd);
  const char *name = ptsname(fd);
  slave = open(name, O_RDWR | O_NOCTTY);  // offen halten, sonst EIO ohne Gegenseite
  termios t;
  tcgetattr(slave, &t);
  cfmakeraw(&t);
  tcsetattr(slave, TCSANOW, &t);
  fcntl(fd, F_SETFL, O_NONBLOCK);
  fcntl(0, F_SETFL, O_NONBLOCK);
  printf("%s\n", name);
  fflush(stdout);

  lcd.power();
  setup();
  std::string input;
  for (;;) {
    loop();
    usleep(50);
    char c;
    ssize_t n;
    while ((n = ::read(0, &c, 1)) == 1) {
      if (c != '\n') { input += c; continue; }
      std::string cmd = input;
      input.clear();
      if (cmd == "SHOW") show();
      else if (cmd == "CW") { detent(ENCODER_CLK, ENCODER_DT); spin(40); }
      else if (cmd == "CCW") { detent(ENCODER_DT, ENCODER_CLK); spin(40); }
      else if (cmd == "HCW") { halfDetent(ENCODER_CLK, ENCODER_DT); spin(40); }
      else if (cmd == "HCCW") { halfDetent(ENCODER_DT, ENCODER_CLK); spin(40); }
      else if (cmd == "CLICK") { pins[ENCODER_SW] = 0; spin(100); pins[ENCODER_SW] = 1; spin(60); }
      else if (cmd == "LONG") { pins[ENCODER_SW] = 0; spin(1000); pins[ENCODER_SW] = 1; spin(60); }
      else if (cmd == "BOUNCE") { pins[ENCODER_SW] = 0; spin(5); pins[ENCODER_SW] = 1; spin(60); }
      else if (cmd == "UNPLUG") lcd.present = false;
      else if (cmd == "PLUG") { lcd.power(); lcd.present = true; }
      else if (cmd == "GARBLE") { lcd.half = true; memset(lcd.ddram, '#', sizeof lcd.ddram); memset(lcd.cgram, 0x15, sizeof lcd.cgram); }
      else if (cmd == "RESET") { rx.clear(); setup(); }
      else if (cmd.rfind("SILENCE ", 0) == 0) skew += atol(cmd.c_str() + 8);
    }
    if (n == 0) return 0;  // stdin geschlossen
  }
}
