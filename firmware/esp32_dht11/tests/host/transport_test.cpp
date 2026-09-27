#include <cassert>
#include <iostream>
#ifndef SERIAL_ONLY
#define XJ_WIFI_SSID "test-only"
#define XJ_API_BASE_URL "https://test.invalid/api/v1/device/ingest"
#define XJ_DEVICE_ID "test-device"
#define XJ_DEVICE_TOKEN "test-token"
#define XJ_EXPERIMENT_SESSION_ID "test-session"
#define XJ_CA_CERT "test-ca"
#endif
#include "../../src/main.cpp"
int sensor_reads=0;
Dht11Frame readDht11(uint8_t){++sensor_reads; Dht11Frame f;f.status=Dht11ReadStatus::Ok;return f;}
const char* dht11StatusText(Dht11ReadStatus){return "test read failure";}
void reset(){disk=Disk{};pending_store=PendingStore{};sends=0;http_status=201;valid_ack=true;fail_ack_save=false;WiFi.state=WL_CONNECTED;has_previous_conversion=false;assert(pending_store.begin());}
PendingEnvelope retained(){PendingEnvelope p;assert(pending_store.load(p));return p;}
int main(){
#ifdef SERIAL_ONLY
    disk.mount_ok=false;setup();emitBatch(nullptr,false,false);
    assert(sends==0 && disk.writes==0);std::cout<<"unconfigured serial-only mode passed\n";return 0;
#else
    for (uint64_t value : { (1ULL << 31) - 1, (1ULL << 31) + 1, (1ULL << 32) - 1, (1ULL << 32) + 1 }) {
        host_ms=value; JsonDocument clock_doc; addCommon(clock_doc);
        assert(clock_doc["uptimeMs"].as<uint64_t>()==value);
        Dht11Frame sample;sample.status=Dht11ReadStatus::Ok;
        sample.read_finished_ms=value;last_successful_trigger_ms=value-5000;
        JsonDocument batch;deserializeJson(batch,makeBatch(&sample,true,true).body);
        assert(batch["records"][0]["payload"]["metadata"]["read_completed_uptime_ms"].as<uint64_t>()==value);
        assert(batch["records"][0]["payload"]["metadata"]["conversion_triggered_uptime_ms"].as<uint64_t>()==value-5000);
    }
    host_ms=0;std::cout<<"64-bit clock and sample metadata across signed/unsigned 32-bit boundaries passed\n";
    reset();WiFi.state=0;emitBatch(nullptr,false,false);
    auto p=retained();assert(p.attempts==0 && sends==0);
    auto frozen=p.body;emitBatch(nullptr,false,false);assert(retained().body==frozen);
    int before=sensor_reads;has_previous_conversion=true;host_ms+=XJ_SAMPLE_INTERVAL_MS;loop();
    assert(sensor_reads==before && !has_previous_conversion);
    pending_store=PendingStore{};assert(pending_store.begin());p=retained();
    WiFi.state=WL_CONNECTED;assert(postPending(p));assert(sent_body==frozen && sends==1 && !pending_store.hasPending());
    std::cout<<"offline retention, restart, frozen identity, bounded sampling passed\n";

    reset();disk.mount_ok=false;pending_store=PendingStore{};assert(!pending_store.begin());
    emitBatch(nullptr,false,false);assert(sends==0 && disk.writes==0);
    reset();disk.open_ok=false;emitBatch(nullptr,false,false);assert(sends==0 && !pending_store.healthy());
    reset();disk.write_limit=12;emitBatch(nullptr,false,false);assert(sends==0 && !pending_store.healthy());
    assert(disk.files.count("/pending.json.tmp"));pending_store=PendingStore{};assert(!pending_store.begin());
    std::cout<<"mount, open, partial write and interrupted first save failures blocked\n";

    reset();WiFi.state=0;emitBatch(nullptr,false,false);p=retained();auto original=disk.files.at("/pending.json");
    disk.rename_ok=false;WiFi.state=WL_CONNECTED;assert(!postPending(p));
    assert(sends==0 && disk.files.at("/pending.json")==original);
    reset();WiFi.state=0;emitBatch(nullptr,false,false);p=retained();disk.write_limit=12;
    WiFi.state=WL_CONNECTED;assert(!postPending(p));assert(sends==0);
    std::cout<<"attempt persistence failure prevents HTTP and preserves old batch\n";

    reset();http_status=503;emitBatch(nullptr,false,false);
    for(int i=0;i<5;++i){pending_store=PendingStore{};assert(pending_store.begin());p=retained();postPending(p);}
    assert(sends==XJ_MAX_HTTP_ATTEMPTS && retained().attempts==XJ_MAX_HTTP_ATTEMPTS);
    std::cout<<"retry budget survives repeated restart\n";

    reset();disk.remove_ok=false;emitBatch(nullptr,false,false);assert(sends==1 && retained().acknowledged);
    pending_store=PendingStore{};assert(pending_store.begin());p=retained();WiFi.state=0;
    assert(!postPending(p));assert(sends==1);disk.remove_ok=true;
    assert(postPending(p));assert(sends==1 && !pending_store.hasPending());
    std::cout<<"acknowledged cleanup retries without HTTP, including offline restart\n";

    reset();fail_ack_save=true;emitBatch(nullptr,false,false);
    assert(sends==1 && !pending_store.healthy());
    emitBatch(nullptr,false,false);assert(sends==1);
    fail_ack_save=false;disk.write_limit=1000000;
    pending_store=PendingStore{};assert(pending_store.begin());p=retained();
    assert(p.attempts==1 && !p.acknowledged);auto acknowledged_body=p.body;
    assert(postPending(p));assert(sends==2 && sent_body==acknowledged_body);
    std::cout<<"unpersisted acknowledgement pauses; restart replays original identity within budget\n";

    reset();WiFi.state=0;emitBatch(nullptr,false,false);
    JsonDocument old;deserializeJson(old,disk.files.at("/pending.json"));
    old.remove("acknowledged");disk.files["/pending.json"].clear();
    serializeJson(old,disk.files["/pending.json"]);
    pending_store=PendingStore{};assert(pending_store.begin());assert(!retained().acknowledged);
    old.remove("attempts");disk.files["/pending.json"].clear();serializeJson(old,disk.files["/pending.json"]);
    pending_store=PendingStore{};assert(!pending_store.begin());
    std::cout<<"intact legacy cache accepted; missing retry count cannot reset budget\n";

    reset();valid_ack=false;emitBatch(nullptr,false,false);assert(!retained().acknowledged);
    reset();WiFi.state=0;emitBatch(nullptr,false,false);p=retained();p.session_id="old-session";assert(pending_store.save(p));
    WiFi.state=WL_CONNECTED;assert(!postPending(p));assert(sends==0 && retained().session_id=="old-session");
    reset();disk.files["/pending.json"]="{broken";pending_store=PendingStore{};assert(!pending_store.begin());
    emitBatch(nullptr,false,false);assert(sends==0);
    std::cout<<"invalid receipt, changed session and corrupt store blocked\n";
#endif
}
