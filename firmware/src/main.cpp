// Pet Watch: AI Thinker ESP32-CAM / OV2640. No SD card or flash illumination.
#include <Arduino.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include <esp_camera.h>
#include <esp_http_server.h>
#include <esp_timer.h>
#include <freertos/semphr.h>
#include "network_setup.h"
#include "network_config.h"

#if __has_include("secrets.h")
#include "secrets.h"
#else
// Buildable without secrets, but refuses to run until configured.
#define CAMERA_KEY ""
#endif

#ifndef CAMERA_HOSTNAME
#define CAMERA_HOSTNAME "pet-camera"
#endif

static httpd_handle_t server = nullptr;
static SemaphoreHandle_t cameraLock;
static SemaphoreHandle_t flashLock;
static bool configured = false;
static bool mdnsStarted = false;
static uint32_t lastMdnsAttempt = 0;
static IPAddress mdnsAddress;
static String mdnsHostname;
static constexpr uint32_t MDNS_RETRY_MS = 15000;
static bool flashOn = false;
static uint32_t flashStarted = 0;
static constexpr uint32_t FLASH_MAX_MS = 60000;  // Avoid leaving the LED hot indefinitely.

static void updateMdns(bool connected, bool wasConnected) {
  const IPAddress address = connected ? WiFi.localIP() : IPAddress();
  const bool addressChanged = address != mdnsAddress || mdnsHostname != networkHostname();
  if (connected && (!wasConnected || addressChanged)) {
    Serial.print("Camera ready: http://");
    Serial.println(address);
  }
  if (mdnsStarted && (!connected || addressChanged)) {
    MDNS.end();
    mdnsStarted = false;
  }
  if (!connected) return;
  const uint32_t now = millis();
  if (!mdnsStarted && (!wasConnected || addressChanged ||
                       now - lastMdnsAttempt >= MDNS_RETRY_MS)) {
    lastMdnsAttempt = now;
    mdnsAddress = address;
    mdnsHostname = networkHostname();
    if (MDNS.begin(mdnsHostname.c_str()) && MDNS.addService("http", "tcp", 80)) {
      mdnsStarted = true;
      Serial.printf("mDNS ready: http://%s.local\n", mdnsHostname.c_str());
    } else {
      // begin() may have partially initialized the responder before failing.
      MDNS.end();
      Serial.println("mDNS initialization failed; retrying in 15 seconds.");
    }
  }
}

static esp_err_t unavailable(httpd_req_t *req, const char *message) {
  // IDF 4.4 has no HTTPD_503_SERVICE_UNAVAILABLE enum value.
  httpd_resp_set_status(req, "503 Service Unavailable");
  httpd_resp_set_type(req, "text/plain");
  return httpd_resp_sendstr(req, message);
}

static bool authorize(httpd_req_t *req) {
  char key[129] = {};
  size_t len = httpd_req_get_hdr_value_len(req, "X-Camera-Key");
  if (len == 0 || len >= sizeof(key) ||
      httpd_req_get_hdr_value_str(req, "X-Camera-Key", key, sizeof(key)) != ESP_OK) {
    httpd_resp_set_status(req, "401 Unauthorized");
    httpd_resp_sendstr(req, "Camera key required");
    return false;
  }
  const size_t expected = strlen(CAMERA_KEY);
  unsigned int difference = len ^ expected;
  for (size_t i = 0; i < expected; ++i) difference |= key[i] ^ CAMERA_KEY[i];
  if (difference != 0) {
    httpd_resp_set_status(req, "401 Unauthorized");
    httpd_resp_sendstr(req, "Invalid camera key");
    return false;
  }
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  return true;
}

static esp_err_t capture(httpd_req_t *req) {
  if (!authorize(req)) return ESP_OK;
  if (xSemaphoreTake(cameraLock, pdMS_TO_TICKS(2500)) != pdTRUE)
    return unavailable(req, "Camera busy");
  camera_fb_t *frame = esp_camera_fb_get();
  esp_err_t result;
  if (!frame) {
    result = unavailable(req, "Capture failed");
  } else {
    httpd_resp_set_type(req, "image/jpeg");
    result = httpd_resp_send(req, reinterpret_cast<const char *>(frame->buf), frame->len);
    esp_camera_fb_return(frame);
  }
  xSemaphoreGive(cameraLock);
  return result;
}

