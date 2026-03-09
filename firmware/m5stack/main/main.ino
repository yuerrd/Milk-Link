/**
 * Milk-Link - M5Stack Chain DualKey (MQTT)
 *
 * Based on proven working code, with added robustness:
 *   - WiFi exponential backoff reconnect
 *   - MQTT exponential backoff reconnect + LWT
 *   - publish retry (3 attempts)
 *   - WiFi down: buttons still respond with red flash
 *   - setup WiFi failure: loop retries
 *
 * Board: M5ChainDualKey (M5Stack board manager >= 3.2.4)
 * Libs:  M5Unified >= 0.2.11, ArduinoJson >= 7.x,
 *        Adafruit NeoPixel >= 1.15.2, PubSubClient >= 2.8
 *
 * LED: red=no WiFi, white=sending, green=milk ok,
 *      yellow=solid ok, orange=duplicate, purple=MQTT fail
 *
 * SWITCH_1(G8)/SWITCH_2(G7): do NOT set OUTPUT HIGH
 */

#include "M5Unified.h"
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Adafruit_NeoPixel.h>
#include <time.h>
#include "config.h"

// -- reconnect params --
static const unsigned long WIFI_RETRY_BASE_MS  =  5000UL;
static const unsigned long WIFI_RETRY_MAX_MS   = 60000UL;
static const unsigned long MQTT_RETRY_BASE_MS  =  3000UL;
static const unsigned long MQTT_RETRY_MAX_MS   = 60000UL;
static const int           PUBLISH_MAX_RETRY   = 3;

// -- reconnect state --
static unsigned long s_wifiNextRetry   = 0;
static unsigned long s_wifiRetryDelay  = WIFI_RETRY_BASE_MS;
static unsigned long s_mqttNextRetry   = 0;
static unsigned long s_mqttRetryDelay  = MQTT_RETRY_BASE_MS;
static bool          s_ntpSynced       = false;
static bool          s_wifiWasConnected = false;

// -- buttons (M5Unified) --
m5::Button_Class Key1;
m5::Button_Class Key2;

// -- RGB LED --
Adafruit_NeoPixel LED(NUM_LEDS, LED_SIG_PIN, NEO_RGB + NEO_KHZ800);

// -- MQTT --
WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);

// -- response cache --
static volatile int  s_responseStatus  = 0;
static volatile int  s_responseWaitSec = 300;

// -- night mode (refresh every minute) --
static bool          s_nightMode           = false;
static unsigned long s_nightModeLastUpdate = 0;

void updateNightMode() {
    unsigned long now = millis();
    if (now - s_nightModeLastUpdate < 60000UL) return;
    s_nightModeLastUpdate = now;
    struct tm t;
    if (getLocalTime(&t, 100)) {
        s_nightMode = (t.tm_hour >= 0 && t.tm_hour < 6);
    }
}

// -- LED helpers --
uint8_t nightScale(uint8_t val) {
    return s_nightMode ? (uint8_t)(val * 5 / 100) : val;
}

void ledSetAll(uint8_t r, uint8_t g, uint8_t b) {
    r = nightScale(r); g = nightScale(g); b = nightScale(b);
    for (int i = 0; i < NUM_LEDS; i++)
        LED.setPixelColor(i, LED.Color(r, g, b));
    LED.show();
}

void ledOff() {
    for (int i = 0; i < NUM_LEDS; i++) LED.setPixelColor(i, 0);
    LED.show();
}

void ledBlink(uint8_t r, uint8_t g, uint8_t b, int n, int onMs = 200, int offMs = 150) {
    for (int i = 0; i < n; i++) {
        ledSetAll(r, g, b);
        delay(onMs);
        ledOff();
        if (i < n - 1) delay(offMs);
    }
}

// -- MQTT callback --
void mqttCallback(char* topic, byte* payload, unsigned int length) {
    String payloadStr;
    for (unsigned int i = 0; i < length; i++)
        payloadStr += (char)payload[i];
    Serial.printf("[MQTT] Received on %s: %s\n", topic, payloadStr.c_str());

    JsonDocument doc;
    if (deserializeJson(doc, payloadStr) != DeserializationError::Ok) {
        Serial.println("[WARN] Invalid JSON in response");
        return;
    }
    s_responseStatus = doc["status"] | 0;
    if (s_responseStatus == 409)
        s_responseWaitSec = doc["wait_seconds"] | 300;
}

