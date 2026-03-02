/**
 * Milk-Link — M5Stack Chain DualKey 喂奶记录固件
 *
 * 功能：
 *   - 单键按下 → POST /feed → 记录一次喂奶
 *     · 服务端自动判断时段（00:00-06:00 夜晚 120ml，其他 160ml）
 *     · 辅食后按下固定 120ml
 *     · 5 分钟内重复按键被服务端拒绝（409），LED 橙色快闪
 *   - 双键同时按下 → POST /solid → 记录一次辅食
 *     · 下次喂奶将自动设为 120ml
 *     · 企业微信推送辅食通知
 *
 * 编译要求：
 *   - Arduino IDE 开发板选项：M5ChainDualKey
 *   - M5Stack 板管理版本 >= 3.2.4
 *   - M5Unified 库版本 >= 0.2.11
 *   - ArduinoJson (by Benoit Blanchon) >= 7.x
 *   - Adafruit NeoPixel >= 1.15.2
 *
 * LED 反馈说明：
 *   - 待机/WiFi断线：红色常亮
 *   - 发送中：白色一闪
 *   - 喂奶成功（201）：绿色双闪
 *   - 辅食成功（201）：黄色双闪
 *   - 重复提交（409）：橙色快速闪烁
 *   - 认证失败（403）：红色慢闪 3 次
 *   - 连接/SSL失败：紫色双闪
 *
 * 注意：SWITCH_1(G8) / SWITCH_2(G7) 不要设置为 OUTPUT HIGH，否则无法关机
 */

#include "M5Unified.h"
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>
#include <Adafruit_NeoPixel.h>
#include <time.h>
#include "config.h"

// ── Button 对象（M5Unified Button_Class）─────────────────────────────────────
m5::Button_Class Key1;
m5::Button_Class Key2;

// ── RGB LED 对象 ───────────────────────────────────────────────────────────────
Adafruit_NeoPixel LED(NUM_LEDS, LED_SIG_PIN, NEO_RGB + NEO_KHZ800);

// ── LED 颜色辅助函数 ───────────────────────────────────────────────────────────

// 夜间模式缓存（每分钟刷新一次，避免在 LED 调用中阻塞 getLocalTime）
static bool s_nightMode = false;
static unsigned long s_nightModeLastUpdate = 0;

void updateNightMode() {
    unsigned long now = millis();
    if (now - s_nightModeLastUpdate < 60000UL) return;   // 1 分钟更新一次
    s_nightModeLastUpdate = now;
    struct tm t;
    if (getLocalTime(&t, 100)) {   // 最多等 100ms，不阻塞主循环
        s_nightMode = (t.tm_hour >= 0 && t.tm_hour < 6);
    }
}

uint8_t nightScale(uint8_t val) {
    return s_nightMode ? (uint8_t)(val * 5 / 100) : val;
}

void ledSetAll(uint8_t r, uint8_t g, uint8_t b) {
    r = nightScale(r); g = nightScale(g); b = nightScale(b);
    for (int i = 0; i < NUM_LEDS; i++) {
        LED.setPixelColor(i, LED.Color(r, g, b));
    }
    LED.show();
}

void ledOff() {
    for (int i = 0; i < NUM_LEDS; i++) LED.setPixelColor(i, 0);
    LED.show();
}

// 闪烁 n 次，每次亮 onMs 毫秒、灭 offMs 毫秒
void ledBlink(uint8_t r, uint8_t g, uint8_t b, int n, int onMs = 200, int offMs = 150) {
    for (int i = 0; i < n; i++) {
        ledSetAll(r, g, b);   // nightScale 在 ledSetAll 内统一处理
        delay(onMs);
        ledOff();
        if (i < n - 1) delay(offMs);
    }
}