static esp_err_t status(httpd_req_t *req) {
  if (!authorize(req)) return ESP_OK;
  if (xSemaphoreTake(flashLock, pdMS_TO_TICKS(100)) != pdTRUE)
    return unavailable(req, "Flash busy");
  const bool light = flashOn;
  xSemaphoreGive(flashLock);
  char body[256];
  snprintf(body, sizeof(body),
           "{\"board\":\"ai-thinker-esp32cam\",\"uptime_s\":%llu,"
           "\"rssi_dbm\":%d,\"free_heap\":%u,\"psram\":%s,\"flash_on\":%s}",
           static_cast<unsigned long long>(esp_timer_get_time() / 1000000),
           WiFi.RSSI(), ESP.getFreeHeap(), psramFound() ? "true" : "false",
           light ? "true" : "false");
  httpd_resp_set_type(req, "application/json");
  return httpd_resp_sendstr(req, body);
}

static esp_err_t flashStatus(httpd_req_t *req) {
  if (!authorize(req)) return ESP_OK;
  if (xSemaphoreTake(flashLock, pdMS_TO_TICKS(100)) != pdTRUE)
    return unavailable(req, "Flash busy");
  const bool light = flashOn;
  xSemaphoreGive(flashLock);
  httpd_resp_set_type(req, "application/json");
  return httpd_resp_sendstr(req, light ? "{\"on\":true}" : "{\"on\":false}");
}

static esp_err_t setFlash(httpd_req_t *req) {
  if (!authorize(req)) return ESP_OK;
  char query[32], state[8];
  if (httpd_req_get_url_query_str(req, query, sizeof(query)) != ESP_OK ||
      httpd_query_key_value(query, "state", state, sizeof(state)) != ESP_OK)
    return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Missing flash state");
  if (strcmp(state, "on") != 0 && strcmp(state, "off") != 0)
    return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid flash state");
  if (xSemaphoreTake(flashLock, pdMS_TO_TICKS(100)) != pdTRUE)
    return unavailable(req, "Flash busy");
  const bool light = strcmp(state, "on") == 0;
  flashOn = light;
  flashStarted = millis();
  digitalWrite(4, light ? HIGH : LOW);
  xSemaphoreGive(flashLock);
  httpd_resp_set_type(req, "application/json");
  return httpd_resp_sendstr(req, light ? "{\"on\":true}" : "{\"on\":false}");
}

static esp_err_t control(httpd_req_t *req) {
  if (!authorize(req)) return ESP_OK;
  char query[64], resolution[16];
  if (httpd_req_get_url_query_str(req, query, sizeof(query)) != ESP_OK ||
      httpd_query_key_value(query, "resolution", resolution, sizeof(resolution)) != ESP_OK)
    return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Missing resolution");
  framesize_t size;
  if (strcmp(resolution, "low") == 0) size = FRAMESIZE_QVGA;
  else if (strcmp(resolution, "standard") == 0) size = FRAMESIZE_VGA;
  else if (strcmp(resolution, "high") == 0) size = FRAMESIZE_SVGA;
  else return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid resolution");
  if (xSemaphoreTake(cameraLock, pdMS_TO_TICKS(2500)) != pdTRUE)
    return unavailable(req, "Camera busy");
  sensor_t *sensor = esp_camera_sensor_get();
  const int result = sensor ? sensor->set_framesize(sensor, size) : -1;
  // Discard buffered images so subsequent captures use the new setting.
  for (int i = 0; i < 2; ++i) {
    camera_fb_t *frame = esp_camera_fb_get();
    if (frame) esp_camera_fb_return(frame);
  }
  xSemaphoreGive(cameraLock);
  if (result != 0)
    return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Setting failed");
  httpd_resp_set_type(req, "application/json");
  return httpd_resp_sendstr(req, "{\"ok\":true}");
}

static esp_err_t startNetworkSetup(httpd_req_t *req) {
  if (!authorize(req)) return ESP_OK;
  networkRequestSetup();
  httpd_resp_set_type(req, "application/json");
  return httpd_resp_sendstr(req, "{\"setup_requested\":true}");
}

