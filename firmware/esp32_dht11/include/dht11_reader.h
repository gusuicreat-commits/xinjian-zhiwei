#pragma once

#include <Arduino.h>

enum class Dht11ReadStatus : uint8_t { Ok, Timeout, Checksum, Range, Protocol };

struct Dht11Frame {
    Dht11ReadStatus status = Dht11ReadStatus::Protocol;
    float temperature_c = 0.0f;
    float humidity_rh = 0.0f;
    uint8_t raw[5] = {0, 0, 0, 0, 0};
    uint32_t trigger_started_ms = 0;
    uint32_t read_finished_ms = 0;
};

Dht11Frame decodeDht11Frame(const uint8_t raw[5]);
Dht11Frame readDht11(uint8_t data_gpio);
const char* dht11StatusText(Dht11ReadStatus status);
