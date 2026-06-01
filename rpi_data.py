import socket
import struct
import time
import numpy as np

# ===== Cấu hình mạng =====
UDP_IP        = "0.0.0.0"
UDP_PORT_DATA = 4444          # RPi lắng nghe dữ liệu từ ESP32
ESP32_PORT_ACK = 5555         # ESP32 nhận ACK tại localPort=5555

# ===== Thông số hệ thống (khớp với ESP32) =====
PACKETS_PER_WINDOW = 50
PAYLOAD_SIZE       = 64

# ===== Biến trạng thái =====
current_window_id   = None
packets_this_window = []      # list of (seq, total, timestamp_ms, payload_len)
esp32_addr          = None    # (IP, port) tự động lấy từ packet đầu tiên

# ===== Sockets =====
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT_DATA))
sock.settimeout(0.1)

ack_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def send_ack(window_id: int, decision: int = 0):
    """Gửi ACK về ESP32: [window_id_high, window_id_low, decision] (3 bytes)."""
    if esp32_addr is None:
        return
    msg = struct.pack('>HB', window_id, decision)
    ack_sock.sendto(msg, (esp32_addr[0], ESP32_PORT_ACK))
    print(f"  [ACK] window={window_id}, decision={decision} → {esp32_addr[0]}:{ESP32_PORT_ACK}")


def handle_sync(addr):
    """Phản hồi SYNC (NTP-style): trả về timestamp 4 bytes."""
    ts = int(time.time() * 1000) & 0xFFFFFFFF
    sock.sendto(struct.pack('>I', ts), addr)
    print(f"[SYNC] Timestamp {ts} ms → {addr}")


def parse_header(data: bytes):
    """
    Header 10 bytes:
      [0-1] window_id   uint16 big-endian
      [2]   seq         uint8
      [3]   total       uint8  (= 50)
      [4-7] timestamp   uint32 big-endian (ms)
      [8-9] payload_len uint16 big-endian (= 64)
    """
    if len(data) < 10:
        return None
    window_id   = (data[0] << 8) | data[1]
    seq         = data[2]
    total       = data[3]
    timestamp   = struct.unpack_from('>I', data, 4)[0]
    payload_len = (data[8] << 8) | data[9]
    return window_id, seq, total, timestamp, payload_len


def compute_metrics(packets):
    """Tính packet_loss, avg_delay, throughput cho một cửa sổ."""
    if not packets:
        return None
    total_expected = packets[0][1]
    received       = len(packets)
    packet_loss    = 1.0 - received / total_expected if total_expected > 0 else 0.0

    now_ms    = int(time.time() * 1000)
    delays    = [max(0, now_ms - pkt[2]) for pkt in packets]
    avg_delay = float(np.mean(delays))

    throughput = sum(10 + pkt[3] for pkt in packets)
    return packet_loss, avg_delay, throughput


# ---------------------------------------------------------------------------
print("=" * 55)
print(" RPi Controller  –  nhận dữ liệu từ ESP32 (no AI)")
print(f" Lắng nghe UDP :{UDP_PORT_DATA}   (IP ESP32 tự nhận diện)")
print("=" * 55)

try:
    while True:
        try:
            data, addr = sock.recvfrom(2048)
        except socket.timeout:
            continue

        # Tự động lưu IP ESP32 từ packet đầu tiên nhận được
        if esp32_addr is None:
            esp32_addr = addr
            print(f"[INFO] Phát hiện ESP32 tại {esp32_addr[0]}:{esp32_addr[1]}")

        # ── SYNC request ──────────────────────────────────────────────────
        if len(data) == 1 and data[0] == ord('S'):
            handle_sync(addr)
            continue

        # ── Gói dữ liệu ──────────────────────────────────────────────────
        parsed = parse_header(data)
        if parsed is None:
            print(f"[WARN] Gói không hợp lệ ({len(data)} bytes) từ {addr}")
            continue

        window_id, seq, total, timestamp, payload_len = parsed

        # ── Phát hiện cửa sổ mới ─────────────────────────────────────────
        if window_id != current_window_id:

            # Xử lý cửa sổ vừa kết thúc
            if current_window_id is not None and packets_this_window:
                metrics = compute_metrics(packets_this_window)
                if metrics:
                    loss, delay, thr = metrics
                    print(
                        f"[Window {current_window_id:4d}] "
                        f"recv={len(packets_this_window)}/{PACKETS_PER_WINDOW}  "
                        f"loss={loss:5.1%}  "
                        f"delay={delay:6.1f}ms  "
                        f"throughput={thr:5d}B"
                    )
                    send_ack(current_window_id, decision=0)

            # Khởi tạo cửa sổ mới
            current_window_id   = window_id
            packets_this_window = [(seq, total, timestamp, payload_len)]
            print(f"\n[Window {window_id}] Bắt đầu nhận...")

        else:
            packets_this_window.append((seq, total, timestamp, payload_len))

except KeyboardInterrupt:
    print("\n[INFO] Dừng controller.")
finally:
    sock.close()
    ack_sock.close()