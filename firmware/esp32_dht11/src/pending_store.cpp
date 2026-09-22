#include "pending_store.h"

#include <ArduinoJson.h>
#include <LittleFS.h>

namespace {
constexpr char kPath[] = "/pending.json";
constexpr char kTmpPath[] = "/pending.json.tmp";
}

bool PendingStore::begin() {
    // Never auto-format here: a mount error must not erase a frozen batch.
    if (!LittleFS.begin(false)) return false;
    pending_ = LittleFS.exists(kPath);
    return true;
}

bool PendingStore::load(PendingEnvelope& out) {
    if (!pending_) return false;
    File file = LittleFS.open(kPath, "r");
    if (!file) return false;
    JsonDocument doc;
    const DeserializationError error = deserializeJson(doc, file);
    file.close();
    if (error) return false;
    out.session_id = doc["sessionId"].as<const char*>();
    out.request_id = doc["requestId"].as<const char*>();
    out.body = doc["body"].as<const char*>();
    out.record_count = doc["recordCount"] | 0;
    out.attempts = doc["attempts"] | 0;
    return !out.session_id.isEmpty() && !out.request_id.isEmpty() && !out.body.isEmpty();
}

bool PendingStore::save(const PendingEnvelope& value) {
    JsonDocument doc;
    doc["sessionId"] = value.session_id;
    doc["requestId"] = value.request_id;
    doc["recordCount"] = value.record_count;
    doc["attempts"] = value.attempts;
    doc["body"] = value.body;
    File file = LittleFS.open(kTmpPath, "w");
    if (!file) return false;
    const size_t written = serializeJson(doc, file);
    file.close();
    if (written == 0 || !LittleFS.rename(kTmpPath, kPath)) {
        LittleFS.remove(kTmpPath);
        return false;
    }
    pending_ = true;
    return true;
}

bool PendingStore::clear() {
    if (LittleFS.exists(kPath) && !LittleFS.remove(kPath)) return false;
    pending_ = false;
    return true;
}
