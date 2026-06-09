#include <ESP8266WiFi.h>
#include <WiFiUdp.h>

// ===== CẤU HÌNH MẠNG =====
const char* ssid     = "P 201";
const char* password = "66668888";
IPAddress rpiIP(192, 168, 1, 238);
const unsigned int rpiPort   = 4444;
const unsigned int localPort = 5555;

WiFiUDP udp;

// ===== THAM SỐ HỆ THỐNG =====
const unsigned long WINDOW_MS         = 2000;
const unsigned long ACK_TIMEOUT_MS    = 1900;
const int           PACKETS_PER_WINDOW = 50;
const int           PAYLOAD_SIZE_SEND  = 64;

const unsigned long SYNC_INTERVAL_MS = 300000; // 5 phút đồng bộ lại 1 lần
unsigned long lastSyncTime = 0;

// ===== TRẠNG THÁI HOẠT ĐỘNG =====
enum Decision { SEND = 0, COMPRESS = 1, WAIT = 2 };
unsigned int windowID = 0;

// ===== ĐỒNG BỘ THỜI GIAN (Thuần túy số nguyên không dấu 32-bit) =====
uint32_t timeOffset      = 0;
bool     timeSynced      = false;
unsigned long windowStartTime = 0;


// ===== HÀM GỬI GÓI TIN =====
void sendPacket(int packetIndex, int totalPackets, const uint8_t* payload, size_t payloadLen) {
  uint8_t buffer[10 + payloadLen];

  // window_id (2 bytes)
  buffer[0] = (windowID >> 8) & 0xFF;
  buffer[1] =  windowID       & 0xFF;

  // seq, total (1 byte mỗi)
  buffer[2] = (uint8_t)packetIndex;
  buffer[3] = (uint8_t)totalPackets;

  // Tính toán timestamp dựa trên offset không dấu (Tận dụng tính chất tràn số bù 2 tự nhiên)
  uint32_t timestamp = (uint32_t)millis() + timeOffset;
  buffer[4] = (timestamp >> 24) & 0xFF;
  buffer[5] = (timestamp >> 16) & 0xFF;
  buffer[6] = (timestamp >>  8) & 0xFF;
  buffer[7] =  timestamp        & 0xFF;

  // payload_len (2 bytes)
  buffer[8] = (payloadLen >> 8) & 0xFF;
  buffer[9] =  payloadLen       & 0xFF;

  memcpy(buffer + 10, payload, payloadLen);

  udp.beginPacket(rpiIP, rpiPort);
  udp.write(buffer, sizeof(buffer));
  udp.endPacket();
}


// ===== HÀM NHẬN ACK =====
void receiveAndDiscardACK() {
  unsigned long deadline = millis() + ACK_TIMEOUT_MS;
  while (millis() < deadline) {
    int packetSize = udp.parsePacket();
    if (packetSize >= 3) {
      uint8_t ackBuffer[3];
      udp.read(ackBuffer, 3);
      unsigned int ackWindowID = (ackBuffer[0] << 8) | ackBuffer[1];
      if (ackWindowID == windowID) {
        Decision receivedDecision = (Decision)ackBuffer[2];
        Serial.printf("ACK received (ignored): decision=%d, always SEND\n", receivedDecision);
        return;
      }
    }
  }
  Serial.println("ACK timeout (continuing SEND regardless)");
}


// ===== HÀM ĐỒNG BỘ THỜI GIAN NÂNG CẤP (Burst Cristian's Algorithm) =====
void synchronizeTime() {
  Serial.println("\n--- Starting Burst SYNC (Cristian's Algorithm - Best RTT) ---");

  const int numAttempts = 10;      // Số lượng gói tin gửi trong 1 đợt burst
  uint32_t  minRTT = 0xFFFFFFFF;   // Giá trị RTT nhỏ nhất tìm thấy
  uint32_t  bestOffset = 0;
  bool      syncSuccess = false;

  for (int i = 0; i < numAttempts; i++) {
    // Xóa sạch bộ đệm UDP cũ nếu còn sót lại dữ liệu nhiễu trước khi ping
    while (udp.parsePacket() > 0) { udp.flush(); }

    uint32_t t_start = millis();

    udp.beginPacket(rpiIP, rpiPort);
    udp.write('S');
    udp.endPacket();

    // Đợi phản hồi với timeout ngắn (150ms mỗi gói)
    unsigned long syncDeadline = millis() + 150;
    while (millis() < syncDeadline) {
      int packetSize = udp.parsePacket();
      if (packetSize == 4) {
        uint32_t t_end = millis();

        uint32_t rpiTimestamp;
        udp.read((uint8_t*)&rpiTimestamp, 4);

        // Đảo Endian từ RPi (Big-Endian) sang ESP (Little-Endian)
        rpiTimestamp = ((rpiTimestamp & 0xFF000000) >> 24) |
                       ((rpiTimestamp & 0x00FF0000) >>  8) |
                       ((rpiTimestamp & 0x0000FF00) <<  8) |
                       ((rpiTimestamp & 0x000000FF) << 24);

        uint32_t rtt = t_end - t_start;

        // Tính toán Offset theo lý thuyết đối xứng mạng tại RTT/2
        uint32_t estEspTime = t_end - (rtt / 2);
        uint32_t currentOffset = rpiTimestamp - estEspTime;

        Serial.printf("  [Ping %2d] RTT = %d ms | Offset = %u\n", i + 1, rtt, currentOffset);

        // LỰA CHỌN: Chỉ lấy Offset của gói tin có RTT ngắn nhất
        if (rtt < minRTT) {
          minRTT = rtt;
          bestOffset = currentOffset;
          syncSuccess = true;
        }
        break;
      }
    }
    delay(15); // Nghỉ ngắn giữa các lần ping để tránh nghẽn hàng đợi trên Router Wi-Fi
  }

  if (syncSuccess) {
    timeOffset = bestOffset;
    timeSynced = true;
    Serial.printf(">>> SYNC SUCCESSFUL! Chosen RTT: %u ms | TimeOffset: %u\n\n", minRTT, timeOffset);
  } else {
    Serial.println(">>> SYNC FAILED! Keeping previous settings.\n");
  }
}


void setup() {
  Serial.begin(115200);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected");
  Serial.print("ESP8266 IP: ");
  Serial.println(WiFi.localIP());

  udp.begin(localPort);

  synchronizeTime();
  lastSyncTime    = millis();
  windowStartTime = millis();
}


void loop() {
  // --- ĐỒNG BỘ ĐỊNH KỲ ĐỂ CHỐNG TRÔI THẠCH ANH ---
  if (millis() - lastSyncTime >= SYNC_INTERVAL_MS) {
    synchronizeTime();
    lastSyncTime = millis();
  }

  // --- QUẢN LÝ CỬA SỔ TRUYỀN DỮ LIỆU ---
  if (millis() - windowStartTime >= WINDOW_MS ) {
    windowStartTime += WINDOW_MS;
    windowID++;

    uint8_t dummyPayload[PAYLOAD_SIZE_SEND];
    for (int i = 0; i < PAYLOAD_SIZE_SEND; i++) dummyPayload[i] = random(256);

    for (int i = 0; i < PACKETS_PER_WINDOW; i++) {
      sendPacket(i, PACKETS_PER_WINDOW, dummyPayload, PAYLOAD_SIZE_SEND);
      delay(1);
    }
    Serial.printf("[Window %d] Sent %d packets\n", windowID, PACKETS_PER_WINDOW);

    receiveAndDiscardACK();
  }

  delay(1);
}