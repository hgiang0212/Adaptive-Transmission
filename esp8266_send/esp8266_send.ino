/**
 * esp8266_send.ino
 * Chạy trên ESP8266 (NodeMCU, Wemos D1 Mini, etc.)
 *
 * Luồng:
 *  1. Kết nối WiFi
 *  2. Handshake TCP: gửi "SYN" → chờ "ACK" từ PC
 *  3. Gửi 100 UDP packet: seq(4B) | timestamp(8B) | payload(128B)
 *
 * Board: NodeMCU 1.0 (ESP-12E Module) 
 * Framework: Arduino (ESP8266 Arduino Core)
 */

#include <ESP8266WiFi.h>
#include <WiFiUdp.h>

// ═══════════════════════════════════════════
//  CẤU HÌNH — sửa trước khi nạp firmware
// ═══════════════════════════════════════════
const char* WIFI_SSID    = "B5 405";
const char* WIFI_PASS    = "vinamilk";

const char* SERVER_IP    = "192.168.1.206";  // IP WiFi của Pi
const uint16_t TCP_PORT  = 5006;             // handshake
const uint16_t UDP_PORT  = 5005;             // data
// ═══════════════════════════════════════════

const int    TOTAL_PKTS  = 100;
const int    INTERVAL_MS = 10;    // Giảm từ 100ms → 10ms (gửi nhanh gấp 10 lần)
const int    MAX_RETRIES = 5;
const int    CYCLE_DELAY = 30;    // Chờ 30 giây giữa các chu kỳ đo

// Payload cố định 512 byte = 0xAA (packet lớn → dễ lỗi hơn)
const int    PAYLOAD_LEN = 512;
uint8_t      payload[PAYLOAD_LEN];

WiFiUDP      udp;
WiFiClient   tcpClient;
int          cycleCount = 0;  // Đếm số chu kỳ đo

// ─── Tiện ích: đóng gói double (big-endian) ───────────────────────────────
void packDoubleBE(uint8_t* buf, double val) {
    uint8_t* src = (uint8_t*)&val;
    // ESP8266 là little-endian, đảo byte
    for (int i = 0; i < 8; i++) {
        buf[i] = src[7 - i];
    }
}

// ─── Kết nối WiFi ─────────────────────────────────────────────────────────
void connectWiFi() {
    Serial.printf("[ESP8266] Kết nối WiFi: %s\n", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASS);

    int tries = 0;
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(".");
        if (++tries > 40) {
            Serial.println("\n[ESP8266] Không kết nối được WiFi. Restart...");
            ESP.restart();
        }
    }
    Serial.printf("\n[ESP8266] WiFi OK — IP: %s\n", WiFi.localIP().toString().c_str());
}

// ─── Handshake TCP ────────────────────────────────────────────────────────
bool handshake() {
    for (int attempt = 1; attempt <= MAX_RETRIES; attempt++) {
        Serial.printf("[ESP8266] Handshake lần %d/%d...\n", attempt, MAX_RETRIES);

        if (!tcpClient.connect(SERVER_IP, TCP_PORT)) {
            Serial.println("[ESP8266] Không kết nối TCP được.");
            delay(2000);
            continue;
        }

        tcpClient.write((const uint8_t*)"SYN", 3);
        tcpClient.flush();

        // Chờ ACK tối đa 5 giây
        unsigned long t0 = millis();
        while (tcpClient.available() == 0 && millis() - t0 < 5000) {
            delay(10);
            yield();  // ESP8266 cần yield() để tránh watchdog reset
        }

        if (tcpClient.available() >= 3) {
            char buf[8] = {0};
            tcpClient.readBytes((uint8_t*)buf, 3);
            tcpClient.stop();
            if (strncmp(buf, "ACK", 3) == 0) {
                Serial.println("[ESP8266] Handshake OK — bắt đầu gửi data\n");
                return true;
            }
            Serial.printf("[ESP8266] Phản hồi không hợp lệ: %s\n", buf);
        } else {
            Serial.println("[ESP8266] Timeout chờ ACK.");
            tcpClient.stop();
        }
        delay(2000);
    }
    return false;
}

