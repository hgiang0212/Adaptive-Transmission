import socket
import struct
import time
import csv
import os
import numpy as np
from collections import deque
import torch
import torch.nn as nn


# ===== Kiến trúc GRU =====
class GRUNet(nn.Module):
    def __init__(self, input_size=3, hidden_size=16, num_classes=3):
        super().__init__()
        self.gru = nn.GRU(input_size, hidden_size, batch_first=True)
        self.fc = nn.Linear(hidden_size, num_classes)

    def forward(self, x):
        out, _ = self.gru(x)
        return self.fc(out[:, -1, :])


# ===== Cấu hình =====
UDP_IP = "0.0.0.0"
UDP_PORT_DATA = 4444
ESP8266_PORT_ACK = 5555

HEADER_SIZE = 10
WINDOW_MS = 2000.0
WINDOW_SIZE = 10  # số cửa sổ tích lũy trước khi chạy GRU
FEATURES = 3
PACKETS_PER_WIN = 50
MODEL_PATH = "gru_model.pt"
LOG_CSV = "session_log.csv"
LOG_TXT = "session_log.txt"

# ===== Load model =====
if not os.path.exists(MODEL_PATH):
    raise FileNotFoundError(f"Không tìm thấy model: {MODEL_PATH}")

checkpoint = torch.load(MODEL_PATH, map_location=torch.device('cpu'))
model = GRUNet(
    input_size=checkpoint['input_size'],
    hidden_size=checkpoint['hidden_size'],
    num_classes=checkpoint['num_classes'],
)
model.load_state_dict(checkpoint['model_state_dict'])
model.eval()

mins = checkpoint['mins'].numpy()
maxs = checkpoint['maxs'].numpy()
maxs[maxs == mins] = 1.0  # tránh chia cho 0

DECISION_LABEL = {0: "SEND", 1: "COMPRESS", 2: "WAIT"}

# ===== Logging =====
csv_file = open(LOG_CSV, 'w', newline='')
csv_writer = csv.writer(csv_file)
csv_writer.writerow(["timestamp", "window_id", "recv_pkts",
                     "packet_loss", "avg_delay_ms", "throughput_bytes",
                     "decision", "decision_label", "gru_scores"])

txt_file = open(LOG_TXT, 'w')


def log(msg: str):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line)
    txt_file.write(line + "\n")
    txt_file.flush()


def log_csv(window_id, recv, loss, delay, thr, decision, scores):
    csv_writer.writerow([
        time.strftime('%Y-%m-%d %H:%M:%S'),
        window_id, recv,
        f"{loss:.4f}", f"{delay:.2f}", thr,
        decision, DECISION_LABEL.get(decision, "?"),
        " ".join(f"{s:.4f}" for s in scores),
    ])
    csv_file.flush()


# ===== Biến trạng thái =====
window_buffer = deque(maxlen=WINDOW_SIZE)
current_window_id = None
packets_this_window = []  # list of (seq, total, timestamp_ms, payload_len, recv_time_ms)
esp32_addr = None  # FIX: Đã đổi thành esp32_addr để không bị lỗi NameError

# ===== Sockets =====
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT_DATA))
sock.settimeout(0.1)
ack_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


# ===== Hàm tiện ích =====
def send_ack(window_id: int, decision: int):
    if esp32_addr is None:
        return
    msg = struct.pack('>HB', window_id, decision)
    ack_sock.sendto(msg, (esp32_addr[0], ESP8266_PORT_ACK))
    log(f"  ACK → {esp32_addr[0]}:{ESP8266_PORT_ACK}  "
        f"window={window_id}  decision={decision} ({DECISION_LABEL.get(decision, '?')})")


def handle_sync(addr):
    ts = int(time.time() * 1000) & 0xFFFFFFFF
    sock.sendto(struct.pack('>I', ts), addr)
    log(f"SYNC: timestamp={ts} ms → {addr}")


def parse_header(data: bytes):
    if len(data) < 10:
        return None
    window_id = (data[0] << 8) | data[1]
    seq = data[2]
    total = data[3]
    timestamp = struct.unpack_from('>I', data, 4)[0]
    payload_len = (data[8] << 8) | data[9]
    return window_id, seq, total, timestamp, payload_len


