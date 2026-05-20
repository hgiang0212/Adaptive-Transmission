"""
TCP Handshake module for Pi Receiver.

This module handles TCP handshake establishment with ESP devices using SYN/ACK protocol.
"""

import socket
import struct
import time
from typing import Optional, Tuple
from config import TCP_PORT


def wait_for_handshake() -> Optional[Tuple[str, float]]:
    """
    Block until TCP handshake completes with an ESP device.
    
    Protocol:
        1. Listen on TCP_PORT (5006)
        2. Accept connection
        3. Receive message
        4. If message == b"SYN": send b"ACK" with Pi epoch timestamp
        5. ESP uses this timestamp to convert micros() to Pi epoch time
        6. Return (ESP IP, 0.0)
    
    Returns:
        tuple: (ESP IP address, clock_offset_ms) if handshake succeeds
        None: If handshake fails
    
    Raises:
        OSError: If socket operations fail (fatal error)
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # Enable socket reuse to prevent "Address already in use" errors
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        s.bind(("0.0.0.0", TCP_PORT))
        s.listen(1)
        
        print(f"[PI] Waiting for handshake on TCP port {TCP_PORT}...")
        
        conn, addr = s.accept()
        
        with conn:
            data = conn.recv(16)
            
            if data == b"SYN":
                # Send ACK with Pi timestamp (microseconds)
                pi_time_us = time.time_ns() // 1_000
                ack_msg = b"ACK" + struct.pack("!Q", pi_time_us)
                conn.sendall(ack_msg)
                
                print(f"[PI] Received SYN from {addr[0]}")
                print(f"[PI] Sent ACK with timestamp: {pi_time_us} us")

                print("[PI] Connection established\n")
                return (addr[0], 0.0)
            else:
                print(f"[WARN] Invalid handshake message: {data}")
                return None
