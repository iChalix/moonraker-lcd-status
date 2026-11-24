#pragma once
#include <stdint.h>
#define WIRE_HAS_TIMEOUT 1
struct HostWire {
  void begin() {}
  void setWireTimeout(uint32_t, bool) {}
  void beginTransmission(uint8_t address);
  void write(uint8_t value);
  uint8_t endTransmission();
};
extern HostWire Wire;
