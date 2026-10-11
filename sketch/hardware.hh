#pragma once

#include <Arduino.h>

#include <cstdint>

#include "cell.hh"

const uint8_t PROBE_PIN = A0;

const uint8_t RELAY_A_PIN = 10;
const uint8_t RELAY_B_PIN = 9;
const uint8_t RELAY_PINS[] = {RELAY_A_PIN, RELAY_B_PIN};
const size_t RELAYS_COUNT = sizeof(RELAY_PINS) / sizeof(RELAY_PINS[0]);

Cell CELLS[] = {
    Cell("A", RELAY_A_PIN, true),
    Cell("B", RELAY_B_PIN, true),
};
const size_t CELLS_COUNT = sizeof(CELLS) / sizeof(CELLS[0]);
