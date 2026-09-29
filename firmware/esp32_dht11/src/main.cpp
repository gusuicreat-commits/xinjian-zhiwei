#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <LittleFS.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <time.h>
#include <esp_system.h>

#include "dht11_reader.h"
#include "monotonic_clock.h"
#include "firmware_config.h"
#include "pending_store.h"

namespace {
String boot_id;
uint64_t sequence_no = 0;
uint64_t last_sample_ms = 0;
uint64_t last_heartbeat_ms = 0;
uint64_t last_retry_ms = 0;
uint64_t last_successful_trigger_ms = 0;
String last_successful_trigger_iso;
bool has_previous_conversion = false;
PendingStore pending_store;

String uuidV4() {
    uint32_t words[4] = {esp_random(), esp_random(), esp_random(), esp_random()};
    words[1] = (words[1] & 0xffff0fffU) | 0x00004000U;
    words[2] = (words[2] & 0x3fffffffU) | 0x80000000U;
    char buffer[37] = {};
    snprintf(buffer, sizeof(buffer), "%08lx-%04lx-%04lx-%04lx-%04lx%08lx",
             static_cast<unsigned long>(words[0]),
             static_cast<unsigned long>((words[1] >> 16) & 0xffffU),
             static_cast<unsigned long>(words[1] & 0xffffU),
             static_cast<unsigned long>((words[2] >> 16) & 0xffffU),
             static_cast<unsigned long>(words[2] & 0xffffU),
             static_cast<unsigned long>(words[3]));
    return String(buffer);
}

bool clockIsValid() { return time(nullptr) >= 1577836800; }

String nowIso() {
    if (!clockIsValid()) return String();
    time_t raw = time(nullptr);
    struct tm utc;
    gmtime_r(&raw, &utc);
    char buffer[25] = {};
    strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%SZ", &utc);
    return String(buffer);
}

void addCommon(JsonDocument& doc) {
    doc["protocolVersion"] = "1.0";
    doc["schemaVersion"] = "1";
    doc["requestId"] = uuidV4();
    doc["bootId"] = boot_id;
    doc["sequenceNo"] = sequence_no;
    doc["uptimeMs"] = monotonicMillis();
    doc["firmwareVersion"] = XJ_FIRMWARE_VERSION;
    doc["isTestData"] = XJ_IS_TEST_DATA != 0;
    const String sent_at = nowIso();
    if (!sent_at.isEmpty()) doc["sentAt"] = sent_at;
}

void addHeartbeat(JsonArray records, bool primed) {
    JsonObject record = records.add<JsonObject>();
    record["type"] = "heartbeat";
    const String observed_at = nowIso();
    if (!observed_at.isEmpty()) record["occurredAt"] = observed_at;
    JsonObject payload = record["payload"].to<JsonObject>();
    payload["metadata"]["source"] = "xinjian-esp32-dht11";
    payload["metadata"]["event_time_quality"] = observed_at.isEmpty() ? "unknown" : "device_reported";
    payload["metadata"]["dht11_sample_primed"] = primed;
}

void addReading(JsonArray records, const char* metric, float value, const char* unit,
                const String& conversion_occurred_at, uint64_t conversion_trigger_ms,
                uint64_t read_ms) {
    JsonObject record = records.add<JsonObject>();
    record["type"] = "reading";
    if (!conversion_occurred_at.isEmpty()) record["occurredAt"] = conversion_occurred_at;
    JsonObject payload = record["payload"].to<JsonObject>();
    payload["sensor_type"] = "dht11";
    payload["metric_key"] = metric;
    payload["value"] = value;
    payload["unit"] = unit;
    payload["metadata"]["conversion_triggered_uptime_ms"] = conversion_trigger_ms;
    payload["metadata"]["read_completed_uptime_ms"] = read_ms;
    payload["metadata"]["measurement_semantics"] = "previous_conversion";
    payload["metadata"]["event_time_quality"] = conversion_occurred_at.isEmpty() ? "unknown" : "device_reported";
}

void addReadFailure(JsonArray records, Dht11ReadStatus status, uint64_t read_ms) {
    JsonObject record = records.add<JsonObject>();
    record["type"] = "log";
    const String occurred_at = nowIso();
    if (!occurred_at.isEmpty()) record["occurredAt"] = occurred_at;
    JsonObject payload = record["payload"].to<JsonObject>();
    payload["level"] = "warning";
    payload["event_code"] = "DHT11_READ_FAILED";
    payload["message"] = dht11StatusText(status);
    payload["sensor_snapshot"]["component_id"] = "dht11";
    payload["sensor_snapshot"]["interface_id"] = "dht11_gpio";
    payload["sensor_snapshot"]["gpio"] = XJ_DHT11_DATA_GPIO;
    payload["sensor_snapshot"]["read_completed_uptime_ms"] = read_ms;
}

PendingEnvelope makeBatch(const Dht11Frame* frame, bool primed, bool include_reading,
                          const String& measurement_occurred_at = String()) {
    JsonDocument doc;
    addCommon(doc);
    JsonArray records = doc["records"].to<JsonArray>();
    if (include_reading && frame != nullptr) {
        addReading(records, "temperature", frame->temperature_c, "°C", measurement_occurred_at,
                   last_successful_trigger_ms, frame->read_finished_ms);
        addReading(records, "humidity", frame->humidity_rh, "%RH", measurement_occurred_at,
                   last_successful_trigger_ms, frame->read_finished_ms);
    } else if (frame != nullptr && frame->status != Dht11ReadStatus::Ok) {
        addReadFailure(records, frame->status, frame->read_finished_ms);
    }
    addHeartbeat(records, primed);
    String body;
    serializeJson(doc, body);
    PendingEnvelope pending;
    pending.session_id = XJ_EXPERIMENT_SESSION_ID;
    pending.request_id = doc["requestId"].as<String>();
    pending.body = body;
    pending.record_count = records.size();
    return pending;
}

bool ackMatches(const String& body, const PendingEnvelope& pending) {
    JsonDocument doc;
    if (deserializeJson(doc, body)) return false;
    if (doc["requestId"].as<String>() != pending.request_id) return false;
    JsonArray records = doc["records"].as<JsonArray>();
    if (records.isNull() || records.size() != pending.record_count) return false;
    for (JsonObject result : records) {
        if (result["status"].as<String>() != "accepted") return false;
    }
    return true;
}

bool configuredForTransport() {
    return String(XJ_WIFI_SSID).length() > 0 && String(XJ_API_BASE_URL).length() > 0 &&
           String(XJ_DEVICE_ID).length() > 0 && String(XJ_DEVICE_TOKEN).length() > 0 &&
           String(XJ_EXPERIMENT_SESSION_ID).length() > 0;
}

bool postPending(PendingEnvelope& pending) {
    if (!pending_store.healthy()) return false;
    if (pending.acknowledged) return pending_store.clear();
    if (!configuredForTransport() || pending.session_id != String(XJ_EXPERIMENT_SESSION_ID)) {
        Serial.println("[xinjian] transport paused: missing or changed session configuration");
        return false;
    }
    if (WiFi.status() != WL_CONNECTED) return false;
    const String endpoint(XJ_API_BASE_URL);
    const bool use_tls = endpoint.startsWith("https://");
    if (use_tls) {
        if (String(XJ_CA_CERT).isEmpty()) {
            Serial.println("[xinjian] HTTPS blocked: no CA certificate configured");
            return false;
        }
    } else if (endpoint.startsWith("http://")) {
#if !XJ_ALLOW_INSECURE_HTTP
        Serial.println("[xinjian] HTTP blocked: set XJ_ALLOW_INSECURE_HTTP only for an isolated test server");
        return false;
#endif
    } else {
        Serial.println("[xinjian] transport blocked: unsupported URL scheme");
        return false;
    }
    // Invalid configuration never consumes the persisted HTTP attempt budget.
    if (pending.attempts >= XJ_MAX_HTTP_ATTEMPTS) {
        Serial.println("[xinjian] transport paused: bounded retry budget exhausted; payload retained");
        return false;
    }
    ++pending.attempts;
    if (!pending_store.save(pending)) {
        Serial.println("[xinjian] storage fault: attempt not persisted; HTTP blocked");
        return false;
    }
    int http_code = -1;
    String response;
    if (use_tls) {
        WiFiClientSecure client;
        client.setCACert(XJ_CA_CERT);
        HTTPClient http;
        if (!http.begin(client, XJ_API_BASE_URL)) return false;
        http.setTimeout(XJ_HTTP_TIMEOUT_MS);
        http.addHeader("Content-Type", "application/json");
        http.addHeader("X-Device-ID", XJ_DEVICE_ID);
        http.addHeader("X-Device-Token", XJ_DEVICE_TOKEN);
        http.addHeader("X-Experiment-Session-ID", XJ_EXPERIMENT_SESSION_ID);
        http_code = http.POST(const_cast<uint8_t*>(reinterpret_cast<const uint8_t*>(pending.body.c_str())), pending.body.length());
        response = http.getString();
        http.end();
    } else {
#if XJ_ALLOW_INSECURE_HTTP
        WiFiClient client;
        HTTPClient http;
        if (!http.begin(client, XJ_API_BASE_URL)) return false;
        http.setTimeout(XJ_HTTP_TIMEOUT_MS);
        http.addHeader("Content-Type", "application/json");
        http.addHeader("X-Device-ID", XJ_DEVICE_ID);
        http.addHeader("X-Device-Token", XJ_DEVICE_TOKEN);
        http.addHeader("X-Experiment-Session-ID", XJ_EXPERIMENT_SESSION_ID);
        http_code = http.POST(const_cast<uint8_t*>(reinterpret_cast<const uint8_t*>(pending.body.c_str())), pending.body.length());
        response = http.getString();
        http.end();
#else
        Serial.println("[xinjian] HTTP blocked: set XJ_ALLOW_INSECURE_HTTP only for an isolated test server");
        return false;
#endif
    }
    if ((http_code == 200 || http_code == 201) && ackMatches(response, pending)) {
        Serial.printf("[xinjian] accepted request=%s records=%u\n", pending.request_id.c_str(), pending.record_count);
        pending.acknowledged = true;
        if (!pending_store.save(pending)) {
            Serial.println("[xinjian] storage fault: acknowledgement not persisted; paused");
            return false;
        }
        return pending_store.clear();
    }
    Serial.printf("[xinjian] response rejected status=%d; frozen payload retained\n", http_code);
    return false;
}

void connectWifi() {
    if (String(XJ_WIFI_SSID).isEmpty()) return;
    WiFi.mode(WIFI_STA);
    WiFi.begin(XJ_WIFI_SSID, XJ_WIFI_PASSWORD);
    const uint64_t started = monotonicMillis();
    while (WiFi.status() != WL_CONNECTED && monotonicMillis() - started < 10000UL) delay(100);
    if (WiFi.status() == WL_CONNECTED) {
        configTime(0, 0, "pool.ntp.org", "time.nist.gov");
        Serial.printf("[xinjian] wifi connected ip=%s\n", WiFi.localIP().toString().c_str());
    } else {
        Serial.println("[xinjian] wifi unavailable; configured transport retains one batch offline");
    }
}

void emitBatch(const Dht11Frame* frame, bool primed, bool include_reading,
               const String& measurement_occurred_at = String()) {
    if (configuredForTransport() && (!pending_store.healthy() || pending_store.hasPending())) {
        Serial.println("[xinjian] pending batch blocks a new sample until acknowledged");
        return;
    }
    ++sequence_no;
    PendingEnvelope pending = makeBatch(frame, primed, include_reading, measurement_occurred_at);
    Serial.printf("[xinjian] batch sequence=%llu records=%u\n",
                  static_cast<unsigned long long>(sequence_no), pending.record_count);
    Serial.println(pending.body);
    if (configuredForTransport()) {
        if (!pending_store.save(pending)) {
            Serial.println("[xinjian] storage fault: batch not persisted; upload and sampling paused");
            return;
        }
        postPending(pending);  // Offline returns without consuming an attempt.
    }
}

}  // namespace

