#pragma once
inline unsigned ca_calls = 0, insecure_calls = 0;
struct WiFiClientSecure {
    void setCACert(const char*) { ++ca_calls; }
    void setInsecure() { ++insecure_calls; }
};
