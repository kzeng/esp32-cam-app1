#pragma once
#include "Arduino.h"
#include <array>
#include <vector>
class IPAddress {
 public:
  std::array<uint8_t, 4> bytes{};
  IPAddress() = default;
  IPAddress(uint8_t a, uint8_t b, uint8_t c, uint8_t d) : bytes{{a,b,c,d}} {}
  bool operator==(const IPAddress &other) const { return bytes == other.bytes; }
  bool operator!=(const IPAddress &other) const { return !(*this == other); }
  String toString() const {
    char text[16]; std::snprintf(text, sizeof(text), "%u.%u.%u.%u", bytes[0], bytes[1], bytes[2], bytes[3]);
    return text;
  }
};
enum { WIFI_STA = 1, WIFI_AP_STA = 3, WL_DISCONNECTED = 6, WL_CONNECTED = 3,
       WIFI_SCAN_RUNNING = -1, WIFI_SCAN_FAILED = -2, WIFI_AUTH_OPEN = 0 };
struct FakeWiFi {
  bool persistentEnabled = true, autoReconnect = true, ap = false, apWorks = true;
  int currentMode = 0, connection = WL_DISCONNECTED;
  String hostname, apName, apPassword;
  IPAddress ip;
  std::vector<std::pair<std::string, std::string>> attempts;
  struct Network { String name; int rssi; int security; };
  std::vector<Network> networks;
  int scanStatus = WIFI_SCAN_RUNNING, scans = 0;
  int scanNetworks(bool async, bool = false, bool = false, uint32_t = 300) { if (async) ++scans; return WIFI_SCAN_RUNNING; }
  int scanComplete() { return scanStatus; }
  void scanDelete() {}
  String SSID(int i) { return networks.at(i).name; }
  int RSSI(int i) { return networks.at(i).rssi; }
  int encryptionType(int i) { return networks.at(i).security; }
  void persistent(bool enabled) { persistentEnabled = enabled; }
  bool mode(int value) { currentMode = value; return true; }
  void setSleep(bool) {}
  void setAutoReconnect(bool value) { autoReconnect = value; }
  void disconnect(bool, bool) { connection = WL_DISCONNECTED; ip = IPAddress(); }
  void setHostname(const char *name) { hostname = name; }
  void begin(const char *ssid, const char *password) { attempts.emplace_back(ssid, password); }
  int status() const { return connection; }
  IPAddress localIP() const { return ip; }
  IPAddress softAPIP() const { return IPAddress(192,168,4,1); }
  bool softAPConfig(IPAddress, IPAddress, IPAddress) { return apWorks; }
  bool softAP(const char *name, const char *password, int, bool, int) {
    apName = name; apPassword = password; ap = apWorks; return apWorks;
  }
  void softAPdisconnect(bool) { ap = false; }
};
inline FakeWiFi WiFi;
inline void *esp_netif_get_handle_from_ifkey(const char *) { return nullptr; }
inline int esp_netif_set_hostname(void *, const char *) { return 0; }
