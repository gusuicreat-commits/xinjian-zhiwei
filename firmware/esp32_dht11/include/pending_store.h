#pragma once

#include <Arduino.h>

struct PendingEnvelope {
    String session_id;
    String request_id;
    String body;
    uint16_t record_count = 0;
    uint8_t attempts = 0;
};

class PendingStore {
public:
    bool begin();
    bool load(PendingEnvelope& out);
    bool save(const PendingEnvelope& value);
    bool clear();
    bool hasPending() const { return pending_; }

private:
    bool pending_ = false;
};
