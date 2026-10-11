#pragma once

#include <Arduino.h>
#include <Arduino_LED_Matrix.h>

#include <cstdint>

// Scrolling bar graph on the onboard 8x13 LED matrix. Auto-ranges to the
// loudest recent peak so it doesn't need to know the real full-scale value.
struct CurrentGraph {
  static const uint8_t ROWS = 8;
  static const uint8_t COLS = 13;

  ArduinoLEDMatrix matrix;
  // Lit rows per column, oldest to newest.
  uint8_t levels[COLS] = {0};
  // Index is row * COLS + col.
  uint8_t frame[ROWS * COLS] = {0};
  float peak = 1.0f;

  void begin() {
    matrix.begin();
    matrix.setGrayscaleBits(3); // 0..7 levels; we only use 0/7.
  }

  void push(int32_t raw) {
    if (raw < 0)
      raw = 0;
    if ((float)raw > peak)
      peak = (float)raw;
    else
      // Slow decay so old peaks don't stick forever.
      peak *= 0.999f;
    if (peak < 1.0f)
      peak = 1.0f;

    uint8_t level = (uint8_t)((float)raw / peak * ROWS + 0.5f);
    if (level > ROWS)
      level = ROWS;

    for (uint8_t c = 0; c < COLS - 1; c++)
      levels[c] = levels[c + 1];
    levels[COLS - 1] = level;
  }

  void render() {
    for (uint8_t c = 0; c < COLS; c++) {
      uint8_t lit = levels[c];
      for (uint8_t r = 0; r < ROWS; r++) {
        // Bottom row first.
        frame[r * COLS + c] = ((ROWS - 1 - r) < lit) ? 7 : 0;
      }
    }
    matrix.draw(frame);
  }
};
