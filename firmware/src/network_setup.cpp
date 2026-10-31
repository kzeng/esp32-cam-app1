#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h>
#include <esp_system.h>
#include <esp_wifi.h>
#include <atomic>
#include <algorithm>
#include <vector>
#include "setup_page.h"
#include "network_config.h"
#include "network_setup.h"

namespace {
Preferences storage;
const IPAddress portalAddress(192, 168, 4, 1);
WebServer portal(portalAddress, 8081);  // Bind only the AP, before HTTP parsing.
NetworkConfig saved, candidate;
bool hasSaved = false, active = false, testing = false, queued = false;
bool ready = false, serialOverflow = false;
uint8_t selectedSlot = 0;
uint32_t openedAt = 0, attemptedAt = 0, connectedAt = 0, lastReconnect = 0;
uint32_t completedAt = 0;
bool scanPending = false;
uint32_t scannedAt = 0;
String scanResult = "{\"scanning\":false,\"networks\":[]}";
std::atomic<bool> requested{false};
String apName, apPassword, token, serialLine;
const char *result = "idle";
char defaultName[33] = {};
constexpr uint32_t WINDOW_MS = 600000, CONNECT_MS = 30000, STABLE_MS = 3000;

String jsonString(const String &value) {
  String out = "\"";
  for (size_t i = 0; i < value.length(); ++i) {
    const unsigned char c = value.c_str()[i];
    if (c == '"' || c == '\\') { out += '\\'; out += static_cast<char>(c); }
    else if (c < 32) {
      char escape[7]; snprintf(escape, sizeof(escape), "\\u%04x", c); out += escape;
    } else out += static_cast<char>(c);
  }
  out += '"';
  return out;
}

void finishScan() {
  if (!scanPending) return;
  const int count = WiFi.scanComplete();
  if (count == WIFI_SCAN_RUNNING) return;
  Serial.printf("Wi-Fi scan completed: %d access points.\n", count);
  scanPending = false;
  if (count < 0) {
    scanResult = "{\"scanning\":false,\"networks\":[],\"error\":\"扫描失败，请重试\"}";
  } else {
    std::vector<int> indexes;
    for (int i = 0; i < count; ++i) if (WiFi.SSID(i).length()) indexes.push_back(i);
    std::sort(indexes.begin(), indexes.end(), [](int a, int b) { return WiFi.RSSI(a) > WiFi.RSSI(b); });
    scanResult = "{\"scanning\":false,\"networks\":[";
    std::vector<String> seen;
    for (int i : indexes) {
      const String name = WiFi.SSID(i);
      if (std::find(seen.begin(), seen.end(), name) != seen.end()) continue;
      if (!seen.empty()) scanResult += ',';
      seen.push_back(name);
      char details[64];
      snprintf(details, sizeof(details), ",\"rssi\":%d,\"secure\":%s}", WiFi.RSSI(i),
               WiFi.encryptionType(i) == WIFI_AUTH_OPEN ? "false" : "true");
      scanResult += "{\"ssid\":"; scanResult += jsonString(name); scanResult += details;
      if (seen.size() >= 30) break;
    }
    scanResult += "]}";
  }
  WiFi.scanDelete();
}

bool beginScan() {
  if (scanPending) return true;
  scannedAt = millis();
  scanPending = true;
  // In AP+STA mode the radio must return to the AP channel between channels.
  // Arduino derives its async deadline from this dwell value (20 * dwell).
  const int status = WiFi.scanNetworks(true, false, false, 1000);
  Serial.printf("Wi-Fi scan started: status=%d, station=%d.\n", status, WiFi.status());
  if (status == WIFI_SCAN_FAILED) {
    scanPending = false;
    scanResult = "{\"scanning\":false,\"networks\":[],\"error\":\"扫描启动失败，请稍后重试\"}";
    return false;
  }
  return true;
}

String randomHex(size_t bytes) {
  String value;
  value.reserve(bytes * 2);
  for (size_t i = 0; i < bytes; ++i) {
    char pair[3];
    snprintf(pair, sizeof(pair), "%02x", static_cast<unsigned>(esp_random() & 255));
    value += pair;
  }
  return value;
}

void connectSaved() {
  WiFi.setAutoReconnect(false);
  WiFi.disconnect(false, false);
  WiFi.setHostname(hasSaved ? saved.hostname : defaultName);
  esp_netif_set_hostname(esp_netif_get_handle_from_ifkey("WIFI_STA_DEF"),
                        hasSaved ? saved.hostname : defaultName);
  if (hasSaved) WiFi.begin(saved.ssid, saved.password);
  lastReconnect = millis();
}

bool apRequest(bool mutation = false) {
  portal.sendHeader("Cache-Control", "no-store");
  portal.sendHeader("X-Content-Type-Options", "nosniff");
  portal.sendHeader("X-Frame-Options", "DENY");
  if (!active || portal.client().localIP() != WiFi.softAPIP()) {
    portal.send(403, "text/plain", "Setup is available only through the device hotspot.");
    return false;
  }
  if (mutation && portal.arg("token") != token) {
    portal.send(403, "text/plain", "Invalid setup token.");
    return false;
  }
  return true;
}

void closePortal() {
  if (scanPending) esp_wifi_scan_stop();
  WiFi.scanDelete();
  scanPending = false;
  portal.stop();
  active = testing = queued = false;
  completedAt = 0;
  token = "";
  memset(&candidate, 0, sizeof(candidate));
  WiFi.softAPdisconnect(true);
  WiFi.mode(WIFI_STA);
  connectSaved();
  Serial.println("Setup hotspot closed; returning to saved network.");
}

void openPortal() {
  if (active) return;
  WiFi.mode(WIFI_AP_STA);
  token = randomHex(16);
  if (!WiFi.softAPConfig(portalAddress, portalAddress, IPAddress(255, 255, 255, 0)) ||
      !WiFi.softAP(apName.c_str(), apPassword.c_str(), 1, false, 1)) {
    Serial.println("Setup hotspot failed; use wifi-setup to retry.");
    WiFi.mode(WIFI_STA);
    connectSaved();
    return;
  }
  active = true;
  testing = queued = false;
  completedAt = 0;
  openedAt = millis();
  result = "idle";
  scannedAt = 0;
  portal.begin();
  Serial.printf("Setup hotspot: %s; open http://%s:8081 (10 minute window).\n",
                apName.c_str(), WiFi.softAPIP().toString().c_str());
  Serial.println("Use local serial command wifi-info to see the hotspot password.");
}

void printInfo() {
  // Only this explicit physical-console command reveals the setup password.
  Serial.printf("Setup SSID: %s\nSetup password: %s\n", apName.c_str(), apPassword.c_str());
}

bool validSetupPassword(const char *password) {
  const size_t n = strlen(password);
  if (n < 8 || n > 63) return false;
  for (size_t i = 0; i < n; ++i)
    if (password[i] < 32 || password[i] > 126) return false;
  return true;
}

void serialTick() {
  for (unsigned i = 0; i < 64 && Serial.available(); ++i) {
    const char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (!serialOverflow) {
        if (serialLine == "wifi-setup") requested.store(true);
        else if (serialLine == "wifi-scan" && active && !testing && !queued) beginScan();
        else if (serialLine == "wifi-scan-result") {
          finishScan();
          Serial.printf("Wi-Fi scan result: %s\n", scanResult.c_str());
        }
        else if (serialLine == "wifi-info") printInfo();
        else if (strncmp(serialLine.c_str(), "wifi-ap-password ", 17) == 0) {
          const char *password = serialLine.c_str() + 17;
          if (!validSetupPassword(password)) {
            Serial.println("Setup password must contain 8-63 printable ASCII characters.");
          } else if (storage.putString("ap-password", password) != strlen(password)) {
            Serial.println("Failed to save setup password; current password unchanged.");
          } else {
            const bool reopen = active;
            apPassword = password;
            if (reopen) closePortal();
            if (reopen) requested.store(true);
            Serial.println("Setup password saved. Active hotspot will restart.");
          }
        }
        else if (serialLine == "wifi-cancel" && active) closePortal();
        else if (serialLine == "wifi-forget CONFIRM") {
          if (storage.putUChar("selected", 0) == 1) {
            hasSaved = false;
            selectedSlot = 0;
            storage.remove("network1");
            storage.remove("network2");
            memset(&saved, 0, sizeof(saved));
            if (active) closePortal();
            connectSaved();
            requested.store(true);
            Serial.println("Saved network removed. Camera key and setup password unchanged.");
          } else Serial.println("Failed to remove network; configuration retained.");
        } else Serial.println("Commands: wifi-setup, wifi-info, wifi-cancel, wifi-forget CONFIRM, wifi-ap-password <password>");
      }
      serialLine = "";
      serialOverflow = false;
    } else if (serialLine.length() < 80 && !serialOverflow) serialLine += c;
    else serialOverflow = true;
  }
}
}  // namespace