// ─── Gửi UDP data ─────────────────────────────────────────────────────────
void sendData() {
    // Header: seq(4B big-endian uint32) + timestamp(8B big-endian double)
    const int HEADER_LEN = 4 + 8;
    const int PKT_LEN    = HEADER_LEN + PAYLOAD_LEN;
    uint8_t   pkt[PKT_LEN];

    // Khởi tạo UDP
    udp.begin(8888);  // Local port bất kỳ

    Serial.printf("[ESP8266] Gửi %d packets tới %s:%d\n", TOTAL_PKTS, SERVER_IP, UDP_PORT);
    Serial.printf("[ESP8266] Payload size: %d bytes | Interval: %dms\n\n", PAYLOAD_LEN, INTERVAL_MS);

    for (int seq = 0; seq < TOTAL_PKTS; seq++) {
        // Mô phỏng packet loss: 10% không gửi
        if (random(100) < 10) {
            Serial.printf("  [DROP] seq=%03d  (simulated loss)\n", seq);
            delay(INTERVAL_MS);
            yield();
            continue;
        }
        
        // Lấy timestamp (giây, dấu phẩy động)
        double ts = (double)millis() / 1000.0;

        // Đóng gói header big-endian
        pkt[0] = (seq >> 24) & 0xFF;
        pkt[1] = (seq >> 16) & 0xFF;
        pkt[2] = (seq >>  8) & 0xFF;
        pkt[3] = (seq      ) & 0xFF;
        packDoubleBE(&pkt[4], ts);

        // Payload
        memcpy(&pkt[HEADER_LEN], payload, PAYLOAD_LEN);

        // Thêm nhiễu giả: flip ngẫu nhiên 1-5 bit
        if (random(100) < 20) {  // 20% packet có lỗi bit
            int num_errors = random(1, 6);  // 1-5 bit lỗi
            for (int i = 0; i < num_errors; i++) {
                int byte_pos = HEADER_LEN + random(PAYLOAD_LEN);
                int bit_pos = random(8);
                pkt[byte_pos] ^= (1 << bit_pos);  // Flip bit
            }
        }

        // Gửi UDP
        udp.beginPacket(SERVER_IP, UDP_PORT);
        size_t written = udp.write(pkt, PKT_LEN);
        int result = udp.endPacket();

        if (result == 1) {
            Serial.printf("  [SEND] seq=%03d  ts=%.3f  ✓\n", seq, ts);
        } else {
            Serial.printf("  [ERR]  seq=%03d  gửi thất bại (code=%d)\n", seq, result);
        }
        
        delay(INTERVAL_MS);
        yield();  // Quan trọng: tránh watchdog reset
    }

    udp.stop();
    Serial.printf("\n[ESP8266] Đã gửi xong %d packets.\n", TOTAL_PKTS);
}

// ─── Setup & Loop ─────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n══════════════════════════════");
    Serial.println("  ESP8266 WiFi Sender");
    Serial.println("  Chế độ: Chạy liên tục");
    Serial.println("══════════════════════════════");

    // Khởi tạo payload 0xAA
    memset(payload, 0xAA, PAYLOAD_LEN);

    connectWiFi();
}

void loop() {
    cycleCount++;
    
    // Handshake TCP để thiết lập kênh truyền
    Serial.println("\n════════════════════════════════════════");
    Serial.printf("  Chu kỳ đo #%d\n", cycleCount);
    Serial.println("════════════════════════════════════════");
    
    if (!handshake()) {
        Serial.println("[ESP8266] Handshake thất bại. Thử lại sau 10s...");
        delay(10000);
        cycleCount--;  // Không tính chu kỳ thất bại
        return;  // Quay lại đầu loop
    }

    // Gửi data
    sendData();
    
    // Chờ trước khi đo lại
    Serial.printf("\n[ESP8266] Hoàn thành chu kỳ #%d. Chờ %ds...\n", cycleCount, CYCLE_DELAY);
    for (int i = CYCLE_DELAY; i > 0; i--) {
        if (i % 5 == 0 || i <= 3) {  // Chỉ in mỗi 5 giây hoặc 3 giây cuối
            Serial.printf("  Còn %d giây...\n", i);
        }
        delay(1000);
        yield();
    }
}
