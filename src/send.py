"""
send.py - chạy trên Raspberry Pi
1. Handshake TCP: gửi SYN -> chờ ACK từ PC
2. Gửi UDP data từng packet một
"""

import socket
import struct
import time

# ── Sửa IP này thành IP của PC ──
SERVER_IP   = "100.95.137.40"
TCP_PORT    = 5006   # handshake
UDP_PORT    = 5005   # data
# ────────────────────────────────

PAYLOAD    = b'\xAA' * 128
TOTAL_PKTS = 100
INTERVAL   = 0.1    # 100ms giữa các packet


def handshake():
    """Gửi SYN qua TCP, chờ ACK từ PC."""
    print("[PI] Đang handshake với PC...")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((SERVER_IP, TCP_PORT))
        s.sendall(b"SYN")
        ack = s.recv(16)
        if ack == b"ACK":
            print("[PI] Handshake OK — bắt đầu gửi data\n")
        else:
            raise ConnectionError(f"Handshake thất bại: {ack}")


def send_data():
    """Gửi UDP packet: seq(4B) | timestamp(8B) | payload."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for seq in range(TOTAL_PKTS):
        ts     = time.time()
        header = struct.pack("!Id", seq, ts)
        packet = header + PAYLOAD
        sock.sendto(packet, (SERVER_IP, UDP_PORT))
        print(f"  [SEND] seq={seq:03d}  ts={ts:.3f}")
        time.sleep(INTERVAL)
    sock.close()
    print("\n[PI] Đã gửi xong.")


if __name__ == "__main__":
    handshake()
    send_data()