bool networkBegin(const char *defaultHostname) {
  if (!validNetworkHostname(defaultHostname)) return false;
  strlcpy(defaultName, defaultHostname, sizeof(defaultName));
  if (!storage.begin("pet-network", false)) return false;
  selectedSlot = storage.getUChar("selected", 0);
  const char *slot = selectedSlot == 1 ? "network1" : "network2";
  if ((selectedSlot == 1 || selectedSlot == 2) && storage.getBytesLength(slot) == sizeof(saved)) {
    hasSaved = storage.getBytes(slot, &saved, sizeof(saved)) == sizeof(saved) &&
               validNetworkConfig(saved);
  }
  // RAM-only driver config: failed trial credentials must never overwrite NVS.
  WiFi.persistent(false);
  if (!WiFi.mode(WIFI_STA)) return false;
  WiFi.setSleep(false);
  apPassword = storage.getString("ap-password", "");
  if (!validSetupPassword(apPassword.c_str())) {
    apPassword = randomHex(12);
    if (storage.putString("ap-password", apPassword) != apPassword.length()) return false;
  }
  const uint64_t mac = ESP.getEfuseMac();
  char suffix[13];
  snprintf(suffix, sizeof(suffix), "%012llX", static_cast<unsigned long long>(mac));
  apName = String("PetCam-Setup-") + suffix;

  portal.on("/", HTTP_GET, [] {
    if (!apRequest()) return;
    String page = SETUP_PAGE;
    page.replace("{{TOKEN}}", token);
    page.replace("{{HOSTNAME}}", hasSaved ? saved.hostname : defaultName);
    portal.send(200, "text/html; charset=utf-8", page);
  });
  portal.on("/scan", HTTP_POST, [] {
    if (!apRequest(true)) return;
    if (testing || queued || completedAt) {
      portal.send(409, "application/json", "{\"error\":\"正在连接，请稍后扫描\"}"); return;
    }
    if (scanPending) {
      portal.send(202, "application/json", "{\"scanning\":true}"); return;
    }
    if (scannedAt && millis() - scannedAt < 5000) {
      portal.send(429, "application/json", "{\"error\":\"请稍后再刷新\"}"); return;
    }
    if (!beginScan()) {
      portal.send(503, "application/json", "{\"error\":\"扫描启动失败，请稍后重试\"}"); return;
    }
    portal.send(202, "application/json", "{\"scanning\":true}");
  });
  portal.on("/scan", HTTP_GET, [] {
    if (!apRequest()) return;
    finishScan();
    portal.send(scanPending ? 202 : 200, "application/json",
                scanPending ? String("{\"scanning\":true}") : scanResult);
  });
  portal.on("/configure", HTTP_POST, [] {
    if (!apRequest(true)) return;
    if (testing || queued || completedAt) {
      portal.send(409, "text/plain", "A connection attempt is already active.");
      return;
    }
    const String ssid = portal.arg("ssid"), password = portal.arg("password");
    const String hostname = portal.arg("hostname");
    if (!ssid.length() || ssid.length() > 32 || password.length() > 63 ||
        ssid.length() != strlen(ssid.c_str()) || password.length() != strlen(password.c_str()) ||
        hostname.length() != strlen(hostname.c_str()) || !validNetworkHostname(hostname.c_str())) {
      portal.send(400, "text/plain", "Invalid SSID, password or hostname length/format.");
      return;
    }
    candidate = NetworkConfig{};
    strlcpy(candidate.ssid, ssid.c_str(), sizeof(candidate.ssid));
    strlcpy(candidate.password, password.c_str(), sizeof(candidate.password));
    strlcpy(candidate.hostname, hostname.c_str(), sizeof(candidate.hostname));
    if (!validNetworkConfig(candidate)) {
      memset(candidate.password, 0, sizeof(candidate.password));
      portal.send(400, "text/plain", "Password must be empty or 8-63 bytes.");
      return;
    }
    queued = true;
    if (scanPending) esp_wifi_scan_stop();
    WiFi.scanDelete();
    scanPending = false;
    result = "connecting";
    portal.sendHeader("Location", "/state");
    portal.send(303);
  });
  portal.on("/state", HTTP_GET, [] {
    if (!apRequest()) return;
    String body = "<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
                  "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                  "<meta http-equiv='refresh' content='3'><title>连接进度</title>"
                  "<style>body{margin:0;background:#f5f6ef;color:#243d31;font:16px/1.7 system-ui,sans-serif;"
                  "padding:48px 20px}main{max-width:420px;margin:auto;background:white;padding:28px;"
                  "border:1px solid #e0e7dc;border-radius:24px;box-shadow:0 16px 48px #243d3110}"
                  "h1{font-size:26px}p{overflow-wrap:anywhere}a{display:block;padding:14px;border-radius:12px;"
                  "background:#246b47;color:white;text-align:center;text-decoration:none}</style>"
                  "<main><h1>正在为摄像头连接 Wi-Fi</h1><p>";
    body += result;
    body += "</p><p>";
    if (strcmp(result, "connecting") == 0)
      body += "正在尝试连接，请稍候。最多需要约 30 秒；请保持连接设备热点。";
    else if (strcmp(result, "connected") == 0)
      body += "连接成功，配置已保存！热点即将关闭，请将手机切回家庭 Wi-Fi。";
    else if (strcmp(result, "failed") == 0)
      body += "连接失败，请检查 Wi-Fi 名称、密码及信号后重试。原有配置没有被覆盖。";
    else if (strcmp(result, "storage-error") == 0)
      body += "保存失败，已返回原有网络配置，请重试或检查设备存储。";
    else body += "尚未开始连接，请返回填写 Wi-Fi 信息。";
    body += "</p><a href='/'>返回配网页面</a></main></html>";
    portal.send(200, "text/html; charset=utf-8", body);
  });
  portal.on("/cancel", HTTP_POST, [] {
    if (!apRequest(true)) return;
    portal.send(200, "text/plain", "Cancelled; closing setup hotspot.");
    closePortal();
  });
  portal.onNotFound([] {
    if (apRequest()) portal.send(404, "text/plain", "Not found");
  });
  connectSaved();
  ready = true;
  Serial.println("Network commands: wifi-setup, wifi-info, wifi-cancel, wifi-forget CONFIRM");
  if (!hasSaved) requested.store(true);
  return true;
}

