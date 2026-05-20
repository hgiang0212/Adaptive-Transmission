"""
Configuration module for Pi Receiver.

This module centralizes all configuration constants for the UDP packet receiver system.
All magic numbers and configuration values are defined here for easy maintenance.
"""

# Network Configuration
TCP_PORT = 5006  # Port for TCP handshake
UDP_PORT = 5005  # Port for UDP data reception

# Packet Configuration
PAYLOAD_LEN = 512   # Payload size in bytes (synced with ESP8266)
TOTAL_PKTS = 100    # Expected number of packets per cycle
STRUCT_FMT = "!IQ"  # Struct format: network byte order, uint32 + uint64
HEADER_SIZE = 12    # Header size: 4 bytes (uint32) + 8 bytes (uint64)

# Encryption Configuration (XOR cipher key - must match ESP8266)
ENCRYPTION_KEY = bytes([
    0x2B, 0x7E, 0x15, 0x16, 0x28, 0xAE, 0xD2, 0xA6,
    0xAB, 0xF7, 0x15, 0x88, 0x09, 0xCF, 0x4F, 0x3C
])

# Timeout Configuration
UDP_TIMEOUT = 15.0  # UDP socket timeout in seconds

# Logging Configuration
LOG_DIR = "logs"           # Directory for detailed packet logs
SUMMARY_FILE = "summary.csv"  # Summary metrics file
