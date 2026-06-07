import socket
import struct
import time
import numpy as np
import csv
# ===== Cấu hình mạng =====
UDP_IP = "0.0.0.0"
UDP_PORT_DATA = 4444  # RPi lắng nghe dữ liệu từ ESP32/ESP8266
ESP8266_PORT_ACK = 5555  # ESP nhận ACK tại localPort=5555

# ===== Thông số hệ thống =====
PACKETS_PER_WINDOW = 100
PAYLOAD_SIZE = 64
HEADER_SIZE = 10
PACKET_SIZE = HEADER_SIZE + PAYLOAD_SIZE  # 74 bytes
WINDOW_MS = 2000.0

# ===== Biến trạng thái =====
current_window_id = None
packets_this_window = []
esp8266_addr = None

# ===== Sockets =====
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT_DATA))
sock.settimeout(0.1)

ack_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# ===== Ngưỡng quyết định (khoa học, có thể điều chỉnh) =====
# Ý nghĩa: SEND (good) – kênh tốt; COMPRESS (normal) – kênh trung bình; WAIT (bad) – kênh xấu
LOSS_GOOD = 0.05      # 5%
LOSS_BAD = 0.2
DELAY_GOOD = 5.0      # ms
DELAY_BAD = 50.0      # ms
THROUGHPUT_GOOD = 1700.0   # Bps
THROUGHPUT_BAD = 1100.0 # Bps

DECISION_LABEL = {
    0: "SEND",
    1: "COMPRESS",
    2: "WAIT"
}
CHANNEL_QUALITY = {
    0: "good",
    1: "normal",
    2: "bad"
}

# ===== File log CSV và TXT =====
LOG_CSV = "session_log.csv"

csv_file = open(LOG_CSV, 'w', newline='')
csv_writer = csv.writer(csv_file)
csv_writer.writerow([
    "timestamp", "window_id", "recv_pkts",
    "packet_loss", "avg_delay_ms", "throughput_bps",
    "decision", "channel_quality"
])
def log_csv(window_id, recv, loss, delay, thr, decision):
    csv_writer.writerow([
        time.strftime('%Y-%m-%d %H:%M:%S'),
        window_id, recv,
        f"{loss:.4f}", f"{delay:.2f}", int(thr),
        decision, CHANNEL_QUALITY[decision]
    ])
    csv_file.flush()

# ===== Hàm ra quyết định dựa trên ngưỡng =====
def decide_action(loss: float, delay_ms: float, throughput_bps: float):
    if delay_ms > DELAY_BAD or loss > LOSS_BAD or throughput_bps < THROUGHPUT_BAD:
        return 2
    # Normal nếu delay trung bình hoặc loss trung bình hoặc throughput thấp
    if delay_ms < DELAY_GOOD or loss < LOSS_GOOD or throughput_bps > THROUGHPUT_GOOD:
        return 0
    return 1
def send_ack(window_id: int, decision: int = 0):
    if esp8266_addr is None:
        return
    msg = struct.pack('>HB', window_id, decision)
    ack_sock.sendto(msg, (esp8266_addr[0], ESP8266_PORT_ACK))
    print(f"  [ACK] window={window_id}, decision={decision} → {esp8266_addr[0]}:{ESP8266_PORT_ACK}")


def handle_sync(addr):
    """Phản hồi SYNC ngay lập tức với Timestamp dạng 32-bit unsigned"""
    ts = int(time.time() * 1000) & 0xFFFFFFFF
    sock.sendto(struct.pack('>I', ts), addr)


def parse_header(data: bytes):
    if len(data) < HEADER_SIZE:
        return None
    window_id = (data[0] << 8) | data[1]
    seq = data[2]
    total = data[3]
    timestamp = struct.unpack_from('>I', data, 4)[0]
    payload_len = (data[8] << 8) | data[9]
    return window_id, seq, total, timestamp, payload_len


def compute_metrics(packets):
    if not packets:
        return None

    # --- Packet loss ---
    received = len(packets)
    packet_loss = 1.0 - received / PACKETS_PER_WINDOW

    # --- One-way delay (ms) với xử lý tràn số và khử Jitter mạng ---
    delays = []
    for pkt in packets:
        send_ts = pkt[2]
        recv_ts = pkt[4]

        # Phép trừ modulo 32-bit chống tràn số tự nhiên
        diff = (recv_ts - send_ts) & 0xFFFFFFFF

        # Vì sai số mạng, đôi khi gói tin đến "sớm" hơn đồng hồ RPi (về mặt tính toán)
        # Khi đó diff sẽ bị vòng ngược thành số cực lớn (> 2 tỷ ms). Ta coi như delay = 0.
        if diff > 0x7FFFFFFF:
            delays.append(0.0)
        else:
            delays.append(float(diff))

    avg_delay = float(np.mean(delays)) if delays else 0.0

    # --- Throughput (Bps) ---
    total_bytes = sum(HEADER_SIZE + pkt[3] for pkt in packets)
    throughput_bps = total_bytes / (WINDOW_MS / 1000.0)

    return packet_loss, avg_delay, throughput_bps


# ---------------------------------------------------------------------------
print("=" * 55)
print(" RPi Controller – Bản nâng cấp Đồng bộ Cristian (Best RTT)")
print(f" Lắng nghe UDP :{UDP_PORT_DATA}")
print("=" * 55)

try:
    while True:
        try:
            data, addr = sock.recvfrom(2048)
        except socket.timeout:
            continue

        # FIX: Ghi thời điểm nhận dưới dạng số nguyên 32-bit unsigned để khớp với ESP
        recv_time_ms = int(time.time() * 1000) & 0xFFFFFFFF

        if esp8266_addr is None:
            esp8266_addr = addr
            print(f"[INFO] Phát hiện ESP8266 tại {esp8266_addr[0]}:{esp8266_addr[1]}")

        # ── Xử lý yêu cầu SYNC (Gửi phản hồi cực nhanh) ──────────────────
        if len(data) == 1 and data[0] == ord('S'):
            handle_sync(addr)
            continue

        # ── Xử lý gói dữ liệu thông thường ───────────────────────────────
        parsed = parse_header(data)
        if parsed is None:
            continue

        window_id, seq, total, send_timestamp_ms, payload_len = parsed

        # ── Quản lý cửa sổ nhận dữ liệu ──────────────────────────────────
        if window_id != current_window_id:
            if current_window_id is not None and packets_this_window:
                metrics = compute_metrics(packets_this_window)
                if metrics:
                    loss, delay, thr = metrics
                    recv_cnt = len(packets_this_window)
                    # Quyết định dựa trên ngưỡng
                    decision = decide_action(loss, delay, thr)

                    print(
                        f"[Window {current_window_id:4d}] "
                        f"recv={recv_cnt}/{PACKETS_PER_WINDOW}  "
                        f"loss={loss:5.1%}  delay={delay:6.2f}ms  "
                        f"throughput={thr:7.1f}Bps  → {CHANNEL_QUALITY[decision]}"
                    )

                    # Gửi ACK với quyết định thực tế
                    send_ack(current_window_id, decision=0)
                    # Ghi CSV
                    log_csv(current_window_id, recv_cnt, loss, delay, thr, decision)

            current_window_id = window_id
            packets_this_window = [(seq, total, send_timestamp_ms, payload_len, recv_time_ms)]
        else:
            packets_this_window.append((seq, total, send_timestamp_ms, payload_len, recv_time_ms))

except KeyboardInterrupt:
    print("\n[INFO] Dừng controller.")
finally:
    sock.close()
    ack_sock.close()