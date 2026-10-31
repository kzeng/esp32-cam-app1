// Links the production translation unit; no access to its private state.
#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h>
#include "network_config.h"
#include "network_setup.h"
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>

#define CHECK(condition) do { if (!(condition)) throw std::runtime_error(\
  std::string(__FILE__) + ":" + std::to_string(__LINE__) + ": " #condition); } while (false)

static WebServer &http() { return *WebServer::instance; }
static void tick(uint32_t elapsed = 0) { fake::now += elapsed; networkTick(); }
static void serial(const char *command) { Serial.input += command; Serial.input += '\n'; tick(); }
static void seed() {
  Preferences p; CHECK(p.begin("pet-network", false));
  NetworkConfig config;
  strlcpy(config.ssid, "old-net", sizeof(config.ssid));
  strlcpy(config.password, "old-secret", sizeof(config.password));
  strlcpy(config.hostname, "old-camera", sizeof(config.hostname));
  CHECK(p.putBytes("network1", &config, sizeof(config)) == sizeof(config));
  CHECK(p.putUChar("selected", 1) == 1);
}
static void boot(bool saved) {
  CHECK(networkBegin("pet-camera"));
  CHECK(!WiFi.persistentEnabled);
  CHECK(!WiFi.autoReconnect);
  CHECK(http().boundAddress == IPAddress(192,168,4,1));
  CHECK(http().port == 8081);
  tick();
  CHECK(WiFi.ap == !saved);
}
static void open() { networkRequestSetup(); tick(); CHECK(WiFi.ap); CHECK(http().running); }
static String token() {
  CHECK(http().request("/", HTTP_GET) == 200);
  CHECK(http().headers.at("Cache-Control") == "no-store");
  const std::string marker = "name='token' value='";
  const auto start = http().body.value.find(marker);
  CHECK(start != std::string::npos);
  const auto offset = start + marker.size();
  const auto end = http().body.value.find('\'', offset);
  CHECK(end != std::string::npos);
  String value(http().body.value.substr(offset, end - offset));
  CHECK(value.length() == 32);
  return value;
}
static int configure(String csrf, String ssid = "new-net", String password = "new-secret", String hostname = "new-camera") {
  return http().request("/configure", HTTP_POST,
    {{"token", csrf}, {"ssid", ssid}, {"password", password}, {"hostname", hostname}});
}
static void state(const char *expected) {
  CHECK(http().request("/state", HTTP_GET) == 200);
  CHECK(http().body.value.find(std::string("<p>") + expected + "</p>") != std::string::npos);
}
static void connected() {
  WiFi.connection = WL_CONNECTED; WiFi.ip = IPAddress(10,0,0,5);
  tick(); tick(2999); state("connecting"); tick(1);
}
static void snapshot(const char *path, bool write) {
  if (write) {
    std::ofstream out(path, std::ios::binary);
    for (const auto &space : fake::nvs) for (const auto &item : space.second)
      out << std::quoted(space.first) << ' ' << std::quoted(item.first) << ' '
          << std::quoted(std::string(item.second.begin(), item.second.end())) << '\n';
    CHECK(out.good());
  } else {
    std::ifstream in(path, std::ios::binary); CHECK(in.good());
    std::string space, key, bytes;
    while (in >> std::quoted(space) >> std::quoted(key) >> std::quoted(bytes))
      fake::nvs[space][key] = fake::Bytes(bytes.begin(), bytes.end());
    CHECK(in.eof());
  }
}
static void validation() {
  for (const char *name : {"", "Camera", "-cam", "cam-", "cam.local", "cam_name", "a b"})
    CHECK(!validNetworkHostname(name));
  CHECK(validNetworkHostname("camera-01"));
  CHECK(validNetworkHostname(std::string(32, 'a').c_str()));
  CHECK(!validNetworkHostname(std::string(33, 'a').c_str()));
  NetworkConfig c;
  strlcpy(c.ssid, "net", sizeof(c.ssid)); strlcpy(c.hostname, "cam", sizeof(c.hostname));
  CHECK(validNetworkConfig(c));
  for (size_t n : {size_t(1), size_t(7), size_t(8), size_t(63), size_t(64)}) {
    std::memset(c.password, 0, sizeof(c.password)); std::memset(c.password, 'x', n);
    CHECK(validNetworkConfig(c) == (n >= 8 && n <= 63));
  }
  c.password[0] = 0; c.version = 2; CHECK(!validNetworkConfig(c)); c.version = 1;
  std::memset(c.ssid, 'x', sizeof(c.ssid)); CHECK(!validNetworkConfig(c));
  CHECK(!networkBegin("Invalid.Name")); CHECK(fake::writes.empty());
}