def compute_metrics(packets):
    total_expected = packets[0][1]
    received = len(packets)
    packet_loss = 1.0 - received / total_expected if total_expected > 0 else 0.0

    # FIX: Tính delay từng gói tại thời điểm nó đến RPi, xử lý toán học chống tràn số mạng
    delays = []
    for pkt in packets:
        send_ts = pkt[2]
        recv_ts = pkt[4]
        diff = (recv_ts - send_ts) & 0xFFFFFFFF
        if diff > 0x7FFFFFFF:
            delays.append(0.0)
        else:
            delays.append(float(diff))
    avg_delay = float(np.mean(delays)) if delays else 0.0

    # GIỮ NGUYÊN: Throughput theo ý người dùng
    total_bytes = sum(HEADER_SIZE + pkt[3] for pkt in packets)
    throughput_bps = total_bytes / (WINDOW_MS / 1000.0)

    return packet_loss, avg_delay, throughput_bps


def run_inference():
    seq_np = np.array(window_buffer, dtype=np.float32).reshape(1, WINDOW_SIZE, FEATURES)
    seq_norm = (seq_np - mins) / (maxs - mins)
    tensor = torch.tensor(seq_norm, dtype=torch.float32)
    with torch.no_grad():
        output = model(tensor)
        scores = output.numpy().flatten().tolist()
        decision = int(output.argmax(dim=1).item())
    return decision, scores


# ===== Main =====
log("=" * 55)
log(f" RPi Controller  |  GRU model: {MODEL_PATH}")
log(f" Data :{UDP_PORT_DATA}   ACK → ESP32:{ESP8266_PORT_ACK}  (IP tự nhận diện)")
log(f" Log CSV: {LOG_CSV}   TXT: {LOG_TXT}")
log("=" * 55)

try:
    while True:
        try:
            data, addr = sock.recvfrom(2048)
        except socket.timeout:
            continue

        # FIX: Ghi nhận thời gian đến ngay lập tức tại vòng lặp chính
        recv_time_ms = int(time.time() * 1000) & 0xFFFFFFFF

        # Lưu IP ESP32 từ packet đầu tiên
        if esp32_addr is None:
            esp32_addr = addr
            log(f"Phát hiện ESP32 tại {esp32_addr[0]}:{esp32_addr[1]}")

        # ── SYNC ──────────────────────────────────────────────
        if len(data) == 1 and data[0] == ord('S'):
            handle_sync(addr)
            continue

        # ── Parse header ───────────────────────────────────────
        parsed = parse_header(data)
        if not parsed:
            log(f"WARN: gói không hợp lệ ({len(data)}B) từ {addr}")
            continue

        window_id, seq, total, timestamp, payload_len = parsed

        # ── Phát hiện cửa sổ mới ──────────────────────────────
        if window_id != current_window_id:

            # Xử lý cửa sổ vừa kết thúc
            if current_window_id is not None and packets_this_window:
                metrics = compute_metrics(packets_this_window)
                loss, delay, thr = metrics
                recv_count = len(packets_this_window)

                log(f"Window {current_window_id:4d} | "
                    f"recv={recv_count}/{PACKETS_PER_WIN}  "
                    f"loss={loss:.1%}  delay={delay:.1f}ms  thr={thr}B")

                window_buffer.append(metrics)

                if len(window_buffer) == WINDOW_SIZE:
                    decision, scores = run_inference()
                    log(f"  GRU scores={[f'{s:.3f}' for s in scores]}  "
                        f"→ decision={decision} ({DECISION_LABEL[decision]})")
                else:
                    decision, scores = 0, []
                    log(f"  Buffer {len(window_buffer)}/{WINDOW_SIZE} → fallback SEND")

                send_ack(current_window_id, decision)
                log_csv(current_window_id, recv_count, loss, delay, thr, decision, scores)

            # Khởi tạo cửa sổ mới, LƯU Ý append thêm recv_time_ms
            current_window_id = window_id
            packets_this_window = [(seq, total, timestamp, payload_len, recv_time_ms)]
            log(f"\nWindow {window_id} — bắt đầu nhận...")

        else:
            packets_this_window.append((seq, total, timestamp, payload_len, recv_time_ms))

except KeyboardInterrupt:
    log("Dừng controller.")
finally:
    sock.close()
    ack_sock.close()
    csv_file.close()
    txt_file.close()