void setup() {
    Serial.begin(115200);
    delay(100);
    boot_id = uuidV4();
    if (configuredForTransport() && !pending_store.begin()) {
        Serial.println("[xinjian] storage unavailable: transport and sampling paused; no auto-format");
    }
    connectWifi();
    // Also protect board-only resets while the sensor remains powered: the
    // previous boot may have triggered a conversion immediately before reset.
    delay(XJ_SAMPLE_INTERVAL_MS);
    Serial.printf("[xinjian] firmware=%s test_data=%s gpio=%u boot_id=%s\n",
                  XJ_FIRMWARE_VERSION, XJ_IS_TEST_DATA ? "true" : "false",
                  XJ_DHT11_DATA_GPIO, boot_id.c_str());
    PendingEnvelope retained;
    if (pending_store.load(retained)) {
        Serial.printf("[xinjian] retained request=%s session=%s attempts=%u\n",
                      retained.request_id.c_str(), retained.session_id.c_str(), retained.attempts);
        postPending(retained);
    }
    last_sample_ms = monotonicMillis() - XJ_SAMPLE_INTERVAL_MS;
    last_heartbeat_ms = monotonicMillis();
    last_retry_ms = monotonicMillis();
}

void loop() {
    const uint64_t now = monotonicMillis();
    // A retained batch invalidates conversion continuity even when its retry
    // succeeds and clears the cache within this same iteration.
    if (configuredForTransport() &&
        (!pending_store.healthy() || pending_store.hasPending())) {
        has_previous_conversion = false;
    }
    if (pending_store.hasPending() && pending_store.healthy() &&
        now - last_retry_ms >= 10000UL) {
        PendingEnvelope retry;
        last_retry_ms = now;
        if (pending_store.load(retry)) postPending(retry);
    }
    const bool sampling_blocked = configuredForTransport() &&
                                  (!pending_store.healthy() || pending_store.hasPending());
    if (sampling_blocked) has_previous_conversion = false;
    const uint64_t sample_now = monotonicMillis();  // HTTP above may have blocked.
    if (!sampling_blocked && sample_now - last_sample_ms >= XJ_SAMPLE_INTERVAL_MS) {
        const String trigger_iso = nowIso();
        Dht11Frame frame = readDht11(XJ_DHT11_DATA_GPIO);
        // Every request, including a failed read, advances the timing anchor.
        last_sample_ms = frame.trigger_started_ms;
        if (frame.status == Dht11ReadStatus::Ok) {
            if (has_previous_conversion) {
                emitBatch(&frame, false, true, last_successful_trigger_iso);
            } else {
                has_previous_conversion = true;
                Serial.println("[xinjian] first valid frame primed; no measurement published for unknown prior conversion");
                emitBatch(nullptr, true, false);
            }
            last_successful_trigger_ms = frame.trigger_started_ms;
            last_successful_trigger_iso = trigger_iso;
        } else {
            has_previous_conversion = false;
            emitBatch(&frame, false, false);
        }
    }
    if (now - last_heartbeat_ms >= XJ_HEARTBEAT_INTERVAL_MS) {
        last_heartbeat_ms = now;
        // Sampling batches already carry heartbeats; this marker is serial-only
        // when a pending request or missing hardware prevents a new batch.
        Serial.println("[xinjian] heartbeat: firmware alive");
    }
    delay(5);
}
