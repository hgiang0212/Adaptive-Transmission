"""
Metrics Computation module for Pi Receiver.

This module computes delay and packet loss metrics from received packet data.
"""

from typing import Dict


def compute_metrics(
    packet_dict: Dict[int, Dict[str, float]],
    total_expected: int,
    duration_seconds: float = 0.0
) -> Dict[str, float]:
    """
    Compute network quality metrics from received packets.
    
    Args:
        packet_dict: Dictionary mapping seq -> packet data (from receive_packets)
        total_expected: Total number of packets expected (typically 100)
        duration_seconds: Total reception duration in seconds (for throughput calculation)
    
    Returns:
        {
            "received": int,           # Number of packets received
            "loss_percent": float,     # Packet loss percentage
            "e2e_delay_avg_ms": float, # Average sender-to-receiver delay
            "e2e_delay_min_ms": float, # Minimum sender-to-receiver delay
            "e2e_delay_max_ms": float, # Maximum sender-to-receiver delay
            "inter_arrival_avg_ms": float, # Average packet receive interval
            "inter_arrival_min_ms": float, # Minimum packet receive interval
            "inter_arrival_max_ms": float, # Maximum packet receive interval
            "jitter_ms": float,        # Inter-arrival jitter (std deviation)
            "throughput_mbps": float   # Throughput in megabits per second
        }
    
    Special Cases:
        - If no packets received: all metrics return 0.0
        - Loss percentage: ((total_expected - received) / total_expected) * 100
        - Throughput formula: (received_packets * packet_size_bytes * 8) / (duration_seconds * 1_000_000)
        - Jitter: Standard deviation of inter-arrival times
    
    Note:
        e2e_delay is sender-to-receiver delay. It requires ESP UDP timestamps
        to be converted to Pi epoch time during the TCP handshake.
    
    Raises:
        ValueError: If total_expected is not positive
    """
    if total_expected <= 0:
        raise ValueError(f"total_expected must be positive, got {total_expected}")
    
    received = len(packet_dict)
    loss_percent = ((total_expected - received) / total_expected) * 100
    
    # Handle empty packet dictionary (total packet loss)
    if received == 0:
        return {
            "received": 0,
            "loss_percent": 100.0,
            "e2e_delay_avg_ms": 0.0,
            "e2e_delay_min_ms": 0.0,
            "e2e_delay_max_ms": 0.0,
            "inter_arrival_avg_ms": 0.0,
            "inter_arrival_min_ms": 0.0,
            "inter_arrival_max_ms": 0.0,
            "jitter_ms": 0.0,
            "throughput_mbps": 0.0
        }
    
    # Extract delay values
    delays = [pkt["e2e_delay_ms"] for pkt in packet_dict.values()]
    
    # Calculate inter-arrival jitter from actual receive order.
    recv_times = sorted(pkt["recv_time"] for pkt in packet_dict.values())
    
    # Compute inter-arrival intervals
    intervals = []
    jitter_ms = 0.0
    if len(recv_times) > 1:
        intervals = [(recv_times[i] - recv_times[i-1]) * 1000 for i in range(1, len(recv_times))]
        # Jitter = standard deviation of intervals
        mean_interval = sum(intervals) / len(intervals)
        variance = sum((x - mean_interval) ** 2 for x in intervals) / len(intervals)
        jitter_ms = variance ** 0.5
    
    # Calculate throughput (Mbps)
    # Formula: (received_packets * packet_size_bytes * 8) / (duration_seconds * 1_000_000)
    # Packet size = 524 bytes (12 header + 512 payload)
    packet_size_bytes = 524
    throughput_mbps = 0.0
    if duration_seconds > 0:
        throughput_mbps = (received * packet_size_bytes * 8) / (duration_seconds * 1_000_000)
    
    return {
        "received": received,
        "loss_percent": round(loss_percent, 2),
        "e2e_delay_avg_ms": round(sum(delays) / len(delays), 2),
        "e2e_delay_min_ms": round(min(delays), 2),
        "e2e_delay_max_ms": round(max(delays), 2),
        "inter_arrival_avg_ms": round(sum(intervals) / len(intervals), 2) if intervals else 0.0,
        "inter_arrival_min_ms": round(min(intervals), 2) if intervals else 0.0,
        "inter_arrival_max_ms": round(max(intervals), 2) if intervals else 0.0,
        "jitter_ms": round(jitter_ms, 2),
        "throughput_mbps": round(throughput_mbps, 2)
    }
