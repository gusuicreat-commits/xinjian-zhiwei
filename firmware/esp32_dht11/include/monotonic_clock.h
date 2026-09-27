#pragma once
#include <stdint.h>
#include <esp_timer.h>

// ESP-IDF provides a 64-bit clock since boot; widening millis() after wrap is too late.
inline uint64_t monotonicMillis() {
    return static_cast<uint64_t>(esp_timer_get_time()) / 1000ULL;
}
