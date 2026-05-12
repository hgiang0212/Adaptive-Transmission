# WiFi Quality Measurement System

Hệ thống đo lường chất lượng WiFi: Packet Loss, Delay, Jitter, BER

## Kiến trúc

```
ESP8266 ──WiFi──► Raspberry Pi
(sender)          (receiver)
```

## Cài đặt

### ESP8266
1. Mở `esp8266_send/esp8266_send.ino` trong Arduino IDE
2. Sửa cấu hình:
```cpp
const char* WIFI_SSID = "YOUR_WIFI";
const char* WIFI_PASS = "YOUR_PASSWORD";
const char* SERVER_IP = "192.168.1.206";  // IP của Pi
```
3. Chọn board: **NodeMCU 1.0 (ESP-12E Module)**
4. Upload

### Raspberry Pi
```bash
cd pi_receiver
python pi_receiver_fixed.py
```

## Các chỉ số đo được

- **Packet Loss** (%)
- **Delay** (ms)
- **Jitter** (ms)
- **BER** (Bit Error Rate)
- **Throughput** (Mbps)

## Kết quả

- `logs/log_YYYYMMDD_HHMMSS.csv` - Log chi tiết
- `summary.csv` - Tổng hợp tất cả chu kỳ

## Xem biểu đồ

```bash
python view_summary.py
```

## Tăng nhiễu để test

### Vật lý
- Tăng khoảng cách ESP ↔ Pi
- Đặt chướng ngại vật (tường, tủ sắt)
- Đặt gần lò vi sóng

### Phần mềm
Trong `esp8266_send.ino`:
```cpp
const int INTERVAL_MS = 10;    // Gửi nhanh → tắc nghẽn
const int PAYLOAD_LEN = 512;   // Packet lớn → dễ lỗi
```

## License

MIT
