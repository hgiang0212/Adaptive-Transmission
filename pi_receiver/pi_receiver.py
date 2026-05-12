"""
pi_receiver.py - chạy trên Raspberry Pi
Nhận UDP packet từ ESP8266/ESP32, tính delay, jitter và BER
Chế độ: Chạy liên tục

Luồng:
1. Chờ handshake TCP từ ESP (SYN) → gửi ACK
2. Nhận UDP data và tính các chỉ số
3. Lưu kết quả với timestamp
4. Quay lại bước 1
"""

import socket
import struct
import time
import csv
import os
from datetime import datetime

TCP_PORT     = 5006
UDP_PORT     = 5005

PAYLOAD_LEN  = 128
KNOWN_PAY    = b'\xAA' * PAYLOAD_LEN

TOTAL_PKTS   = 100

LOG_DIR      = "logs"
SUMMARY_FILE = "summary.csv"

received     = {}
cycle_count  = 0

# ESP8266 gửi: uint32 seq + double timestamp
STRUCT_FMT   = "!Id"

# 4B uint32 + 8B double = 12 bytes
HEADER_SIZE  = struct.calcsize(STRUCT_FMT)


# ════════════════════════════════════════════════
# Utility
# ════════════════════════════════════════════════

def bit_error_count(a: bytes, b: bytes) -> int:
    """Đếm số bit lỗi."""
    min_len = min(len(a), len(b))

    return sum(
        bin(x ^ y).count("1")
        for x, y in zip(a[:min_len], b[:min_len])
    )


# ════════════════════════════════════════════════
# TCP Handshake
# ════════════════════════════════════════════════

def wait_for_handshake():

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:

        # FIX: reuse addr
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        s.bind(("0.0.0.0", TCP_PORT))
        s.listen(1)

        print(f"[PI] Chờ handshake tại TCP port {TCP_PORT}...")

        conn, addr = s.accept()

        with conn:

            data = conn.recv(16)

            if data == b"SYN":

                conn.sendall(b"ACK")

                print(f"[PI] Nhận SYN từ {addr[0]}")
                print("[PI] Đã gửi ACK ✓")
                print("[PI] Kênh truyền đã thiết lập\n")

                return addr[0]

            else:

                print(f"[PI] Handshake lỗi: {data}")

                return None


# ════════════════════════════════════════════════
# UDP Receive
# ════════════════════════════════════════════════

def flush_udp_buffer(sock):

    sock.setblocking(False)

    try:
        while True:
            sock.recvfrom(4096)

    except:
        pass

    sock.setblocking(True)


def receive_data():

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # FIX
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    sock.bind(("0.0.0.0", UDP_PORT))

    # Flush packet cũ
    flush_udp_buffer(sock)

    sock.settimeout(15.0)

    print(f"[PI] Listening UDP :{UDP_PORT}")
    print(f"[PI] Chờ {TOTAL_PKTS} packets...\n")

    prev_recv_time = None

    while len(received) < TOTAL_PKTS:

        try:

            data, addr = sock.recvfrom(4096)

        except socket.timeout:

            print("[PI] Timeout nhận packet")
            break

        recv_time = time.time()

        # Validate packet size
        if len(data) < HEADER_SIZE + PAYLOAD_LEN:

            print(f"[WARN] Packet quá ngắn: {len(data)} bytes")

            continue

        # Unpack header: !Id = uint32 + double
        seq, esp_ts = struct.unpack(
            STRUCT_FMT,
            data[:HEADER_SIZE]
        )

        payload = data[HEADER_SIZE:]

        # Validate payload
        if len(payload) != PAYLOAD_LEN:

            print(f"[WARN] Payload lỗi size={len(payload)}")

            continue

        # Duplicate
        if seq in received:

            print(f"[DUP] seq={seq:03d}")

            continue

        # Inter-arrival delay
        if prev_recv_time is None:

            inter_delay = 0.0

        else:

            inter_delay = (
                (recv_time - prev_recv_time) * 1000
            )

        prev_recv_time = recv_time

        # BER
        bit_errors = bit_error_count(
            payload,
            KNOWN_PAY
        )

        ber = bit_errors / (PAYLOAD_LEN * 8)

        received[seq] = {

            "inter_delay_ms": round(inter_delay, 3),

            "ber": round(ber, 8),

            "recv_time": recv_time,

            "esp_ts": esp_ts,
        }

        print(
            f"[RECV] "
            f"seq={seq:03d}  "
            f"delay={inter_delay:.2f}ms  "
            f"BER={ber:.8f}"
        )

    sock.close()


# ════════════════════════════════════════════════
# Metrics
# ════════════════════════════════════════════════