void networkRequestSetup() { requested.store(true); }
const char *networkHostname() { return hasSaved ? saved.hostname : defaultName; }

void networkTick() {
  if (!ready) return;
  serialTick();
  if (requested.exchange(false)) openPortal();
  if (active) {
    finishScan();
    portal.handleClient();
    if (!active) return;
    const uint32_t now = millis();
    if (now - openedAt >= WINDOW_MS || (completedAt && now - completedAt >= 8000)) {
      closePortal();
      return;
    }
    if (queued) {
      queued = false;
      WiFi.setAutoReconnect(false);
      WiFi.disconnect(false, false);
      WiFi.setHostname(candidate.hostname);
      esp_netif_set_hostname(esp_netif_get_handle_from_ifkey("WIFI_STA_DEF"), candidate.hostname);
      WiFi.begin(candidate.ssid, candidate.password);
      testing = true;
      attemptedAt = now;
      connectedAt = 0;
    }
    if (testing) {
      if (WiFi.status() == WL_CONNECTED && WiFi.localIP() != IPAddress()) {
        if (!connectedAt) connectedAt = now;
        if (now - connectedAt >= STABLE_MS) {
          const uint8_t nextSlot = selectedSlot == 1 ? 2 : 1;
          const char *key = nextSlot == 1 ? "network1" : "network2";
          NetworkConfig verified;
          const bool written = storage.putBytes(key, &candidate, sizeof(candidate)) == sizeof(candidate) &&
              storage.getBytes(key, &verified, sizeof(verified)) == sizeof(verified) &&
              memcmp(&verified, &candidate, sizeof(candidate)) == 0;
          if (written && storage.putUChar("selected", nextSlot) == 1) {
            selectedSlot = nextSlot;
            saved = candidate;
            hasSaved = true;
            result = "connected";
            completedAt = now;
          } else {
            result = "storage-error";
            connectSaved();
          }
          testing = false;
          memset(&candidate, 0, sizeof(candidate));
        }
      } else connectedAt = 0;
      if (testing && now - attemptedAt >= CONNECT_MS) {
        testing = false;
        result = "failed";
        memset(&candidate, 0, sizeof(candidate));
        connectSaved();
      }
    }
  }
  if (!testing && !queued && !completedAt && !scanPending && hasSaved && WiFi.status() != WL_CONNECTED &&
      millis() - lastReconnect >= CONNECT_MS) {
    connectSaved();
  }
}