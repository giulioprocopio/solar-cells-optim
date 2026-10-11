#pragma once

#include <Arduino.h>

#include <cstdint>

struct Cell {
  const char *id;
  uint8_t relay_pin;
  bool active_high;
  volatile bool bypassed;

  void begin() {
    pinMode(relay_pin, OUTPUT);
    bypass(false);
  }

  void bypass(bool want) {
    digitalWrite(relay_pin, (want == active_high) ? HIGH : LOW);
    bypassed = want;
  }

  Cell(const char *id, uint8_t relay_pin, bool active_high = true)
      : id(id), relay_pin(relay_pin), active_high(active_high),
        bypassed(false) {}
};
