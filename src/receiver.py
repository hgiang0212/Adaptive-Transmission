"""
receiver.py - chạy trên PC (server)
1. Chờ SYN từ Pi -> gửi ACK
2. Nhận UDP data, tính delay và BER
"""

import socket
import struct
import time
import csv
import threading

TCP_PORT    = 5006
UDP_PORT    = 5005
KNOWN_PAY   = b'\xAA' * 128
TOTAL_PKTS  = 100
LOG_FILE    = "raw_log.csv"

received    = {}
header_size = struct.calcsize("!Id")


def bit_error_count(a: bytes, b: bytes) -> int:
    return sum(bin(x ^ y).count("1") for x, y in zip(a, b))


def wait_for_handshake():
    """Chờ SYN từ Pi, gửi lại ACK."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", TCP_PORT))
        s.listen(1)
        print(f"[PC] Chờ handshake tại port {TCP_PORT}...")
        conn, addr = s.accept()
        with conn:
            data = conn.recv(16)
            if data == b"SYN":
                conn.sendall(b"ACK")
                print(f"[PC] Nhận SYN từ {addr[0]} -> đã gửi ACK\n")


def receive_data():
    """Nhận UDP packet từ Pi."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))
    sock.settimeout(10.0)
    print(f"[PC] Lắng nghe UDP port {UDP_PORT}...")

    while len(received) < TOTAL_PKTS:
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            print("[PC] Timeout — dừng nhận.")
            break

        recv_time  = time.time()
        if len(data) < header_size:
            continue

        seq, send_ts = struct.unpack("!Id", data[:header_size])
        payload      = data[header_size:]
        delay        = (recv_time - send_ts) * 1000
        bit_errors   = bit_error_count(payload, KNOWN_PAY)
        ber          = bit_errors / (len(KNOWN_PAY) * 8)

        received[seq] = {"delay_ms": round(delay, 3), "ber": round(ber, 8)}
        print(f"  [RECV] seq={seq:03d}  delay={delay:.2f}ms  BER={ber:.6f}")

    sock.close()


def print_stats():
    n         = len(received)
    loss      = (TOTAL_PKTS - n) / TOTAL_PKTS * 100
    avg_delay = sum(v["delay_ms"] for v in received.values()) / n if n else 0
    avg_ber   = sum(v["ber"]      for v in received.values()) / n if n else 0

    print("\n══════════ KẾT QUẢ ══════════")
    print(f"  Nhận    : {n}/{TOTAL_PKTS} packets")
    print(f"  Loss    : {loss:.1f}%")
    print(f"  Delay   : {avg_delay:.2f} ms (avg)")
    print(f"  BER     : {avg_ber:.8f} (avg)")
    print("══════════════════════════════")

    with open(LOG_FILE, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["seq", "delay_ms", "ber"])
        for seq in sorted(received):
            w.writerow([seq, received[seq]["delay_ms"], received[seq]["ber"]])
    print(f"[PC] Log đã lưu → {LOG_FILE}")


if __name__ == "__main__":
    wait_for_handshake()
    receive_data()
    print_stats()
