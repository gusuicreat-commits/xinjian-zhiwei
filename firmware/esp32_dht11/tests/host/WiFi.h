#pragma once
#include "Arduino.h"
constexpr int WL_CONNECTED=3, WIFI_STA=1;
struct WiFiClient {};
struct WiFiMock {
    int state=WL_CONNECTED;
    int status() {return state;}
    void mode(int) {}
    void begin(const char*,const char*) {}
    struct IP { String toString(){return "127.0.0.1";} };
    IP localIP() {return {};}
};
inline WiFiMock WiFi;
