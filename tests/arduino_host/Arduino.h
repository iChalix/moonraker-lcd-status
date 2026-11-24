// Minimaler Arduino-Ersatz, um den echten Sketch auf dem PC laufen zu lassen.
#pragma once
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <string>

#define INPUT_PULLUP 2
#define LOW 0
#define HIGH 1
#define CHANGE 1

unsigned long millis();
void delay(unsigned long ms);
void pinMode(int pin, int mode);
int digitalRead(int pin);
inline int digitalPinToInterrupt(int pin) { return pin; }
void attachInterrupt(int interrupt, void (*handler)(), int mode);
inline void noInterrupts() {}
inline void interrupts() {}

struct HostSerial {
  void begin(long) {}
  int available();
  int read();
  void write(char c);
  void print(const char *text);
};
extern HostSerial Serial;