// -- WiFi reconnect (exponential backoff, non-blocking) --
bool maintainWifi() {
    if (WiFi.status() == WL_CONNECTED) {
        s_wifiRetryDelay = WIFI_RETRY_BASE_MS;
        return true;
    }
    unsigned long now = millis();
    if (now < s_wifiNextRetry) return false;

    wl_status_t st = WiFi.status();
    Serial.printf("[WiFi] status=%d, reconnecting (next in %lus)...\n",
                  (int)st, s_wifiRetryDelay / 1000);

    if (st == WL_NO_SSID_AVAIL || st == WL_CONNECT_FAILED) {
        WiFi.disconnect(false);
        delay(100);
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    } else {
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    }

    s_wifiRetryDelay = min(s_wifiRetryDelay * 2, WIFI_RETRY_MAX_MS);
    s_wifiNextRetry  = now + s_wifiRetryDelay;
    return false;
}

// -- NTP sync --
void syncNtp() {
    if (s_ntpSynced) return;
    configTime(8 * 3600, 0, "pool.ntp.org", "time.cloudflare.com");
    struct tm t;
    if (getLocalTime(&t, 5000)) {
        Serial.printf("[NTP] Synced: %02d:%02d\n", t.tm_hour, t.tm_min);
        s_ntpSynced = true;
    } else {
        Serial.println("[WARN] NTP sync failed, will retry");
    }
}

// -- MQTT reconnect (exponential backoff + LWT) --
bool maintainMqtt() {
    if (mqtt.connected()) {
        s_mqttRetryDelay = MQTT_RETRY_BASE_MS;
        return true;
    }
    unsigned long now = millis();
    if (now < s_mqttNextRetry) return false;

    Serial.printf("[MQTT] Connecting to %s:%d ...\n",
                  MQTT_BROKER_HOST, MQTT_BROKER_PORT);
    const char* user = (strlen(MQTT_USERNAME) > 0) ? MQTT_USERNAME : nullptr;
    const char* pass = (strlen(MQTT_PASSWORD) > 0) ? MQTT_PASSWORD : nullptr;

    String statusTopic = String(MQTT_TOPIC_PREFIX) + "/" + DEVICE_ID + "/status";
    const char* willMsg = "{\"online\":false}";

    if (mqtt.connect(DEVICE_ID, user, pass,
                     statusTopic.c_str(), 1, true, willMsg)) {
        Serial.println("[MQTT] Connected");
        mqtt.publish(statusTopic.c_str(), "{\"online\":true}", true);

        String feedResp  = String(MQTT_TOPIC_PREFIX) + "/" + DEVICE_ID + "/feed/response";
        String solidResp = String(MQTT_TOPIC_PREFIX) + "/" + DEVICE_ID + "/solid/response";
        mqtt.subscribe(feedResp.c_str(), 1);
        mqtt.subscribe(solidResp.c_str(), 1);
        Serial.println("[MQTT] Subscribed to response topics");
        s_mqttRetryDelay = MQTT_RETRY_BASE_MS;
        return true;
    }

    Serial.printf("[MQTT] Failed rc=%d, retry in %lus\n",
                  mqtt.state(), s_mqttRetryDelay / 1000);
    s_mqttRetryDelay = min(s_mqttRetryDelay * 2, MQTT_RETRY_MAX_MS);
    s_mqttNextRetry  = now + s_mqttRetryDelay;
    return false;
}

// -- wait for MQTT response --
bool waitForResponse(unsigned long timeoutMs) {
    unsigned long start = millis();
    s_responseStatus = 0;
    while (millis() - start < timeoutMs) {
        mqtt.loop();
        if (s_responseStatus != 0) return true;
        if (WiFi.status() != WL_CONNECTED) {
            Serial.println("[WARN] WiFi lost during response wait");
            return false;
        }
        yield();
        delay(20);
    }
    return false;
}

// -- publish with retry --
bool publishAction(const char* action) {
    JsonDocument doc;
    doc["device_id"] = DEVICE_ID;
    doc["secret"]    = DEVICE_SECRET;
    String body;
    serializeJson(doc, body);
    String topic = String(MQTT_TOPIC_PREFIX) + "/" + DEVICE_ID + "/" + action;

    for (int attempt = 1; attempt <= PUBLISH_MAX_RETRY; attempt++) {
        if (mqtt.publish(topic.c_str(), body.c_str(), false)) {
            Serial.printf("[MQTT] Published %s (attempt %d)\n", topic.c_str(), attempt);
            return true;
        }
        Serial.printf("[MQTT] Publish failed (attempt %d/%d)\n",
                      attempt, PUBLISH_MAX_RETRY);
        if (attempt < PUBLISH_MAX_RETRY) {
            maintainMqtt();
            delay(300);
        }
    }
    return false;
}

