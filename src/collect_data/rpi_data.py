import socket
import struct
import time
import numpy as np
import csv
# ===== Cấu hình mạng =====
UDP_IP = "0.0.0.0"
UDP_PORT_DATA = 4444
ESP8266_PORT_ACK = 5555

# ===== Thông số hệ thống =====
PACKETS_PER_WINDOW = 50
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

# ===== File log CSV và TXT =====
CSV_FILENAME = "raw_metrics.csv"

csv_file = open(CSV_FILENAME, 'w', newline='')
csv_writer = csv.writer(csv_file)
csv_writer.writerow(["timestamp", "window_id", "recv_pkts", "packet_loss", "avg_delay_ms", "throughput_bps"])


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
    first_recv = packets[0][4]
    last_recv = packets[-1][4]
    duration_ms = last_recv - first_recv
    if duration_ms > 0:
        throughput_bps = total_bytes / (duration_ms / 1000.0)
    else:
        throughput_bps = 0.0

    return packet_loss, avg_delay, throughput_bps


# ---------------------------------------------------------------------------
print("=" * 55)
print(" RPi Controller")
print(f" Lắng nghe UDP :{UDP_PORT_DATA}")
print("=" * 55)

current_win = None
win_packets = []
win_start_time = None
print("Collecting data... Press Ctrl+C to stop.")
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
                    csv_writer.writerow([
                        time.strftime('%Y-%m-%d %H:%M:%S'),
                        current_window_id, recv_cnt,
                        f"{loss:.4f}", f"{delay:.2f}", int(thr)
                    ])
                    csv_file.flush()
                    print(f"Window {current_window_id:4d}: recv={recv_cnt:2d}/{PACKETS_PER_WINDOW} "
                          f"loss={loss:5.1%} delay={delay:6.2f}ms thr={int(thr):5d} Bps")
                    # Gửi ACK với quyết định thực tế
                    send_ack(current_window_id, decision=0)
                    # Ghi CSV

            current_window_id = window_id
            packets_this_window = [(seq, total, send_timestamp_ms, payload_len, recv_time_ms)]
        else:
            packets_this_window.append((seq, total, send_timestamp_ms, payload_len, recv_time_ms))

except KeyboardInterrupt:
    print("\n[INFO] Dừng controller.")
finally:
    sock.close()
    ack_sock.close()