static void scenario(const std::string &name, const char *path) {
  if (name == "validation") { validation(); return; }
  if (name == "ap-password-restore") {
    snapshot(path, false); boot(true); serial("wifi-setup");
    CHECK(WiFi.apPassword == "test-pass-123"); return;
  }
  if (name == "restore" || name == "restore-old") {
    snapshot(path, false); boot(true);
    CHECK(std::string(networkHostname()) == (name == "restore" ? "new-camera" : "old-camera"));
    CHECK(WiFi.attempts.back().first == (name == "restore" ? "new-net" : "old-net"));
    CHECK(WiFi.attempts.back().second == (name == "restore" ? "new-secret" : "old-secret"));
    return;
  }
  if (name == "open-failure" || name == "password-failure") {
    fake::failOpen = name == "open-failure";
    fake::failString = name == "password-failure";
    CHECK(!networkBegin("pet-camera")); tick(); CHECK(!WiFi.ap); return;
  }
  const bool first = name == "first" || name == "first-save" || name == "security" || name == "http-validation";
  if (!first) seed();
  boot(!first);
  if (name == "scan") {
    open(); const String csrf = token();
    CHECK(http().body.value.find("role=\"combobox\"") != std::string::npos);
    CHECK(http().body.value.find("{{TOKEN}}") == std::string::npos);
    CHECK(http().request("/scan", HTTP_POST) == 403);
    CHECK(http().request("/scan", HTTP_POST, {{"token", csrf}}, IPAddress(10,0,0,5)) == 403);
    CHECK(WiFi.scans == 0);
    CHECK(http().request("/scan", HTTP_POST, {{"token", csrf}}) == 202);
    CHECK(http().request("/scan", HTTP_GET) == 202);
    WiFi.networks = {{"weak", -88, 1}, {"strong", -30, 1}, {"weak", -60, 1},
                     {"", -10, 0}, {"quote\"\\\n", -45, 0}};
    WiFi.scanStatus = 5;
    CHECK(http().request("/scan", HTTP_GET) == 200);
    const std::string body = http().body.value;
    CHECK(body.find("strong") < body.find("quote"));
    CHECK(body.find("quote") < body.find("weak"));
    CHECK(body.find("weak") == body.rfind("weak"));
    CHECK(body.find("quote\\\"\\\\\\u000a") != std::string::npos);
    CHECK(body.find("\"secure\":false") != std::string::npos);
    CHECK(http().request("/scan", HTTP_POST, {{"token", csrf}}) == 429);
    tick(5000); CHECK(http().request("/scan", HTTP_POST, {{"token", csrf}}) == 202);
    WiFi.scanStatus = WIFI_SCAN_FAILED;
    CHECK(http().request("/scan", HTTP_GET) == 200);
    CHECK(http().body.value.find("error") != std::string::npos);
    CHECK(configure(csrf) == 303);
    CHECK(http().request("/scan", HTTP_POST, {{"token", csrf}}) == 409);
    return;
  }
  if (name == "ap-password") {
    serial("wifi-setup");
    const String oldPassword = WiFi.apPassword;
    serial("wifi-ap-password short"); CHECK(WiFi.apPassword == oldPassword);
    fake::failString = true;
    serial("wifi-ap-password test-pass-123"); CHECK(WiFi.apPassword == oldPassword);
    fake::failString = false;
    serial("wifi-ap-password test-pass-123");
    CHECK(WiFi.ap); CHECK(WiFi.apPassword == "test-pass-123");
    CHECK(Serial.output.find("test-pass-123") == std::string::npos);
    snapshot(path, true); return;
  }
  if (name == "first") {
    CHECK(WiFi.attempts.empty()); CHECK(WiFi.apPassword.length() == 24);
    CHECK(Serial.output.find(WiFi.apPassword.value) == std::string::npos);
    CHECK(std::string(networkHostname()) == "pet-camera");
    token(); serial("wifi-info");
    CHECK(Serial.output.find(WiFi.apPassword.value) != std::string::npos); return;
  }
  if (name == "reconnect") {
    CHECK(WiFi.attempts.size() == 1); CHECK(WiFi.attempts.back().first == "old-net");
    tick(29999); CHECK(WiFi.attempts.size() == 1);
    tick(1); CHECK(WiFi.attempts.size() == 2);
    WiFi.connection = WL_CONNECTED; tick(30000); CHECK(WiFi.attempts.size() == 2); return;
  }
  if (!first) open();
  const String csrf = token();
  const auto before = fake::nvs;
  if (name == "security") {
    CHECK(http().request("/", HTTP_GET, {}, IPAddress(10,0,0,5)) == 403);
    CHECK(http().request("/configure", HTTP_POST, {{"token", csrf}}, IPAddress(10,0,0,5)) == 403);
    CHECK(configure("") == 403); CHECK(configure("wrong") == 403);
    CHECK(http().request("/cancel", HTTP_POST, {{"token", "wrong"}}) == 403);
    CHECK(WiFi.ap); CHECK(fake::nvs == before); CHECK(WiFi.attempts.empty()); return;
  }
  if (name == "http-validation") {
    CHECK(configure(csrf, "") == 400);
    CHECK(configure(csrf, std::string(33, 's')) == 400);
    CHECK(configure(csrf, "net", "short") == 400);
    CHECK(configure(csrf, "net", std::string(64, 'p')) == 400);
    CHECK(configure(csrf, "net", "", "Bad.Host") == 400);
    CHECK(configure(csrf, String(std::string("net\0hidden", 10))) == 400);
    CHECK(configure(csrf, "net", String(std::string("password\0hidden", 15))) == 400);
    CHECK(fake::nvs == before); CHECK(WiFi.attempts.empty());
    CHECK(configure(csrf, "open-net", "") == 303); tick();
    CHECK(WiFi.attempts.back().second.empty()); return;
  }
  if (name == "timeout" || name == "cancel" || name == "serial-cancel") {
    if (name == "timeout") tick(600000);
    else {
      CHECK(configure(csrf) == 303); tick();
      if (name == "cancel") CHECK(http().request("/cancel", HTTP_POST, {{"token", csrf}}) == 200);
      else serial("wifi-cancel");
    }
    CHECK(!WiFi.ap); CHECK(!http().running); CHECK(WiFi.currentMode == WIFI_STA);
    CHECK(WiFi.attempts.back().first == "old-net"); CHECK(fake::nvs == before); return;
  }
  if (name == "forget" || name == "forget-failure") {
    fake::nvs["camera"]["key"] = {1,2,3};
    fake::nvs["pet-network"]["unrelated"] = {4,5};
    const auto password = fake::nvs["pet-network"]["ap-password"];
    serial("wifi-forget"); CHECK(std::string(networkHostname()) == "old-camera");
    fake::failSelected = name == "forget-failure";
    serial("wifi-forget CONFIRM");
    CHECK(fake::nvs["camera"]["key"] == fake::Bytes({1,2,3}));
    CHECK(fake::nvs["pet-network"]["unrelated"] == fake::Bytes({4,5}));
    CHECK(fake::nvs["pet-network"]["ap-password"] == password);
    if (fake::failSelected) CHECK(std::string(networkHostname()) == "old-camera");
    else {
      CHECK(std::string(networkHostname()) == "pet-camera");
      CHECK(fake::nvs["pet-network"].count("network1") == 0);
      CHECK(fake::nvs["pet-network"].count("network2") == 0);
      CHECK(fake::nvs["pet-network"]["selected"] == fake::Bytes({0})); CHECK(WiFi.ap);
    }
    return;
  }
  CHECK(configure(csrf) == 303);
  CHECK(configure(csrf) == 409); tick();
  CHECK(WiFi.attempts.back().first == "new-net");
  CHECK(std::string(networkHostname()) == (first ? "pet-camera" : "old-camera"));
  if (name == "trial-failure") {
    tick(30000); state("failed"); CHECK(fake::nvs == before);
    CHECK(WiFi.attempts.back().first == "old-net"); return;
  }
  fake::failBytes = name == "write-failure";
  fake::failSelected = name == "commit-failure";
  fake::corruptRead = name == "verify-failure";
  // Association alone is insufficient: require an address and 3 stable seconds.
  WiFi.connection = WL_CONNECTED; tick(3000); state("connecting");
  connected();
  if (name == "save" || name == "first-save") {
    state("connected"); CHECK(std::string(networkHostname()) == "new-camera");
    CHECK(fake::nvs["pet-network"]["selected"] == fake::Bytes({static_cast<uint8_t>(first ? 1 : 2)}));
    snapshot(path, true); tick(8000); CHECK(!WiFi.ap);
    CHECK(WiFi.attempts.back().first == "new-net");
  } else {
    state("storage-error"); CHECK(std::string(networkHostname()) == "old-camera");
    CHECK(WiFi.attempts.back().first == "old-net");
    CHECK(fake::nvs["pet-network"]["selected"] == before.at("pet-network").at("selected"));
    CHECK(fake::nvs["pet-network"]["network1"] == before.at("pet-network").at("network1"));
    snapshot(path, true);
  }
}
int main(int argc, char **argv) {
  try {
    CHECK(argc >= 2); scenario(argv[1], argc >= 3 ? argv[2] : "");
    std::cout << "PASS " << argv[1] << '\n'; return 0;
  } catch (const std::exception &error) { std::cerr << error.what() << '\n'; return 1; }
}
