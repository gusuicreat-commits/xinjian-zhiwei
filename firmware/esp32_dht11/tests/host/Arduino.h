#pragma once
// Host-only I/O adapter. Firmware logic and ArduinoJson are compiled unchanged.
#include <cstdint>
#include <cstdio>
#include <string>
#include <ArduinoJson.h>
class String : public std::string {
public:
    using std::string::string;
    using std::string::operator=;
    String() = default;
    String(const std::string& s) : std::string(s) {}
    bool isEmpty() const { return empty(); }
    bool startsWith(const char* s) const { return rfind(s, 0) == 0; }
    size_t write(uint8_t c) { push_back(c); return 1; }
    size_t write(const uint8_t* p, size_t n) { append(reinterpret_cast<const char*>(p), n); return n; }
};
namespace ArduinoJson {
template<> struct Converter<String> {
    static void toJson(const String& s, JsonVariant dst) { dst.set(std::string(s)); }
    static String fromJson(JsonVariantConst src) { const char* s=src.as<const char*>(); return s ? s : ""; }
    static bool checkJson(JsonVariantConst src) { return src.is<const char*>(); }
};
}
inline uint64_t host_ms = 0;
// Decoder tests compile the real driver; these stubs do not model GPIO timing.
constexpr int INPUT = 0, OUTPUT = 1, LOW = 0, HIGH = 1;
inline uint32_t micros() { static uint32_t ticks = 0; return ++ticks; }
inline int digitalRead(uint8_t) { return HIGH; }
inline void digitalWrite(uint8_t, int) {}
inline void pinMode(uint8_t, int) {}
inline void delayMicroseconds(uint32_t) {}
inline void noInterrupts() {}
inline void interrupts() {}
inline uint32_t millis() { return host_ms; }
inline void delay(uint32_t ms) { host_ms += ms; }
inline void configTime(int, int, const char*, const char*) {}
struct SerialMock {
    void begin(int) {}
    void println(const String&) {}
    template<class... T> void printf(const char*, T...) {}
};
inline SerialMock Serial;