// ── 发送辅食记录请求 ──────────────────────────────────────────────────────────
void onSolidPress() {
    // WiFi 断线自动重连
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[WARN] WiFi lost, reconnecting...");
        ledSetAll(0, 0, 255);
        WiFi.reconnect();
        int wait = 0;
        while (WiFi.status() != WL_CONNECTED && wait < 20) {
            delay(500);
            wait++;
        }
        ledOff();
        if (WiFi.status() != WL_CONNECTED) {
            Serial.println("[ERROR] WiFi reconnect failed");
            ledBlink(255, 0, 0, 3, 150, 100);
            return;
        }
        Serial.println("[INFO] WiFi reconnected");
    }

    // 白色常亮：正在发送
    ledSetAll(255, 255, 255);
    Serial.println("[INFO] Sending solid food request...");

    WiFiClientSecure sslClient;
    sslClient.setInsecure();

    HTTPClient http;
    String url = String(SERVER_URL) + "/solid";
    http.begin(sslClient, url);
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(8000);

    JsonDocument reqDoc;
    reqDoc["device_id"] = DEVICE_ID;
    reqDoc["secret"]    = DEVICE_SECRET;
    String body;
    serializeJson(reqDoc, body);

    int httpCode = http.POST(body);
    String payload = http.getString();
    http.end();

    Serial.printf("[HTTP] Solid code: %d\n", httpCode);
    ledOff();

    if (httpCode == 201) {
        Serial.println("[OK] Solid food recorded");
        ledBlink(255, 200, 0, 2, 300, 150);   // 黄色双闪：辅食成功
    } else if (httpCode == 409) {
        Serial.println("[WARN] Solid duplicate");
        ledBlink(255, 80, 0, 4, 100, 80);     // 橙色快闪：重复
    } else if (httpCode == 403) {
        Serial.println("[ERROR] Auth failed (403)");
        ledBlink(255, 0, 0, 3, 300, 200);     // 红色慢闪：认证失败
    } else if (httpCode <= 0) {
        Serial.printf("[ERROR] Connection failed, code=%d\n", httpCode);
        ledBlink(128, 0, 128, 2, 400, 200);   // 紫色双闪：连接失败
    } else {
        Serial.printf("[ERROR] HTTP %d\n", httpCode);
        ledSetAll(255, 0, 0);
        delay(1000);
        ledOff();
    }
}

// ── 发送喂奶请求 ───────────────────────────────────────────────────────────────
void onButtonPress() {
    // WiFi 断线自动重连（最多等 10 秒）
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[WARN] WiFi lost, reconnecting...");
        ledSetAll(0, 0, 255);
        WiFi.reconnect();
        int wait = 0;
        while (WiFi.status() != WL_CONNECTED && wait < 20) {
            delay(500);
            wait++;
        }
        ledOff();
        if (WiFi.status() != WL_CONNECTED) {
            Serial.println("[ERROR] WiFi reconnect failed");
            ledBlink(255, 0, 0, 3, 150, 100);   // 红色快闪 3 次：无网络
            return;
        }
        Serial.println("[INFO] WiFi reconnected");
    }

    // 白色常亮：正在发送
    ledSetAll(255, 255, 255);
    Serial.println("[INFO] Sending feed request...");

    WiFiClientSecure sslClient;
    sslClient.setInsecure();   // 跳过证书校验（内网/自签名均可用）

    HTTPClient http;
    String url = String(SERVER_URL) + "/feed";
    http.begin(sslClient, url);
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(8000);

    // 构造请求体
    JsonDocument reqDoc;
    reqDoc["device_id"] = DEVICE_ID;
    reqDoc["secret"]    = DEVICE_SECRET;
    String body;
    serializeJson(reqDoc, body);

    int httpCode = http.POST(body);
    String payload = http.getString();
    http.end();

    Serial.printf("[HTTP] Code: %d\n", httpCode);
    Serial.println(payload);

    ledOff();

    if (httpCode == 201) {
        // ── 成功：绿色双闪 ────────────────────────────────────────────────────
        JsonDocument resDoc;
        DeserializationError err = deserializeJson(resDoc, payload);
        if (!err) {
            int amount     = resDoc["record"]["amount_ml"] | 0;
            int todayCount = resDoc["today_count"]         | 0;
            int todayTotal = resDoc["today_total_ml"]      | 0;
            const char* period = resDoc["record"]["period"] | "day";
            Serial.printf("[OK] %dml (%s)  今日第%d次/共%dml\n",
                          amount, period, todayCount, todayTotal);
        }
        ledBlink(0, 255, 0, 2, 300, 150);   // 绿色双闪

    } else if (httpCode == 409) {
        // ── 重复提交：橙色快速闪烁 ───────────────────────────────────────────
        JsonDocument resDoc;
        DeserializationError err = deserializeJson(resDoc, payload);
        int waitSec = (!err) ? (resDoc["wait_seconds"] | 300) : 300;
        int waitMin = (waitSec + 59) / 60;
        Serial.printf("[WARN] Duplicate, wait %d min\n", waitMin);
        ledBlink(255, 80, 0, 4, 100, 80);   // 橙色快速 4 闪

    } else if (httpCode == 403) {
        // ── 认证失败：红色慢闪 3 次 ──────────────────────────────────────────
        Serial.println("[ERROR] Auth failed (403)");
        ledBlink(255, 0, 0, 3, 300, 200);

    } else if (httpCode <= 0) {
        // ── 连接/SSL 错误（负数）：紫色双闪 ─────────────────────────────────────
        Serial.printf("[ERROR] Connection failed, code=%d\n", httpCode);
        ledBlink(128, 0, 128, 2, 400, 200);  // 紫色双闪：网络/SSL 故障

    } else {
        // ── 其他 HTTP 错误：红色单长亮 ───────────────────────────────────────
        Serial.printf("[ERROR] HTTP %d\n", httpCode);
        ledSetAll(255, 0, 0);
        delay(1000);
        ledOff();
    }
}

