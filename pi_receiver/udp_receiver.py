"""
UDP packet receiver for Raspberry Pi.

The ESP packet timestamp must be converted to Pi epoch microseconds during
the TCP handshake. With both timestamps on the same time base:

    delay_ms = (pi_receive_time_us - esp_send_time_us) / 1000
"""

import socket
import struct
import time
from typing import Dict, Tuple

from config import (
    ENCRYPTION_KEY,
    HEADER_SIZE,
    PAYLOAD_LEN,
    STRUCT_FMT,
    TOTAL_PKTS,
    UDP_PORT,
    UDP_TIMEOUT,
)


def _xor_decrypt(data: bytes) -> bytes:
    decrypted = bytearray(data)
    key_len = len(ENCRYPTION_KEY)
    for i in range(len(decrypted)):
        decrypted[i] ^= ENCRYPTION_KEY[i % key_len]
    return bytes(decrypted)


def _flush_buffer(sock: socket.socket) -> None:
    sock.setblocking(False)
    try:
        while True:
            sock.recvfrom(4096)
    except BlockingIOError:
        pass
    finally:
        sock.setblocking(True)


def receive_packets(clock_offset_ms: float = 0.0) -> Tuple[Dict[int, Dict[str, float]], float]:
    """
    Receive UDP packets until TOTAL_PKTS are received or timeout occurs.

    Packet format:
        - uint32 sequence number, big-endian
        - uint64 ESP send timestamp, Pi epoch microseconds, big-endian
        - 512-byte XOR-encrypted payload
    """
    received: Dict[int, Dict[str, float]] = {}
    start_time = None
    end_time = None

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", UDP_PORT))
        _flush_buffer(sock)
        sock.settimeout(UDP_TIMEOUT)

        print(f"[PI] Listening on UDP port {UDP_PORT}")
        print(f"[PI] Waiting for {TOTAL_PKTS} packets...\n")

        while len(received) < TOTAL_PKTS:
            try:
                data, _addr = sock.recvfrom(4096)
                recv_time_us = time.time_ns() // 1_000
                recv_time = recv_time_us / 1_000_000

                if len(data) < HEADER_SIZE + PAYLOAD_LEN:
                    print(f"[WARN] Packet too short: {len(data)} bytes")
                    continue

                try:
                    seq, esp_ts_us = struct.unpack(STRUCT_FMT, data[:HEADER_SIZE])
                except struct.error as e:
                    print(f"[WARN] Corrupted packet header: {e}")
                    continue

                payload = _xor_decrypt(data[HEADER_SIZE:])
                if len(payload) != PAYLOAD_LEN:
                    print(f"[WARN] Invalid payload size: {len(payload)} bytes")
                    continue

                if seq in received:
                    print(f"[DUP] seq={seq:03d}")
                    continue

                if start_time is None:
                    start_time = recv_time
                end_time = recv_time

                delay_ms = (recv_time_us - esp_ts_us) / 1000.0

                received[seq] = {
                    "e2e_delay_ms": round(delay_ms, 3),
                    "esp_ts_us": esp_ts_us,
                    "recv_time": recv_time,
                }

                print(f"[RECV] seq={seq:03d}  delay={delay_ms:.2f}ms")

            except socket.timeout:
                print(f"[INFO] Timeout after receiving {len(received)} packets")
                break

    except OSError as e:
        print(f"[ERROR] Socket error in UDP receiver: {e}")
        raise
    finally:
        sock.close()

    duration = 0.0
    if start_time is not None and end_time is not None:
        duration = end_time - start_time

    return received, duration
