#include <cstdint>
#include <vector>

#include <Arduino_RouterBridge.h>

#include "hardware.hh"
#include "led_matrix.hh"

const unsigned long SAMPLE_PERIOD_MS = 50;
const unsigned long MATRIX_PUSH_PERIOD_MS = 400;

CurrentGraph current_graph;

int32_t get_cell_count() { return (int32_t)CELLS_COUNT; }

// Keeps at least one cell active. Returns -1 (bad index), 0 (refused), or 1 (ok).
int32_t set_relay(int32_t index, int32_t bypassed) {
  if (index < 0 || (size_t)index >= CELLS_COUNT)
    return -1;

  bool want = bypassed != 0;
  if (want) {
    bool others_all_bypassed = true;
    for (size_t j = 0; j < CELLS_COUNT; j++) {
      if ((int32_t)j == index)
        continue;
      if (!CELLS[j].bypassed) {
        others_all_bypassed = false;
        break;
      }
    }
    if (others_all_bypassed)
      return 0;
  }

  CELLS[index].bypass(want);
  return 1;
}

void setup() {
  Serial.begin(115200);

  for (size_t i = 0; i < CELLS_COUNT; ++i) {
    CELLS[i].begin();
  }
  current_graph.begin();

  Bridge.begin();
  Bridge.notify("ready", true);

  Bridge.provide("get_cell_count", get_cell_count);
  Bridge.provide("set_relay", set_relay);
}

void loop() {
  unsigned long now = millis();
  int32_t raw = analogRead(PROBE_PIN); // 0..16383, negative means ADC error

  static unsigned long t_last_sample = 0;
  if (now - t_last_sample >= SAMPLE_PERIOD_MS) {
    t_last_sample = now;

    int32_t mask = 0;
    for (size_t i = 0; i < CELLS_COUNT; i++) {
      if (CELLS[i].bypassed)
        mask |= (1L << i);
    }

    std::vector<int32_t> f;
    f.reserve(3);
    f.push_back((int32_t)now);
    f.push_back(raw);
    f.push_back(mask);
    Bridge.notify("sample", f);

    Serial.print("t=");
    Serial.print(now);
    Serial.print(" raw=");
    Serial.print(raw);
    Serial.print(" mask=0b");
    Serial.println(mask, BIN);
  }

  static unsigned long t_last_graph = 0;
  if (now - t_last_graph >= MATRIX_PUSH_PERIOD_MS) {
    t_last_graph = now;
    current_graph.push(raw);
    current_graph.render();
  }
}