static bool startServer() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 80;
  config.max_open_sockets = 3;
  config.lru_purge_enable = true;
  config.recv_wait_timeout = 3;
  config.send_wait_timeout = 3;
  if (httpd_start(&server, &config) != ESP_OK) return false;
  httpd_uri_t captureRoute = {};
  captureRoute.uri = "/capture";
  captureRoute.method = HTTP_GET;
  captureRoute.handler = capture;
  httpd_uri_t statusRoute = {};
  statusRoute.uri = "/status";
  statusRoute.method = HTTP_GET;
  statusRoute.handler = status;
  httpd_uri_t controlRoute = {};
  controlRoute.uri = "/control";
  controlRoute.method = HTTP_POST;
  controlRoute.handler = control;
  httpd_uri_t flashRoute = {};
  flashRoute.uri = "/flash";
  flashRoute.method = HTTP_GET;
  flashRoute.handler = flashStatus;
  httpd_uri_t setFlashRoute = {};
  setFlashRoute.uri = "/flash";
  setFlashRoute.method = HTTP_POST;
  setFlashRoute.handler = setFlash;
  httpd_uri_t setupRoute = {};
  setupRoute.uri = "/network/setup";
  setupRoute.method = HTTP_POST;
  setupRoute.handler = startNetworkSetup;
  return httpd_register_uri_handler(server, &captureRoute) == ESP_OK &&
         httpd_register_uri_handler(server, &statusRoute) == ESP_OK &&
         httpd_register_uri_handler(server, &controlRoute) == ESP_OK &&
         httpd_register_uri_handler(server, &flashRoute) == ESP_OK &&
         httpd_register_uri_handler(server, &setFlashRoute) == ESP_OK &&
         httpd_register_uri_handler(server, &setupRoute) == ESP_OK;
}

void setup() {
  Serial.begin(115200);
  pinMode(4, OUTPUT);
  digitalWrite(4, LOW);  // Leave onboard flash off; room has independent lighting.
  if (strlen(CAMERA_KEY) < 32 || strlen(CAMERA_KEY) > 128 ||
      strncmp(CAMERA_KEY, "CHANGE_", 7) == 0) {
    Serial.println("Configure include/secrets.h (random camera key) first.");
    return;
  }
  if (!psramFound()) {
    Serial.println("PSRAM unavailable. Confirm AI Thinker board, power, and PSRAM hardware.");
    return;
  }
  if (!validNetworkHostname(CAMERA_HOSTNAME)) {
    Serial.println("CAMERA_HOSTNAME must be 1-32 lowercase letters/digits/hyphens, no edge hyphens.");
    return;
  }
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = 5; c.pin_d1 = 18; c.pin_d2 = 19; c.pin_d3 = 21;
  c.pin_d4 = 36; c.pin_d5 = 39; c.pin_d6 = 34; c.pin_d7 = 35;
  c.pin_xclk = 0; c.pin_pclk = 22; c.pin_vsync = 25; c.pin_href = 23;
  c.pin_sccb_sda = 26; c.pin_sccb_scl = 27;
  c.pin_pwdn = 32; c.pin_reset = -1;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size = FRAMESIZE_SVGA;  // Allocate for largest offered resolution.
  c.jpeg_quality = 14;
  c.fb_count = 2;
  c.fb_location = CAMERA_FB_IN_PSRAM;
  c.grab_mode = CAMERA_GRAB_LATEST;
  if (esp_camera_init(&c) != ESP_OK) {
    Serial.println("Camera init failed. Check model, ribbon cable, and power.");
    return;
  }
  esp_camera_sensor_get()->set_framesize(esp_camera_sensor_get(), FRAMESIZE_VGA);
  if (!networkBegin(CAMERA_HOSTNAME)) {
    Serial.println("Network configuration storage/initialization failed.");
    return;
  }
  cameraLock = xSemaphoreCreateMutex();
  flashLock = xSemaphoreCreateMutex();
  if (!cameraLock || !flashLock || !startServer()) {
    Serial.println("HTTP server initialization failed.");
    return;
  }
  configured = true;
}

void loop() {
  static bool wasConnected = false;
  if (!configured) { delay(1000); return; }
  networkTick();
  if (xSemaphoreTake(flashLock, pdMS_TO_TICKS(100)) == pdTRUE) {
    if (flashOn && millis() - flashStarted >= FLASH_MAX_MS) {
      flashOn = false;
      digitalWrite(4, LOW);
    }
    xSemaphoreGive(flashLock);
  }
  const bool connected = WiFi.status() == WL_CONNECTED;
  updateMdns(connected, wasConnected);
  wasConnected = connected;
  delay(10);  // Keep the setup portal responsive without blocking reconnects.
}