def compute_jitter():

    seqs = sorted(received.keys())

    delays = [
        received[s]["inter_delay_ms"]
        for s in seqs
        if received[s]["inter_delay_ms"] > 0
    ]

    if len(delays) < 2:
        return 0.0

    diffs = [
        abs(delays[i] - delays[i - 1])
        for i in range(1, len(delays))
    ]

    return sum(diffs) / len(diffs)


def detect_out_of_order():

    seqs_by_recv = sorted(
        received.keys(),
        key=lambda s: received[s]["recv_time"]
    )

    ooo = 0

    for i in range(1, len(seqs_by_recv)):

        if seqs_by_recv[i] < seqs_by_recv[i - 1]:

            ooo += 1

    return ooo


def compute_throughput():

    if len(received) < 2:
        return 0.0

    recv_times = [
        v["recv_time"]
        for v in received.values()
    ]

    duration = max(recv_times) - min(recv_times)

    if duration <= 0:
        return 0.0

    total_bytes = len(received) * (
        HEADER_SIZE + PAYLOAD_LEN
    )

    throughput_mbps = (
        total_bytes * 8 / duration / 1e6
    )

    return throughput_mbps


# ════════════════════════════════════════════════
# Report
# ════════════════════════════════════════════════

def print_stats():

    global cycle_count

    cycle_count += 1

    n = len(received)

    loss = (
        (TOTAL_PKTS - n)
        / TOTAL_PKTS
        * 100
    )

    delays = [
        v["inter_delay_ms"]
        for v in received.values()
        if v["inter_delay_ms"] > 0
    ]

    avg_delay = (
        sum(delays) / len(delays)
        if delays else 0
    )

    min_delay = min(delays) if delays else 0
    max_delay = max(delays) if delays else 0

    avg_ber = (
        sum(v["ber"] for v in received.values()) / n
        if n else 0
    )

    jitter = compute_jitter()

    ooo = detect_out_of_order()

    throughput = compute_throughput()

    timestamp = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    print("\n══════════════ RESULT ══════════════")

    print(f"Cycle             : #{cycle_count}")

    print(f"Timestamp         : {timestamp}")

    print(f"Received          : {n}/{TOTAL_PKTS}")

    print(f"Packet Loss       : {loss:.2f}%")

    print(f"Delay Avg         : {avg_delay:.2f} ms")

    print(f"Delay Min         : {min_delay:.2f} ms")

    print(f"Delay Max         : {max_delay:.2f} ms")

    print(f"Jitter            : {jitter:.2f} ms")

    print(f"Out-of-order      : {ooo}")

    print(f"BER Avg           : {avg_ber:.8f}")

    print(f"Throughput        : {throughput:.4f} Mbps")

    print("════════════════════════════════════\n")

    # Save logs
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

    log_name = (
        f"{LOG_DIR}/"
        f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )

    with open(log_name, "w", newline="") as f:

        w = csv.writer(f)

        w.writerow([
            "seq",
            "inter_delay_ms",
            "ber",
            "esp_ts",
            "recv_time"
        ])

        for seq in sorted(received):

            r = received[seq]

            w.writerow([
                seq,
                r["inter_delay_ms"],
                r["ber"],
                r["esp_ts"],
                r["recv_time"]
            ])

    print(f"[PI] Saved log -> {log_name}")

    # Save summary
    summary_exists = os.path.exists(SUMMARY_FILE)

    with open(SUMMARY_FILE, "a", newline="") as f:

        w = csv.writer(f)

        if not summary_exists:

            w.writerow([
                "timestamp",
                "cycle",
                "received",
                "loss_%",
                "avg_delay_ms",
                "min_delay_ms",
                "max_delay_ms",
                "jitter_ms",
                "out_of_order",
                "avg_ber",
                "throughput_mbps"
            ])

        w.writerow([
            timestamp,
            cycle_count,
            n,
            round(loss, 2),
            round(avg_delay, 2),
            round(min_delay, 2),
            round(max_delay, 2),
            round(jitter, 2),
            ooo,
            avg_ber,
            round(throughput, 4)
        ])

    print(f"[PI] Summary -> {SUMMARY_FILE}\n")


# ════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════

if __name__ == "__main__":

    print("════════════════════════════════════")
    print(" Raspberry Pi UDP Receiver")
    print(" ESP8266 / ESP32")
    print(" Continuous Mode")
    print("════════════════════════════════════\n")

    try:

        while True:

            received.clear()

            esp_ip = wait_for_handshake()

            if esp_ip is None:

                print("[PI] Handshake fail\n")

                time.sleep(2)

                continue

            receive_data()

            print_stats()

            print("[PI] Ready for next cycle\n")

            print("─" * 50 + "\n")

    except KeyboardInterrupt:

        print("\n[PI] Stop")

        print(f"[PI] Total cycles: {cycle_count}")