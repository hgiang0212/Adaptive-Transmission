"""
Main orchestration module for Pi Receiver.

This module coordinates the continuous measurement cycle by orchestrating
all modules: handshake, UDP reception, metrics computation, and logging.
"""

import time
from typing import Dict
from config import TOTAL_PKTS
from handshake import wait_for_handshake
from udp_receiver import receive_packets
from metrics import compute_metrics
from logger import save_logs


def print_results(metrics: Dict[str, float], cycle: int) -> None:
    """
    Print formatted results to console.
    
    Args:
        metrics: Computed metrics dictionary
        cycle: Current cycle number
    """
    print("\n══════════════ RESULT ══════════════")
    print(f"Cycle             : #{cycle}")
    print(f"Received          : {metrics['received']}/{TOTAL_PKTS}")
    print(f"Packet Loss       : {metrics['loss_percent']:.2f}%")
    print(f"Delay Avg         : {metrics['e2e_delay_avg_ms']:.2f} ms")
    print(f"Delay Min         : {metrics['e2e_delay_min_ms']:.2f} ms")
    print(f"Delay Max         : {metrics['e2e_delay_max_ms']:.2f} ms")
    print(f"Inter-arrival Avg : {metrics['inter_arrival_avg_ms']:.2f} ms")
    print(f"Inter-arrival Min : {metrics['inter_arrival_min_ms']:.2f} ms")
    print(f"Inter-arrival Max : {metrics['inter_arrival_max_ms']:.2f} ms")
    print(f"Jitter            : {metrics['jitter_ms']:.2f} ms")
    print(f"Throughput        : {metrics['throughput_mbps']:.2f} Mbps")
    print("════════════════════════════════════\n")


def main() -> None:
    """
    Run continuous measurement cycles until interrupted.
    
    Workflow per cycle:
        1. Wait for TCP handshake
        2. If handshake fails: wait 2 seconds, retry
        3. Receive UDP packets
        4. Compute metrics
        5. Save logs
        6. Print results to console
        7. Increment cycle counter
        8. Repeat
    
    Termination:
        - Ctrl+C (KeyboardInterrupt): print total cycles, exit gracefully
    """
    cycle_count = 0
    
    print("════════════════════════════════════")
    print(" Raspberry Pi UDP Receiver")
    print(" Modular Architecture")
    print("════════════════════════════════════\n")
    
    try:
        while True:
            # Handshake phase
            handshake_result = wait_for_handshake()
            if handshake_result is None:
                print("[PI] Handshake failed, retrying in 2 seconds...\n")
                time.sleep(2)
                continue
            
            esp_ip, clock_offset_ms = handshake_result
            print(f"[PI] Connected to ESP at {esp_ip}")
            print("[PI] ESP timestamp calibrated to Pi epoch time\n")
            
            # Reception phase
            packet_dict, duration = receive_packets(clock_offset_ms)
            
            # Metrics phase
            metrics = compute_metrics(packet_dict, TOTAL_PKTS, duration)
            
            # Logging phase
            log_paths = save_logs(packet_dict, metrics, cycle_count)
            
            # Display phase
            print_results(metrics, cycle_count)
            print(f"[PI] Logs saved: {log_paths[0]}")
            print(f"[PI] Summary: {log_paths[1]}\n")
            print("─" * 50 + "\n")
            
            cycle_count += 1
            
    except KeyboardInterrupt:
        print("\n[PI] Interrupted by user")
        print(f"[PI] Total cycles completed: {cycle_count}")
        print("[PI] Exiting gracefully...")
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        print(f"[ERROR] Cycles completed before crash: {cycle_count}")
        raise


if __name__ == "__main__":
    main()
