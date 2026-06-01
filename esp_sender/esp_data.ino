#include <WiFi.h>
#include <WiFiUdp.h>

// ===== CẤU HÌNH MẠNG =====
const char* ssid = "P 201";
const char* password = "66668888";
IPAddress rpiIP(192, 168, 1, 238);
const unsigned int rpiPort = 4444;
const unsigned int localPort = 5555;

WiFiUDP udp;

// ===== THAM SỐ HỆ THỐNG =====
const unsigned long WINDOW_MS = 1000;
const unsigned long ACK_TIMEOUT_MS = 100;
const int PACKETS_PER_WINDOW = 50;
const int PAYLOAD_SIZE_SEND = 64;       // Luôn dùng kích thước SEND

const unsigned long SYNC_INTERVAL_MS = 300000;
unsigned long lastSyncTime = 0;

// ===== TRẠNG THÁI HOẠT ĐỘNG =====
enum Decision { SEND = 0, COMPRESS = 1, WAIT = 2 };
unsigned int windowID = 0;

// ===== ĐỒNG BỘ THỜI GIAN =====
int32_t timeOffset = 0;
bool timeSynced = false;
unsigned long windowStartTime = 0;

// ===== HÀM GỬI GÓI TIN =====
void sendPacket(int packetIndex, int totalPackets, const uint8_t* payload, size_t payloadLen) {
  uint8_t buffer[10 + payloadLen];
  buffer[0] = (windowID >> 8) & 0xFF;
  buffer[1] = windowID & 0xFF;
  buffer[2] = packetIndex;
  buffer[3] = totalPackets;

  uint32_t timestamp = millis() + timeOffset;
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

// ===== HÀM NHẬN ACK (vẫn nhận nhưng BỎ QUA lệnh điều khiển) =====
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
        // Nhận ACK để giữ giao thức, nhưng KHÔNG áp dụng lệnh
        Serial.printf("ACK received (ignored): decision=%d, always SEND\n", receivedDecision);
        return;
      }
    }
  }
  Serial.println("ACK timeout (continuing SEND regardless)");
}

// ===== HÀM ĐỒNG BỘ THỜI GIAN =====
void synchronizeTime() {
  Serial.println("Sending SYNC packet (NTP Style)...");

  unsigned long t_start = millis();

  udp.beginPacket(rpiIP, rpiPort);
  udp.write('S');
  udp.endPacket();

  unsigned long syncDeadline = millis() + 2000;
  while (millis() < syncDeadline) {
    int packetSize = udp.parsePacket();
    if (packetSize == 4) {
      unsigned long t_end = millis();

      uint32_t rpiTimestamp;
      udp.read((uint8_t*)&rpiTimestamp, 4);

      unsigned long rtt = t_end - t_start;
      timeOffset = rpiTimestamp - (t_end - (rtt / 2));
      timeSynced = true;

      Serial.printf("Time synced! RTT = %lu ms, Offset = %d ms\n", rtt, timeOffset);
      return;
    }
  }
  Serial.println("Time sync failed!");
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

    // Tạo payload ngẫu nhiên, luôn dùng PAYLOAD_SIZE_SEND
    uint8_t dummyPayload[PAYLOAD_SIZE_SEND];
    for (int i = 0; i < PAYLOAD_SIZE_SEND; i++) dummyPayload[i] = random(256);

    // Luôn gửi đủ 50 gói, bất kể ACK nói gì
    for (int i = 0; i < PACKETS_PER_WINDOW; i++) {
      sendPacket(i, PACKETS_PER_WINDOW, dummyPayload, PAYLOAD_SIZE_SEND);
      delay(1);
    }
    Serial.printf("[Window %d] Sent %d packets x %d bytes\n",
                  windowID, PACKETS_PER_WINDOW, PAYLOAD_SIZE_SEND);

    // Vẫn nhận ACK để duy trì giao thức, nhưng bỏ qua lệnh điều khiển
    receiveAndDiscardACK();
  }

  delay(1);
}