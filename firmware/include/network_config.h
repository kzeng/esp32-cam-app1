#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

struct NetworkConfig {
  uint32_t version = 1;
  char ssid[33] = {};
  char password[65] = {};
  char hostname[33] = {};
};

inline bool validNetworkHostname(const char *name) {
  const size_t n = strlen(name);
  if (!n || n > 32 || name[0] == '-' || name[n - 1] == '-') return false;
  for (size_t i = 0; i < n; ++i) {
    const char c = name[i];
    if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-')) return false;
  }
  return true;
}

inline bool validNetworkConfig(const NetworkConfig &c) {
  if (c.version != 1 || !memchr(c.ssid, 0, sizeof(c.ssid)) ||
      !memchr(c.password, 0, sizeof(c.password)) ||
      !memchr(c.hostname, 0, sizeof(c.hostname))) return false;
  const size_t n = strlen(c.password);
  if (n != 0 && (n < 8 || n > 63)) return false;
  return c.ssid[0] && validNetworkHostname(c.hostname);
}