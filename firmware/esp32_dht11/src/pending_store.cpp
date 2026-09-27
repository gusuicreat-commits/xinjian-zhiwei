#include "pending_store.h"

#include <ArduinoJson.h>
#include <LittleFS.h>

namespace {
constexpr char kPath[] = "/pending.json";
constexpr char kTmpPath[] = "/pending.json.tmp";

bool decode(File& file, PendingEnvelope& out) {
    JsonDocument doc;
    if (deserializeJson(doc, file)) return false;
    if (!doc["sessionId"].is<const char*>() || !doc["requestId"].is<const char*>() ||
        !doc["body"].is<const char*>() || !doc["recordCount"].is<uint16_t>() ||
        !doc["attempts"].is<uint8_t>() ||
        (!doc["acknowledged"].isNull() && !doc["acknowledged"].is<bool>())) return false;
    out.session_id = doc["sessionId"].as<const char*>();
    out.request_id = doc["requestId"].as<const char*>();
    out.body = doc["body"].as<const char*>();
    out.record_count = doc["recordCount"].as<uint16_t>();
    out.attempts = doc["attempts"].as<uint8_t>();
    out.acknowledged = doc["acknowledged"] | false;  // Older intact envelopes remain readable.
    if (out.session_id.isEmpty() || out.request_id.isEmpty() || out.body.isEmpty() ||
        out.record_count == 0) return false;
    JsonDocument body;
    if (deserializeJson(body, out.body)) return false;
    return body["requestId"].as<String>() == out.request_id &&
           body["records"].is<JsonArray>() &&
           body["records"].as<JsonArray>().size() == out.record_count;
}

bool sameEnvelope(const PendingEnvelope& a, const PendingEnvelope& b) {
    return a.session_id == b.session_id && a.request_id == b.request_id &&
           a.body == b.body && a.record_count == b.record_count &&
           a.attempts == b.attempts && a.acknowledged == b.acknowledged;
}
}

bool PendingStore::begin() {
    healthy_ = false;
    // Never auto-format: mount errors must not erase retained data.
    if (!LittleFS.begin(false)) return false;
    pending_ = LittleFS.exists(kPath);
    // An interrupted first save is ambiguous. Retain it for explicit recovery.
    if (!pending_ && LittleFS.exists(kTmpPath)) return false;
    healthy_ = true;
    PendingEnvelope retained;
    if (pending_ && !load(retained)) return false;
    return true;
}

bool PendingStore::load(PendingEnvelope& out) {
    if (!healthy_ || !pending_) return false;
    File file = LittleFS.open(kPath, "r");
    const bool valid = file && decode(file, out);
    file.close();
    if (!valid) healthy_ = false;
    return valid;
}

bool PendingStore::save(const PendingEnvelope& value) {
    if (!healthy_) return false;
    JsonDocument doc;
    doc["sessionId"] = value.session_id;
    doc["requestId"] = value.request_id;
    doc["recordCount"] = value.record_count;
    doc["attempts"] = value.attempts;
    doc["acknowledged"] = value.acknowledged;
    doc["body"] = value.body;
    File file = LittleFS.open(kTmpPath, "w");
    if (!file) { healthy_ = false; return false; }
    const size_t expected = measureJson(doc);
    const size_t written = serializeJson(doc, file);
    file.flush();
    file.close();
    File check = LittleFS.open(kTmpPath, "r");
    PendingEnvelope verified;
    const bool valid = written == expected && check && check.size() == expected &&
                       decode(check, verified) && sameEnvelope(value, verified);
    check.close();
    if (!valid || !LittleFS.rename(kTmpPath, kPath)) {
        healthy_ = false;
        return false;  // Keep both old and temporary files; no send follows.
    }
    pending_ = true;
    return true;
}

bool PendingStore::clear() {
    if (!healthy_) return false;
    // Callers persist acknowledged=true first. A failed cleanup is retried
    // without another HTTP request, including after restart.
    if (LittleFS.exists(kTmpPath) && !LittleFS.remove(kTmpPath)) return false;
    if (LittleFS.exists(kPath) && !LittleFS.remove(kPath)) return false;
    pending_ = false;
    return true;
}
