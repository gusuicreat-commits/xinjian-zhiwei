#include "dht11_reader.h"

namespace {
bool waitForLevel(uint8_t gpio, int level, uint32_t timeout_us) {
    const uint32_t started = micros();
    while (digitalRead(gpio) != level) {
        if (static_cast<uint32_t>(micros() - started) > timeout_us) return false;
    }
    return true;
}
}

Dht11Frame decodeDht11Frame(const uint8_t raw[5]) {
    Dht11Frame frame;
    memcpy(frame.raw, raw, sizeof(frame.raw));
    const uint8_t checksum = static_cast<uint8_t>(raw[0] + raw[1] + raw[2] + raw[3]);
    if (checksum != raw[4]) {
        frame.status = Dht11ReadStatus::Checksum;
        return frame;
    }
    const bool negative = (raw[2] & 0x80U) != 0;
    const float magnitude = static_cast<float>(raw[2] & 0x7fU) +
                            static_cast<float>(raw[3] & 0x0fU) * 0.1f;
    frame.temperature_c = negative ? -magnitude : magnitude;
    frame.humidity_rh = static_cast<float>(raw[0]) +
                        static_cast<float>(raw[1] & 0x0fU) * 0.1f;
    if (frame.humidity_rh < 0.0f || frame.humidity_rh > 100.0f ||
        frame.temperature_c < -40.0f || frame.temperature_c > 80.0f) {
        frame.status = Dht11ReadStatus::Range;
        return frame;
    }
    frame.status = Dht11ReadStatus::Ok;
    return frame;
}

Dht11Frame readDht11(uint8_t data_gpio) {
    Dht11Frame frame;
    frame.trigger_started_ms = millis();
    pinMode(data_gpio, OUTPUT);
    digitalWrite(data_gpio, LOW);
    delay(18);
    digitalWrite(data_gpio, HIGH);
    delayMicroseconds(40);
    // The selected four-pin sensor uses the documented external 4.7kΩ pullup;
    // do not silently replace that circuit with the ESP32's weak internal one.
    pinMode(data_gpio, INPUT);

    if (!waitForLevel(data_gpio, LOW, 120) || !waitForLevel(data_gpio, HIGH, 120) ||
        !waitForLevel(data_gpio, LOW, 120)) {
        frame.status = Dht11ReadStatus::Timeout;
        return frame;
    }
    noInterrupts();
    for (uint8_t bit = 0; bit < 40; ++bit) {
        if (!waitForLevel(data_gpio, HIGH, 100)) {
            interrupts();
            frame.status = Dht11ReadStatus::Timeout;
            return frame;
        }
        const uint32_t high_started = micros();
        if (!waitForLevel(data_gpio, LOW, 120)) {
            interrupts();
            frame.status = Dht11ReadStatus::Timeout;
            return frame;
        }
        const uint32_t high_us = static_cast<uint32_t>(micros() - high_started);
        frame.raw[bit / 8] <<= 1;
        if (high_us > 50) frame.raw[bit / 8] |= 1U;
    }
    interrupts();
    frame.read_finished_ms = millis();
    const Dht11Frame decoded = decodeDht11Frame(frame.raw);
    frame.status = decoded.status;
    frame.temperature_c = decoded.temperature_c;
    frame.humidity_rh = decoded.humidity_rh;
    return frame;
}

const char* dht11StatusText(Dht11ReadStatus status) {
    switch (status) {
        case Dht11ReadStatus::Ok: return "ok";
        case Dht11ReadStatus::Timeout: return "timeout";
        case Dht11ReadStatus::Checksum: return "checksum";
        case Dht11ReadStatus::Range: return "range";
        case Dht11ReadStatus::Protocol: return "protocol";
    }
    return "protocol";
}
