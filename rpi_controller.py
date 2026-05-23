import socket
import struct
import time
import numpy as np
from collections import deque
import torch
import torch.nn as nn

# ===== Định nghĩa kiến trúc mô hình =====
class GRUNet(nn.Module):
    def __init__(self, input_size=3, hidden_size=16, num_classes=3):
        super().__init__()
        self.gru = nn.GRU(input_size, hidden_size, batch_first=True)
        self.fc = nn.Linear(hidden_size, num_classes)
    def forward(self, x):
        out, _ = self.gru(x)
        return self.fc(out[:, -1, :])

# ===== Cấu hình mạng =====
UDP_IP = "0.0.0.0"
UDP_PORT_DATA = 4444
UDP_PORT_ACK = 5555
ESP32_IP = "192.168.1.50"   # Hãy sửa thành địa chỉ IP thực tế của ESP32
ESP32_PORT_ACK = 5555

WINDOW_SIZE = 10
FEATURES = 3

# ===== Load model và các tham số chuẩn hoá =====
checkpoint = torch.load('gru_model.pt', map_location=torch.device('cpu'))
model = GRUNet(input_size=checkpoint['input_size'],
               hidden_size=checkpoint['hidden_size'],
               num_classes=checkpoint['num_classes'])
model.load_state_dict(checkpoint['model_state_dict'])
model.eval()

mins = checkpoint['mins'].numpy()
maxs = checkpoint['maxs'].numpy()
maxs[maxs == mins] = 1.0

# ===== Biến toàn cục =====
window_buffer = deque(maxlen=WINDOW_SIZE)
current_window_id = None
packets_this_window = []

# Sockets
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT_DATA))
sock.settimeout(0.1)
ack_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send_ack(window_id, decision):
    msg = struct.pack('>HB', window_id, decision)
    ack_sock.sendto(msg, (ESP32_IP, ESP32_PORT_ACK))
    print(f"Sent ACK: window={window_id}, decision={decision}")

# --- ĐÃ SỬA LỖI: Hàm không còn bị chặn, nhận addr để phản hồi ngay tắp lự ---
def handle_sync(addr):
    ts = int(time.time() * 1000) & 0xFFFFFFFF
    sock.sendto(struct.pack('>I', ts), addr)
    print(f"SYNC: sent timestamp {ts} to {addr}")

def process_packet(data):
    if len(data) < 10:
        return None
    window_id = (data[0] << 8) | data[1]
    seq = data[2]
    total = data[3]
    timestamp = (data[4] << 24) | (data[5] << 16) | (data[6] << 8) | data[7]
    payload_len = (data[8] << 8) | data[9]
    return window_id, seq, total, timestamp, payload_len

def process_window(window_id, packets):
    if not packets:
        return None
    # Xác định tổng số gói dựa trên thông báo cấu trúc gói tin (Header trường total)
    total_packets = packets[0][1]
    received = len(packets)
    packet_loss = 1.0 - (received / total_packets) if total_packets > 0 else 0.0

    now_ms = int(time.time() * 1000)
    delays = [max(0, now_ms - ts) for _, _, ts, _ in packets]
    avg_delay = np.mean(delays) if delays else 0.0

    total_bytes = sum(10 + plen for _, _, _, plen in packets)
    throughput = total_bytes

    return packet_loss, avg_delay, throughput

print("RPi Controller (PyTorch - Fixed & NTP Ready) started. Waiting for data...")
try:
    while True:
        try:
            data, addr = sock.recvfrom(2048)
        except socket.timeout:
            continue

        # Bắt gói tin yêu cầu đồng bộ thời gian (SYNC)
        if len(data) == 1 and data[0] == ord('S'):
            handle_sync(addr) # Truyền trực tiếp địa chỉ nguồn để phản hồi lập tức
            continue

        parsed = process_packet(data)
        if not parsed:
            continue

        window_id, seq, total, timestamp, payload_len = parsed

        # Kiểm tra xem có phải gói tin thuộc về một Cửa sổ mới hoàn toàn không
        if window_id != current_window_id:
            # Xử lý tính toán đặc trưng và chạy AI cho cửa sổ vừa kết thúc
            if current_window_id is not None and packets_this_window:
                metrics = process_window(current_window_id, packets_this_window)
                if metrics:
                    print(f"Window {current_window_id}: loss={metrics[0]:.2f}, delay={metrics[1]:.1f}ms, thr={metrics[2]} B/s")
                    window_buffer.append(metrics)

                    # Đợi đủ dữ liệu chuỗi thời gian của 10 cửa sổ liên tiếp để nạp vào mạng GRU
                    if len(window_buffer) == WINDOW_SIZE:
                        seq_np = np.array(window_buffer, dtype=np.float32).reshape(1, WINDOW_SIZE, FEATURES)
                        seq_norm = (seq_np - mins) / (maxs - mins)
                        input_tensor = torch.tensor(seq_norm, dtype=torch.float32)
                        with torch.no_grad():
                            output = model(input_tensor)
                            decision = output.argmax(dim=1).item()
                        print(f"GRU Inference: {output.numpy()}, Decision={decision}")
                    else:
                        decision = 0  # Fallback: Mặc định SEND khi bộ đệm chưa đầy 10 giây đầu
                        print(f"Buffer size {len(window_buffer)} < {WINDOW_SIZE}, fallback SEND")

                    send_ack(current_window_id, decision)

            # Khởi tạo vùng lưu trữ bóc tách gói tin cho cửa sổ mới
            current_window_id = window_id
            packets_this_window = [(seq, total, timestamp, payload_len)]
        else:
            # Gói tin thuộc cửa sổ hiện tại, thêm vào list chờ gom đủ cuối giây
            packets_this_window.append((seq, total, timestamp, payload_len))

except KeyboardInterrupt:
    print("Shutting down Controller.")
finally:
    sock.close()
    ack_sock.close()