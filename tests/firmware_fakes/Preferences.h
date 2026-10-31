#pragma once
#include "Arduino.h"
#include <map>
#include <vector>
namespace fake {
using Bytes = std::vector<uint8_t>;
inline std::map<std::string, std::map<std::string, Bytes>> nvs;
inline bool failOpen = false, failString = false, failBytes = false, failSelected = false, corruptRead = false;
inline std::vector<std::string> writes;
}
class Preferences {
  std::string space;
 public:
  bool begin(const char *name, bool) { space = name; return !fake::failOpen; }
  size_t getBytesLength(const char *key) { return fake::nvs[space][key].size(); }
  size_t getBytes(const char *key, void *out, size_t capacity) {
    const auto &data = fake::nvs[space][key];
    if (data.size() > capacity) return 0;
    std::memcpy(out, data.data(), data.size());
    if (fake::corruptRead && !data.empty()) static_cast<uint8_t *>(out)[0] ^= 1;
    return data.size();
  }
  size_t putBytes(const char *key, const void *data, size_t size) {
    fake::writes.push_back(space + "/" + key);
    if (fake::failBytes) return 0;
    const auto *bytes = static_cast<const uint8_t *>(data);
    fake::nvs[space][key] = fake::Bytes(bytes, bytes + size); return size;
  }
  uint8_t getUChar(const char *key, uint8_t fallback) {
    const auto &data = fake::nvs[space][key]; return data.empty() ? fallback : data[0];
  }
  size_t putUChar(const char *key, uint8_t value) {
    if (fake::failSelected) return 0;
    return putBytes(key, &value, 1);
  }
  String getString(const char *key, const char *fallback) {
    const auto &data = fake::nvs[space][key];
    return data.empty() ? String(fallback) : String(std::string(data.begin(), data.end()));
  }
  size_t putString(const char *key, const String &value) {
    return fake::failString ? 0 : putBytes(key, value.c_str(), value.length());
  }
  bool remove(const char *key) { fake::writes.push_back(space + "/" + key); return fake::nvs[space].erase(key) != 0; }
};
