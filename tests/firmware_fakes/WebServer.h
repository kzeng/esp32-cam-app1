#pragma once
#include "WiFi.h"
#include <functional>
#include <map>
#include <stdexcept>
enum HTTPMethod { HTTP_GET, HTTP_POST };
class WebServer {
 public:
  inline static WebServer *instance = nullptr;
  IPAddress boundAddress;
  int port;
  bool running = false;
  int code = 0;
  String body;
  std::map<std::string, String> arguments, headers;
  std::map<std::pair<std::string, HTTPMethod>, std::function<void()>> routes;
  std::function<void()> missing;
  struct Client { IPAddress address; IPAddress localIP() const { return address; } } peer;
  WebServer(IPAddress address, int number) : boundAddress(address), port(number) { instance = this; }
  void on(const char *path, HTTPMethod method, std::function<void()> handler) { routes[{path, method}] = std::move(handler); }
  void onNotFound(std::function<void()> handler) { missing = std::move(handler); }
  void begin() { running = true; }
  void stop() { running = false; }
  void handleClient() {}
  Client &client() { return peer; }
  String arg(const char *name) const { const auto it = arguments.find(name); return it == arguments.end() ? String() : it->second; }
  void sendHeader(const char *name, const String &value) { headers[name] = value; }
  void send(int status, const char * = "", const String &text = String()) { code = status; body = text; }
  int request(const char *path, HTTPMethod method, std::map<std::string, String> args = {},
              IPAddress local = IPAddress(192,168,4,1)) {
    if (!running) throw std::runtime_error("request to stopped portal");
    arguments = std::move(args); peer.address = local; code = 0; body = ""; headers.clear();
    const auto it = routes.find({path, method});
    if (it == routes.end()) missing(); else it->second();
    return code;
  }
};
