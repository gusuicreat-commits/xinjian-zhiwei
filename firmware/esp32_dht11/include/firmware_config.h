#pragma once

#if __has_include("secrets.h")
#include "secrets.h"
#endif

#ifndef XJ_WIFI_SSID
#define XJ_WIFI_SSID ""
#endif
#ifndef XJ_WIFI_PASSWORD
#define XJ_WIFI_PASSWORD ""
#endif
#ifndef XJ_API_BASE_URL
#define XJ_API_BASE_URL ""
#endif
#ifndef XJ_DEVICE_ID
#define XJ_DEVICE_ID ""
#endif
#ifndef XJ_DEVICE_TOKEN
#define XJ_DEVICE_TOKEN ""
#endif
#ifndef XJ_EXPERIMENT_SESSION_ID
#define XJ_EXPERIMENT_SESSION_ID ""
#endif
#ifndef XJ_CA_CERT
#define XJ_CA_CERT ""
#endif
#ifndef XJ_FIRMWARE_VERSION
#define XJ_FIRMWARE_VERSION "0.2.5"
#endif
#ifndef XJ_IS_TEST_DATA
#define XJ_IS_TEST_DATA 1
#endif
#ifndef XJ_ALLOW_INSECURE_HTTP
#define XJ_ALLOW_INSECURE_HTTP 0
#endif

constexpr uint8_t XJ_DHT11_DATA_GPIO = 4;
// Project minimum and configured period; vendor V1.3 requires strictly > 2000 ms.
constexpr uint32_t XJ_SAMPLE_INTERVAL_MS = 3000UL;
static_assert(XJ_SAMPLE_INTERVAL_MS >= 3000UL, "DHT11 project minimum is 3 seconds");
constexpr uint32_t XJ_HEARTBEAT_INTERVAL_MS = 30000UL;
constexpr uint32_t XJ_HTTP_TIMEOUT_MS = 5000UL;
constexpr uint8_t XJ_MAX_HTTP_ATTEMPTS = 3;
