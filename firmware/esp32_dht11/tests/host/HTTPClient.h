#pragma once
#include "Arduino.h"
#include "LittleFS.h"
inline int sends=0, http_status=201;
inline bool valid_ack=true, fail_ack_save=false;
inline String sent_body;
struct HTTPClient {
    template<class T> bool begin(T&, const char*) {return true;}
    void setTimeout(int) {}
    void addHeader(const char*,const char*) {}
    int POST(uint8_t* body,size_t n){++sends;if(fail_ack_save) disk.write_limit=12;sent_body=std::string(reinterpret_cast<char*>(body),n);return http_status;}
    String getString(){
        JsonDocument payload, reply;
        deserializeJson(payload,sent_body);
        reply["requestId"]=valid_ack?payload["requestId"].as<String>():String("wrong-request");
        for (JsonVariant record:payload["records"].as<JsonArray>()) {
            (void)record;
            reply["records"].add<JsonObject>()["status"]="accepted";
        }
        String result;serializeJson(reply,result);return result;
    }
    void end(){}
};
