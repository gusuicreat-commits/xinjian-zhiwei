#pragma once
#include "Arduino.h"
#include <algorithm>
#include <map>
#include <memory>
struct Disk {
    std::map<std::string, std::string> files;
    bool mount_ok=true, open_ok=true, rename_ok=true, remove_ok=true;
    size_t write_limit=1000000;
    int writes=0;
};
inline Disk disk;
class File {
    std::string path_;
    size_t cursor_=0;
    bool open_=false;
public:
    File()=default;
    File(const char* path, const char* mode) : path_(path) {
        if (!disk.open_ok) return;
        if (*mode=='w') disk.files[path_].clear();
        open_=disk.files.count(path_)>0;
    }
    explicit operator bool() const { return open_; }
    int read() { auto& data=disk.files[path_]; return cursor_<data.size() ? static_cast<uint8_t>(data[cursor_++]) : -1; }
    size_t readBytes(char* buffer, size_t n) { size_t i=0; int c; while (i<n && (c=read())>=0) buffer[i++]=c; return i; }
    size_t write(uint8_t c) { return write(&c,1); }
    size_t write(const uint8_t* p, size_t n) {
        ++disk.writes;
        auto& data=disk.files[path_];
        n=std::min(n, disk.write_limit>data.size()?disk.write_limit-data.size():0);
        data.append(reinterpret_cast<const char*>(p),n); return n;
    }
    size_t size() const { return disk.files.at(path_).size(); }
    void close() { open_=false; }
    void flush() {}
};
struct LittleFSMock {
    bool begin(bool format) { if (format) std::abort(); return disk.mount_ok; }
    bool exists(const char* path) { return disk.files.count(path)>0; }
    File open(const char* path, const char* mode) { return File(path,mode); }
    bool rename(const char* from, const char* to) {
        if (!disk.rename_ok || !exists(from)) return false;
        disk.files[to]=disk.files[from];disk.files.erase(from);return true;
    }
    bool remove(const char* path) { if (!disk.remove_ok) return false;disk.files.erase(path);return true; }
};
inline LittleFSMock LittleFS;
