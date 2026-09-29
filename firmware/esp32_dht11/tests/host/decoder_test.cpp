#include <cmath>
#include <iostream>
#include "../../src/main.cpp"

// Independent expectations: Aosong V1.3_20170331 PDF pp.3-5.
// Compile the production decoder, not a test copy of its algorithm.
int main() {
    int failures = 0;
    auto check = [&](bool ok, const char* label) {
        if (!ok) { ++failures; std::cerr << "FAIL: " << label << '\n'; }
    };
    const uint8_t negative[] = {0x35, 0x00, 0x0a, 0x81, 0xc0};
    auto frame = decodeDht11Frame(negative);
    check(frame.status == Dht11ReadStatus::Ok && std::fabs(frame.temperature_c + 10.1f) < 0.001f,
          "manual -10.1 C frame preserves sign");
    JsonDocument batch;
    deserializeJson(batch, makeBatch(&frame, true, true).body);
    bool found = false;
    for (JsonObject record : batch["records"].as<JsonArray>()) {
        if (record["payload"]["metric_key"] == "temperature") {
            found = true;
            check(std::fabs(record["payload"]["value"].as<float>() + 10.1f) < 0.001f,
                  "production batch preserves negative temperature");
        }
    }
    check(found, "production batch contains temperature");
    struct Sample { uint8_t raw[5]; float expected; Dht11ReadStatus status; };
    const Sample samples[] = {
        {{0x35,0,0x18,4,0x51},24.4f,Dht11ReadStatus::Ok},
        {{53,0,0,0,53},0,Dht11ReadStatus::Ok},
        {{53,0,0,0x81,182},-0.1f,Dht11ReadStatus::Ok},
        {{53,0,0,1,54},0.1f,Dht11ReadStatus::Ok},
        {{5,0,20,128,153},-20,Dht11ReadStatus::Ok},
        {{95,0,60,0,155},60,Dht11ReadStatus::Ok},
        {{53,0,24,4,0x49},0,Dht11ReadStatus::Checksum},
        {{53,0,24,0x14,97},0,Dht11ReadStatus::Protocol},
        {{53,0,24,10,87},0,Dht11ReadStatus::Protocol},
        {{53,1,24,0,78},0,Dht11ReadStatus::Protocol},
        {{53,0,21,128,202},0,Dht11ReadStatus::Range},
        {{53,0,61,0,114},0,Dht11ReadStatus::Range},
        {{4,0,24,0,28},0,Dht11ReadStatus::Range},
        {{96,0,24,0,120},0,Dht11ReadStatus::Range},
    };
    for (const auto& sample : samples) {
        const auto result = decodeDht11Frame(sample.raw);
        check(result.status == sample.status, "manual format/checksum/range status");
        if (sample.status == Dht11ReadStatus::Ok)
            check(std::fabs(result.temperature_c - sample.expected) < 0.001f, "decoded temperature");
    }
    std::cout << "decoder/manual vectors and production serialization failures=" << failures << '\n';
    return failures ? 1 : 0;
}
