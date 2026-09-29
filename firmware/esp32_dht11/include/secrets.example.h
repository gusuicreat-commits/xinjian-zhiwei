// Copy this file to secrets.h (ignored by git) and fill local test values.
#define XJ_WIFI_SSID ""
#define XJ_WIFI_PASSWORD ""
#define XJ_API_BASE_URL "https://example.invalid/api/v1/device/ingest"
#define XJ_DEVICE_ID ""
#define XJ_DEVICE_TOKEN ""
#define XJ_EXPERIMENT_SESSION_ID ""
// PEM certificate text for the API host. Keep empty only when HTTPS is not used.
#define XJ_CA_CERT ""
// Set to 1 only for an isolated local HTTP test server; never for production.
// This does not disable HTTPS certificate validation; HTTPS always requires CA.
#define XJ_ALLOW_INSECURE_HTTP 0
