/**
 * esp8266_send.ino
 * Chạy trên ESP8266 (NodeMCU, Wemos D1 Mini, etc.)
 *
 * Luồng:
 *  1. Kết nối WiFi
 *  2. Handshake TCP với clock offset calibration
 *  3. Gửi 100 UDP packet: seq(4B) | timestamp(8B) | payload(512B)
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

// Mã hóa XOR - Key 16 bytes (128-bit)
const uint8_t ENCRYPTION_KEY[16] = {
    0x2B, 0x7E, 0x15, 0x16, 0x28, 0xAE, 0xD2, 0xA6,
    0xAB, 0xF7, 0x15, 0x88, 0x09, 0xCF, 0x4F, 0x3C
};
    
WiFiUDP      udp;
WiFiClient   tcpClient;
int          cycleCount = 0;  // Đếm số chu kỳ đo
int64_t      clockOffsetUs = 0;  // Pi epoch microseconds - ESP micros()

// ─── Tiện ích: đóng gói uint64_t (big-endian) ─────────────────────────────
void packUint64BE(uint8_t* buf, uint64_t val) {
    for (int i = 0; i < 8; i++) {
        buf[7 - i] = (val >> (i * 8)) & 0xFF;
    }
}

// ─── Tiện ích: giải mã uint64_t (big-endian) ──────────────────────────────
uint64_t unpackUint64BE(const uint8_t* buf) {
    uint64_t val = 0;
    for (int i = 0; i < 8; i++) {
        val |= ((uint64_t)buf[7 - i]) << (i * 8);
    }
    return val;
}

// ─── Mã hóa XOR với key ───────────────────────────────────────────────────
void xorEncrypt(uint8_t* data, int len) {
    for (int i = 0; i < len; i++) {
        data[i] ^= ENCRYPTION_KEY[i % 16];  // XOR với key (lặp lại key nếu data dài hơn)
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

// ─── Handshake TCP với Clock Offset Calibration ───────────────────────────
bool handshake() {
    for (int attempt = 1; attempt <= MAX_RETRIES; attempt++) {
        Serial.printf("[ESP8266] Handshake lần %d/%d...\n", attempt, MAX_RETRIES);

        if (!tcpClient.connect(SERVER_IP, TCP_PORT)) {
            Serial.println("[ESP8266] Không kết nối TCP được.");
            delay(2000);
            continue;
        }

        // Gửi SYN
        tcpClient.write((const uint8_t*)"SYN", 3);
        tcpClient.flush();

        // Chờ ACK + Pi timestamp tối đa 5 giây
        unsigned long t0 = millis();
        while (tcpClient.available() < 11 && millis() - t0 < 5000) {  // ACK(3) + uint64(8)
            delay(10);
            yield();
        }

        if (tcpClient.available() >= 11) {
            // Đọc ACK (3 bytes)
            char ack[4] = {0};
            tcpClient.readBytes((uint8_t*)ack, 3);
            
            if (strncmp(ack, "ACK", 3) != 0) {
                Serial.printf("[ESP8266] Phản hồi không hợp lệ: %s\n", ack);
                tcpClient.stop();
                delay(2000);
                continue;
            }
            
            // Đọc Pi timestamp (8 bytes, big-endian uint64 microseconds)
            uint8_t pi_ts_buf[8];
            tcpClient.readBytes(pi_ts_buf, 8);
            uint64_t pi_time_us = unpackUint64BE(pi_ts_buf);
            
            // Quy đổi micros() của ESP sang cùng mốc thời gian với Pi.
            uint64_t esp_time_us = micros();
            clockOffsetUs = (int64_t)pi_time_us - (int64_t)esp_time_us;
            
            tcpClient.stop();
            
            Serial.printf("[ESP8266] Handshake OK\n");
            Serial.printf("[ESP8266] Pi timestamp: %llu us\n", pi_time_us);
            Serial.printf("[ESP8266] ESP timestamp: %llu us\n", esp_time_us);
            Serial.printf("[ESP8266] Clock offset: %lld us\n\n", (long long)clockOffsetUs);
            return true;
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
    // Header: seq(4B big-endian uint32) + timestamp(8B big-endian uint64 microseconds)
    const int HEADER_LEN = 4 + 8;
    const int PKT_LEN    = HEADER_LEN + PAYLOAD_LEN;
    uint8_t   pkt[PKT_LEN];

    // Khởi tạo UDP
    udp.begin(8888);  // Local port bất kỳ

    Serial.printf("[ESP8266] Gửi %d packets tới %s:%d\n", TOTAL_PKTS, SERVER_IP, UDP_PORT);
    Serial.printf("[ESP8266] Payload size: %d bytes | Interval: %dms\n\n", PAYLOAD_LEN, INTERVAL_MS);

    for (int seq = 0; seq < TOTAL_PKTS; seq++) {
        // Timestamp gửi theo mốc thời gian của Pi để Pi tính delay = recv - send.
        uint64_t ts_us = (uint64_t)((int64_t)micros() + clockOffsetUs);

        // Đóng gói header big-endian
        pkt[0] = (seq >> 24) & 0xFF;
        pkt[1] = (seq >> 16) & 0xFF;
        pkt[2] = (seq >>  8) & 0xFF;
        pkt[3] = (seq      ) & 0xFF;
        packUint64BE(&pkt[4], ts_us);

        // Payload
        memcpy(&pkt[HEADER_LEN], payload, PAYLOAD_LEN);

        // *** MÃ HÓA PAYLOAD (chỉ mã hóa payload, không mã hóa header) ***
        xorEncrypt(&pkt[HEADER_LEN], PAYLOAD_LEN);

        // Gửi UDP
        udp.beginPacket(SERVER_IP, UDP_PORT);
        size_t written = udp.write(pkt, PKT_LEN);
        int result = udp.endPacket();

        if (result == 1) {
            Serial.printf("  [SEND] seq=%03d  ts=%llu us  ✓\n", seq, ts_us);
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
    Serial.println("  Clock Offset Calibration");
    Serial.println("══════════════════════════════");

    // Khởi tạo payload 0xAA
    memset(payload, 0xAA, PAYLOAD_LEN);

    connectWiFi();
}

void loop() {
    cycleCount++;
    
    // Handshake TCP để thiết lập kênh truyền và tính clock offset
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