// ── Setup ─────────────────────────────────────────────────────────────────────
void setup() {
    // M5Unified 初始化（Chain DualKey 无屏幕，M5.begin() 仍用于电源管理）
    M5.begin();
    Serial.begin(115200);

    // 按键引脚（active LOW，内部上拉）
    pinMode(PIN_KEY1, INPUT_PULLUP);
    pinMode(PIN_KEY2, INPUT_PULLUP);

    // RGB LED 初始化：先给 PWR 引脚供电，再初始化 NeoPixel
    pinMode(LED_PWR_PIN, OUTPUT);
    digitalWrite(LED_PWR_PIN, HIGH);
    LED.begin();
    ledOff();

    Serial.println("[INFO] Milk-Link Chain DualKey starting...");

    // WiFi 连接：蓝色慢速闪烁表示连接中
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("[INFO] Connecting WiFi");
    int retry = 0;
    while (WiFi.status() != WL_CONNECTED && retry < 40) {
        ledSetAll(0, 0, 255);
        delay(300);
        ledOff();
        delay(300);
        Serial.print(".");
        retry++;
    }
    Serial.println();

    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("[INFO] WiFi OK: %s\n", WiFi.localIP().toString().c_str());
        // 同步 NTP 时间（用于夜间亮度控制）
        configTime(8 * 3600, 0, "pool.ntp.org", "time.cloudflare.com");
        Serial.println("[INFO] NTP sync...");
        struct tm t;
        if (getLocalTime(&t, 5000)) {
            Serial.printf("[INFO] Time: %02d:%02d\n", t.tm_hour, t.tm_min);
        } else {
            Serial.println("[WARN] NTP sync failed, night mode based on time unavailable");
        }
        // 绿色常亮 1.5 秒表示连接成功
        ledSetAll(0, 255, 0);
        delay(1500);
        ledOff();
    } else {
        Serial.println("[ERROR] WiFi failed");
        // 红色长亮 2 秒表示连接失败
        ledSetAll(255, 0, 0);
        delay(2000);
        ledOff();
    }

    Serial.println("[INFO] Ready. Press Key1 or Key2 to record feeding.");
}

// ── Loop ──────────────────────────────────────────────────────────────────────
static bool s_wifiWasConnected = false;

void loop() {
    uint32_t ms = millis();

    // 更新两个按键状态（M5Unified Button_Class，active LOW → 取反）
    Key1.setRawState(ms, !digitalRead(PIN_KEY1));
    Key2.setRawState(ms, !digitalRead(PIN_KEY2));

    bool wifiOk = (WiFi.status() == WL_CONNECTED);

    // 每分钟更新夜间模式状态（非阻塞）
    updateNightMode();

    // WiFi 状态持续指示：断线 → 红色常亮；恢复 → 熄灭
    if (!wifiOk) {
        ledSetAll(255, 0, 0);   // 红色常亮：无 WiFi
        s_wifiWasConnected = false;
    } else if (!s_wifiWasConnected) {
        // 刚恢复连接：熄灭状态灯
        ledOff();
        s_wifiWasConnected = true;
    }

    // 任意键单次按下 → 等 60ms 判断是否双键同时按下
    if (Key1.wasPressed() || Key2.wasPressed()) {
        delay(60);
        bool k1held = !digitalRead(PIN_KEY1);
        bool k2held = !digitalRead(PIN_KEY2);

        if (k1held && k2held) {
            Serial.println("[INFO] Dual key pressed → solid food");
            onSolidPress();
        } else {
            Serial.println("[INFO] Single key pressed → milk");
            onButtonPress();
        }
    }

    delay(10);
}
