#include <cassert>
#include <iostream>
#include <vector>

const char* test_url = "https://test.invalid/api/v1/device/ingest";
const char* test_ca = "test-ca";
const char* test_wifi = "test-only";
#define XJ_WIFI_SSID test_wifi
#define XJ_API_BASE_URL test_url
#define XJ_DEVICE_ID "test-device"
#define XJ_DEVICE_TOKEN "test-token"
#define XJ_EXPERIMENT_SESSION_ID "test-session"
#define XJ_CA_CERT test_ca
#include "../../src/main.cpp"

std::vector<uint64_t> triggers;
Dht11ReadStatus sensor_status = Dht11ReadStatus::Ok;
Dht11Frame readDht11(uint8_t) {
    Dht11Frame frame;
    frame.trigger_started_ms = host_ms;
    triggers.push_back(host_ms);
    delay(20);  // Sensor transaction itself takes time.
    frame.read_finished_ms = host_ms;
    frame.status = sensor_status;
    return frame;
}
const char* dht11StatusText(Dht11ReadStatus) { return "test failure"; }

void reset() {
    disk = Disk{}; pending_store = PendingStore{};
    assert(pending_store.begin());
    host_ms = 0; last_sample_ms = 0; last_retry_ms = 0; last_heartbeat_ms = 0;
    last_successful_trigger_ms = 0; last_successful_trigger_iso = String();
    has_previous_conversion = false; sequence_no = 0; triggers.clear();
    sensor_status = Dht11ReadStatus::Ok;
    sends = 0; http_status = 201; valid_ack = true; fail_ack_save = false;
    response_delay_ms = 0; http_begins = 0; ca_calls = 0; insecure_calls = 0;
    WiFi.state = WL_CONNECTED;
}

void check_intervals() {
    assert(!triggers.empty()); // A stopped sampler must not pass the test.
    for (size_t i = 1; i < triggers.size(); ++i) {
        std::cout << "gap_ms=" << triggers[i] - triggers[i-1] << std::endl;
        assert(triggers[i] - triggers[i-1] >= 3000);
    }
}

void boundary(uint64_t base, Dht11ReadStatus status) {
    reset(); host_ms = base; last_sample_ms = base; sensor_status = status;
    host_ms = base + 2999; loop(); assert(triggers.empty());
    host_ms = base + 3000; loop(); assert(triggers.size() == 1);
    host_ms = base + 5999; loop(); assert(triggers.size() == 1);
    host_ms = base + 6000; loop(); assert(triggers.size() == 2);
    check_intervals();
}

void retry(uint64_t latency, bool was_primed) {
    reset(); WiFi.state = 0; emitBatch(nullptr, false, false);
    has_previous_conversion = was_primed;
    WiFi.state = WL_CONNECTED; host_ms = 11000; response_delay_ms = latency;
    loop(); loop();
    assert(triggers.size() == 1);
    assert(triggers.front() == 11000 + latency);
    JsonDocument first; deserializeJson(first, sent_body);
    assert(first["records"].size() == 1);
    assert(first["records"][0]["payload"]["metadata"]["dht11_sample_primed"].as<bool>());
    host_ms = triggers.front() + 3000; loop();
    assert(triggers.size() == 2); check_intervals();
    JsonDocument reading; deserializeJson(reading, sent_body);
    assert(reading["records"].size() == 3);
    assert(reading["records"][0]["payload"]["metadata"]["conversion_triggered_uptime_ms"].as<uint64_t>() == triggers.front());
}

void policy(const char* scenario) {
    reset(); bool allowed = false, uses_tls = false;
    if (String(scenario) == "https-ca") { allowed = true; uses_tls = true; }
    else if (String(scenario) == "https-empty") { test_ca = ""; }
    else if (String(scenario) == "http") {
        test_url = "http://test.invalid/api/v1/device/ingest";
        allowed = XJ_ALLOW_INSECURE_HTTP;
    } else { test_url = "ftp://test.invalid/ingest"; }
    auto pending = makeBatch(nullptr, false, false);
    assert(pending_store.save(pending));
    const String frozen = pending.body, id = pending.request_id;
    assert(postPending(pending) == allowed);
    assert(insecure_calls == 0);
    assert(ca_calls == unsigned(uses_tls));
    assert(http_begins == unsigned(allowed));
    assert(sends == int(allowed));
    assert(pending.attempts == unsigned(allowed));
    if (!allowed) {
        PendingEnvelope retained; assert(pending_store.load(retained));
        assert(retained.body == frozen && retained.request_id == id && retained.attempts == 0);
        retained.acknowledged = true; assert(pending_store.save(retained));
        assert(postPending(retained)); // Confirmed cleanup still works with bad config.
        assert(!pending_store.hasPending() && sends == 0);
    }
}

int main(int argc, char** argv) {
    assert(argc == 2); String scenario = argv[1];
    if (scenario == "boundary") {
        for (auto base : {0ULL, (1ULL<<31)-3001, (1ULL<<32)-3001})
            for (auto status : {Dht11ReadStatus::Ok, Dht11ReadStatus::Timeout,
                                Dht11ReadStatus::Checksum, Dht11ReadStatus::Range,
                                Dht11ReadStatus::Protocol}) boundary(base, status);
    } else if (scenario == "serial-boundary") {
        test_wifi = ""; boundary(0, Dht11ReadStatus::Ok); assert(sends == 0);
    } else if (scenario == "retry-fast") retry(0, false);
    else if (scenario == "retry-slow") retry(4000, false);
    else if (scenario == "retry-prime-fast") retry(0, true);
    else if (scenario == "retry-prime") retry(4000, true);
    else if (scenario == "initial-slow") {
        reset(); host_ms = 3000; response_delay_ms = 5000; loop(); loop();
        assert(triggers.size() == 2); check_intervals();
        const auto second = triggers.back(); loop(); assert(triggers.size() == 2);
        host_ms = second + 3000; loop(); assert(triggers.size() == 3); check_intervals();
    } else if (scenario == "retry-failure") {
        reset(); WiFi.state = 0; emitBatch(nullptr, false, false);
        WiFi.state = WL_CONNECTED; http_status = -1;
        for (int i=0; i<3; ++i) { host_ms += 10000; response_delay_ms = 5000; loop(); }
        assert(triggers.empty() && sends == 3 && pending_store.hasPending());
        http_status = 201; host_ms += 10000; loop(); assert(triggers.empty() && sends == 3);
    } else if (scenario == "startup") {
        reset(); setup(); loop();
        assert(triggers.size() == 1 && triggers[0] >= 3000);
        check_intervals(); // Each new boot, including board-only reset, waits independently.
        test_wifi = ""; reset(); setup(); loop();
        assert(triggers.size() == 1 && triggers[0] >= 3000 && sends == 0);
    } else if (scenario == "failure-recovery") {
        reset(); host_ms = 3000; http_status = -1; response_delay_ms = 5000;
        loop(); assert(triggers.size() == 1 && pending_store.hasPending());
        loop(); assert(triggers.size() == 1);
        http_status = 201; host_ms = 20000; response_delay_ms = 4000;
        loop(); loop(); assert(triggers.size() == 2); check_intervals();
        JsonDocument first; deserializeJson(first, sent_body);
        assert(first["records"].size() == 1);
        host_ms = triggers.back() + 3000; loop();
        assert(triggers.size() == 3); check_intervals();
    } else policy(argv[1]);
    std::cout << "passed: " << scenario << " HTTP-enabled=" << XJ_ALLOW_INSECURE_HTTP << std::endl;
}
