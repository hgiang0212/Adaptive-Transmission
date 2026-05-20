"""
Logging module for Pi Receiver.

This module handles CSV logging of packet data and metrics.
"""

import os
import csv
from datetime import datetime
from typing import Dict, Tuple
from config import LOG_DIR, SUMMARY_FILE


SUMMARY_HEADER = [
    "timestamp",
    "cycle",
    "received",
    "loss_%",
    "e2e_delay_avg_ms",
    "e2e_delay_min_ms",
    "e2e_delay_max_ms",
    "inter_arrival_avg_ms",
    "inter_arrival_min_ms",
    "inter_arrival_max_ms",
    "jitter_ms",
    "throughput_mbps"
]


def _summary_needs_header(path: str) -> bool:
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return True

    with open(path, newline="") as f:
        reader = csv.reader(f)
        return not any(row == SUMMARY_HEADER for row in reader)


def save_logs(
    packet_dict: Dict[int, Dict[str, float]],
    metrics: Dict[str, float],
    cycle: int
) -> Tuple[str, str]:
    """
    Save per-packet details and summary metrics to CSV files.
    
    Args:
        packet_dict: Dictionary mapping seq -> packet data
        metrics: Computed metrics from compute_metrics()
        cycle: Current cycle number
    
    Returns:
        Tuple of (detail_log_path, summary_log_path)
    
    Files Created/Updated:
        1. logs/log_YYYYMMDD_HHMMSS.csv (per-packet details)
           Columns: seq, e2e_delay_ms, esp_ts_us, recv_time
        
        2. summary.csv (summary metrics, appended)
           Columns: timestamp, cycle, received, loss_%, 
                    e2e_delay_avg_ms, e2e_delay_min_ms, e2e_delay_max_ms,
                    jitter_ms, throughput_mbps
    
    Behavior:
        - Creates logs/ directory if it doesn't exist
        - Creates summary.csv with headers if it doesn't exist
        - Appends to summary.csv if it exists
        - Generates timestamped filename for detail logs
    
    Raises:
        OSError: If directory creation or file write fails (fatal error)
    """
    # Create logs directory if it doesn't exist
    try:
        if not os.path.exists(LOG_DIR):
            os.makedirs(LOG_DIR)
    except OSError as e:
        print(f"[ERROR] Cannot create log directory: {e}")
        raise
    
    # Generate timestamp for filenames
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    timestamp_display = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Save detail log
    detail_path = os.path.join(LOG_DIR, f"log_{timestamp}.csv")
    
    try:
        with open(detail_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["seq", "e2e_delay_ms", "esp_ts_us", "recv_time"])
            
            for seq in sorted(packet_dict.keys()):
                pkt = packet_dict[seq]
                writer.writerow([
                    seq,
                    pkt["e2e_delay_ms"],
                    pkt["esp_ts_us"],
                    pkt["recv_time"]
                ])
    except (OSError, csv.Error) as e:
        print(f"[ERROR] Cannot write detail log: {e}")
        raise
    
    # Save summary log
    summary_needs_header = _summary_needs_header(SUMMARY_FILE)
    
    try:
        with open(SUMMARY_FILE, "a", newline="") as f:
            writer = csv.writer(f)
            
            if summary_needs_header:
                writer.writerow(SUMMARY_HEADER)
            
            # Write metrics row
            writer.writerow([
                timestamp_display,
                cycle,
                metrics["received"],
                round(metrics["loss_percent"], 2),
                round(metrics["e2e_delay_avg_ms"], 2),
                round(metrics["e2e_delay_min_ms"], 2),
                round(metrics["e2e_delay_max_ms"], 2),
                round(metrics["inter_arrival_avg_ms"], 2),
                round(metrics["inter_arrival_min_ms"], 2),
                round(metrics["inter_arrival_max_ms"], 2),
                round(metrics["jitter_ms"], 2),
                round(metrics["throughput_mbps"], 2)
            ])
    except (OSError, csv.Error) as e:
        print(f"[ERROR] Cannot write summary log: {e}")
        raise
    
    return (detail_path, SUMMARY_FILE)
