"""
send.py - chạy trên Raspberry Pi
Gửi UDP packet tới PC server
"""

import socket
import struct
import time

# ── Sửa IP này thành IP của PC ──
SERVER_IP   = "100.95.137.40"
SERVER_PORT = 5005
# ────────────────────────────────

PAYLOAD     = b'\xAA' * 128   # bit pattern cố định
TOTAL_PKTS  = 100
INTERVAL    = 0.05            # 50ms giữa các packet

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

print(f"[PI] Gửi {TOTAL_PKTS} packets tới {SERVER_IP}:{SERVER_PORT}")

for seq in range(TOTAL_PKTS):
    ts = time.time()
    header = struct.pack("!Id", seq, ts)   # seq(4B) + timestamp(8B)
    packet = header + PAYLOAD
    sock.sendto(packet, (SERVER_IP, SERVER_PORT))
    print(f"  [SEND] seq={seq:03d}")
    time.sleep(INTERVAL)

sock.close()
print("[PI] Xong.")
