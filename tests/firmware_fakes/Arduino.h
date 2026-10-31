#pragma once
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <cstdarg>
#include <string>
#include <algorithm>

#define F(text) text
class String {
 public:
  std::string value;
  String() = default;
  String(const char *s) : value(s) {}
  String(std::string s) : value(std::move(s)) {}
  const char *c_str() const { return value.c_str(); }
  size_t length() const { return value.size(); }
  void reserve(size_t n) { value.reserve(n); }
  void replace(const char *from, const String &to) {
    size_t pos = 0;
    while ((pos = value.find(from, pos)) != std::string::npos) {
      value.replace(pos, strlen(from), to.value); pos += to.length();
    }
  }
  String &operator+=(const String &s) { value += s.value; return *this; }
  String &operator+=(char c) { value += c; return *this; }
  friend String operator+(String a, const String &b) { return a += b; }
  friend bool operator==(const String &a, const String &b) { return a.value == b.value; }
  friend bool operator!=(const String &a, const String &b) { return !(a == b); }
};
inline size_t strlcpy(char *dst, const char *src, size_t size) {
  const size_t n = std::strlen(src);
  if (size) { const size_t count = std::min(n, size - 1); std::memcpy(dst, src, count); dst[count] = 0; }
  return n;
}
namespace fake { inline uint32_t now = 100; }
inline uint32_t millis() { return fake::now; }
struct FakeSerial {
  std::string input, output;
  size_t available() const { return input.size(); }
  char read() { const char c = input.front(); input.erase(0, 1); return c; }
  void println(const char *s) { output += s; output += '\n'; }
  void printf(const char *format, ...) {
    char buffer[2048]; va_list args; va_start(args, format);
    std::vsnprintf(buffer, sizeof(buffer), format, args); va_end(args); output += buffer;
  }
};
inline FakeSerial Serial;
struct FakeESP { uint64_t getEfuseMac() const { return 0x123456789abcULL; } };
inline FakeESP ESP;