// -- unified button handler --
void handleAction(const char* action) {
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[WARN] WiFi not connected, press ignored");
        ledBlink(255, 0, 0, 3, 150, 100);
        return;
    }
    if (!mqtt.connected() && !maintainMqtt()) {
        Serial.println("[WARN] MQTT not connected, press ignored");
        ledBlink(128, 0, 128, 2, 400, 200);
        return;
    }

    ledSetAll(255, 255, 255);
    Serial.printf("[INFO] Sending %s via MQTT...\n", action);

    if (!publishAction(action)) {
        ledOff();
        ledBlink(128, 0, 128, 2, 400, 200);
        return;
    }

    bool got = waitForResponse(8000);
    ledOff();

    if (!got) {
        Serial.println("[WARN] Response timeout");
        ledBlink(128, 0, 128, 3, 300, 150);
        return;
    }

    Serial.printf("[MQTT] Response status: %d\n", s_responseStatus);
    bool isMilk = (strcmp(action, "feed") == 0);

    if (s_responseStatus == 201) {
        if (isMilk) ledBlink(0, 255, 0,   2, 300, 150);
        else        ledBlink(255, 200, 0,  2, 300, 150);
    } else if (s_responseStatus == 409) {
        Serial.printf("[WARN] Duplicate, wait %ds\n", s_responseWaitSec);
        ledBlink(255, 80, 0, 4, 100, 80);
    } else if (s_responseStatus == 403) {
        Serial.println("[ERROR] Auth failed (403)");
        ledBlink(255, 0, 0, 3, 300, 200);
    } else {
        Serial.printf("[ERROR] Unexpected status %d\n", s_responseStatus);
        ledSetAll(255, 0, 0);
        delay(1000);
        ledOff();
    }
}

// -- Setup (same structure as proven working version) --
void setup() {
    M5.begin();
    Serial.begin(115200);

    pinMode(PIN_KEY1, INPUT_PULLUP);
    pinMode(PIN_KEY2, INPUT_PULLUP);

    pinMode(LED_PWR_PIN, OUTPUT);
    digitalWrite(LED_PWR_PIN, HIGH);
    LED.begin();
    ledOff();

    Serial.println("[INFO] Milk-Link Chain DualKey (MQTT) starting...");

    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("[WiFi] Connecting");
    for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) {
        ledSetAll(0, 0, 255);
        delay(300);
        ledOff();
        delay(300);
        Serial.print(".");
    }
    Serial.println();

    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("[WiFi] OK: %s\n", WiFi.localIP().toString().c_str());
        syncNtp();

        mqtt.setServer(MQTT_BROKER_HOST, MQTT_BROKER_PORT);
        mqtt.setCallback(mqttCallback);
        mqtt.setBufferSize(512);
        mqtt.setKeepAlive(20);
        mqtt.setSocketTimeout(5);
        maintainMqtt();

        ledSetAll(0, 255, 0);
        delay(1500);
        ledOff();
        s_wifiWasConnected = true;
    } else {
        Serial.println("[WARN] WiFi failed, will retry in loop");
        mqtt.setServer(MQTT_BROKER_HOST, MQTT_BROKER_PORT);
        mqtt.setCallback(mqttCallback);
        mqtt.setBufferSize(512);
        mqtt.setKeepAlive(20);
        mqtt.setSocketTimeout(5);

        ledSetAll(255, 0, 0);
        delay(2000);
        ledOff();
    }

    Serial.println("[INFO] Ready. Press Key1 or Key2 to record feeding.");
}

// -- Loop --
void loop() {
    uint32_t ms = millis();
    Key1.setRawState(ms, !digitalRead(PIN_KEY1));
    Key2.setRawState(ms, !digitalRead(PIN_KEY2));

    updateNightMode();

    bool wifiOk = maintainWifi();

    if (!wifiOk) {
        ledSetAll(255, 0, 0);
        s_wifiWasConnected = false;
        // no return: keep checking buttons
    } else {
        if (!s_wifiWasConnected) {
            Serial.printf("[WiFi] Reconnected: %s\n", WiFi.localIP().toString().c_str());
            syncNtp();
            s_mqttNextRetry  = 0;
            s_mqttRetryDelay = MQTT_RETRY_BASE_MS;
            s_wifiWasConnected = true;
            ledOff();
        }
        maintainMqtt();
        if (mqtt.connected()) mqtt.loop();
    }

    if (Key1.wasPressed() || Key2.wasPressed()) {
        delay(60);
        bool k1held = !digitalRead(PIN_KEY1);
        bool k2held = !digitalRead(PIN_KEY2);

        if (k1held && k2held) {
            Serial.println("[INFO] Dual key -> solid food");
            handleAction("solid");
        } else {
            Serial.println("[INFO] Single key -> milk");
            handleAction("feed");
        }
    }

    delay(10);
}
