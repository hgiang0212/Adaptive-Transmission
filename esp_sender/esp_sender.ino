#include <ESP8266WiFi.h>
#include <WiFiUdp.h>

// ===== CẤU HÌNH MẠNG =====
const char* ssid = "P 201";
const char* password = "66668888";
IPAddress rpiIP(192, 168, 1, 238);  // Địa chỉ IP của RPi
const unsigned int rpiPort = 4444;      // Cổng RPi nhận dữ liệu
const unsigned int localPort = 5555;    // Cổng ESP32 nhận ACK

WiFiUDP udp;

// ===== THAM SỐ HỆ THỐNG =====
const unsigned long WINDOW_MS = 2000;   // Cửa sổ 1 giây
const unsigned long ACK_TIMEOUT_MS = 100; // Timeout chờ ACK

const int PACKETS_PER_WINDOW = 50;

const int PAYLOAD_SIZE_SEND = 64;       // Kích thước payload khi SEND
const int PAYLOAD_SIZE_COMPRESS = 32;   // Kích thước payload khi COMPRESS

const unsigned long SYNC_INTERVAL_MS = 300000;
unsigned long lastSyncTime = 0;

// ===== TRẠNG THÁI HOẠT ĐỘNG =====
enum Decision { SEND = 0, COMPRESS = 1, WAIT = 2 };
Decision currentDecision = SEND;
unsigned int windowID = 0;

// ===== ĐỒNG BỘ THỜI GIAN =====
// FIX: Dùng uint32_t để chống lỗi tính toán sinh âm trên vi điều khiển
uint32_t timeOffset = 0;
bool timeSynced = false;
unsigned long windowStartTime = 0;

// ===== HÀM GỬI GÓI TIN =====
void sendPacket(int packetIndex, int totalPackets, const uint8_t* payload, size_t payloadLen) {
  uint8_t buffer[10 + payloadLen];
  buffer[0] = (windowID >> 8) & 0xFF;
  buffer[1] = windowID & 0xFF;
  buffer[2] = packetIndex;
  buffer[3] = totalPackets;

  // Lấy nhãn thời gian NTP chuẩn qua mạng (Đã khử bù 2 tự động)
  uint32_t timestamp = (uint32_t)millis() + timeOffset;
  buffer[4] = (timestamp >> 24) & 0xFF;
  buffer[5] = (timestamp >> 16) & 0xFF;
  buffer[6] = (timestamp >> 8) & 0xFF;
  buffer[7] = timestamp & 0xFF;

  buffer[8] = (payloadLen >> 8) & 0xFF;
  buffer[9] = payloadLen & 0xFF;
  memcpy(buffer + 10, payload, payloadLen);

  udp.beginPacket(rpiIP, rpiPort);
  udp.write(buffer, sizeof(buffer));
  udp.endPacket();
}

// ===== HÀM NHẬN ACK =====
bool receiveACK(Decision &newDecision) {
  unsigned long deadline = millis() + ACK_TIMEOUT_MS;
  while (millis() < deadline) {
    int packetSize = udp.parsePacket();
    if (packetSize >= 3) {
      uint8_t ackBuffer[3];
      udp.read(ackBuffer, 3);
      unsigned int ackWindowID = (ackBuffer[0] << 8) | ackBuffer[1];
      if (ackWindowID == windowID) {
        newDecision = (Decision)ackBuffer[2];
        Serial.printf("ACK received: decision=%d\n", newDecision);
        return true;
      }
    }
  }
  Serial.println("ACK timeout");
  return false;
}

// ===== HÀM ĐỒNG BỘ THỜI GIAN (Thuật toán Cristian 10 Burst) =====
void synchronizeTime() {
  Serial.println("Starting SYNC packet burst...");

  const int numAttempts = 10;
  uint32_t minRTT = 0xFFFFFFFF;
  uint32_t bestOffset = 0;
  bool syncSuccess = false;

  for (int i = 0; i < numAttempts; i++) {
    // Dọn rác bộ đệm
    while (udp.parsePacket() > 0) { udp.flush(); }

    uint32_t t_start = millis();
    udp.beginPacket(rpiIP, rpiPort);
    udp.write('S');
    udp.endPacket();

    unsigned long syncDeadline = millis() + 150;
    while (millis() < syncDeadline) {
      int packetSize = udp.parsePacket();
      if (packetSize == 4) {
        uint32_t t_end = millis();

        uint32_t rpiTimestamp;
        udp.read((uint8_t*)&rpiTimestamp, 4);

        // FIX Endianness: Đảo chiều Byte từ Python (Big-Endian) sang ESP32 (Little-Endian)
        rpiTimestamp = ((rpiTimestamp & 0xFF000000) >> 24) |
                       ((rpiTimestamp & 0x00FF0000) >>  8) |
                       ((rpiTimestamp & 0x0000FF00) <<  8) |
                       ((rpiTimestamp & 0x000000FF) << 24);

        uint32_t rtt = t_end - t_start;
        uint32_t currentOffset = rpiTimestamp - (t_end - (rtt / 2));

        if (rtt < minRTT) {
          minRTT = rtt;
          bestOffset = currentOffset;
          syncSuccess = true;
        }
        break;
      }
    }
    delay(10); // Ngăn rác Router
  }

  if (syncSuccess) {
    timeOffset = bestOffset;
    timeSynced = true;
    Serial.printf("Time synced! Chosen RTT = %u ms, Offset = %u\n", minRTT, timeOffset);
  } else {
    Serial.println("Time sync failed! Keeping old offset.");
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
  Serial.print("ESP32 IP: ");
  Serial.println(WiFi.localIP());

  udp.begin(localPort);

  // Đồng bộ thời gian ban đầu
  synchronizeTime();
  lastSyncTime = millis();

  windowStartTime = millis();
}

void loop() {
  // --- ĐỒNG BỘ ĐỊNH KỲ CHỐNG TRÔI ĐỒNG HỒ ---
  if (millis() - lastSyncTime >= SYNC_INTERVAL_MS) {
    synchronizeTime();
    lastSyncTime = millis();
  }

  // --- QUẢN LÝ CỬA SỔ TRUYỀN DỮ LIỆU ---
  if (millis() - windowStartTime >= WINDOW_MS) {
    windowStartTime += WINDOW_MS;
    windowID++;

    size_t payloadSize = (currentDecision == COMPRESS) ?
                         PAYLOAD_SIZE_COMPRESS : PAYLOAD_SIZE_SEND;
    uint8_t dummyPayload[PAYLOAD_SIZE_SEND];
    for (int i = 0; i < PAYLOAD_SIZE_SEND; i++) dummyPayload[i] = random(256);

    // Gửi cụm (Burst) 50 gói tin
    if (currentDecision != WAIT) {
      for (int i = 0; i < PACKETS_PER_WINDOW; i++) {
        sendPacket(i, PACKETS_PER_WINDOW, dummyPayload, payloadSize);
        delay(1);
      }
      Serial.printf("Sent %d packets (payload=%d bytes)\n", PACKETS_PER_WINDOW, payloadSize);
    } else {
      Serial.println("WAIT: No data sent this window");
    }

    // Chờ nhận lệnh ACK phản hồi từ RPi
    Decision newDecision;
    if (receiveACK(newDecision)) {
      currentDecision = newDecision;
    }
  }
  delay(1);
}