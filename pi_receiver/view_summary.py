"""
view_summary.py - Xem tổng hợp kết quả đo liên tục
Đọc từ summary.csv và hiển thị biểu đồ theo thời gian
"""

import csv
import os
import sys
from datetime import datetime

SUMMARY_FILE = "summary.csv"


def load_summary():
    if not os.path.exists(SUMMARY_FILE):
        print(f"[ERR] Không tìm thấy file: {SUMMARY_FILE}")
        print("      Hãy chạy pi_receiver.py trước.")
        sys.exit(1)

    data = []
    with open(SUMMARY_FILE, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append({
                'timestamp': datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S'),
                'cycle': int(row['cycle']),
                'received': int(row['received']),
                'loss': float(row['loss_%']),
                'avg_delay': float(row['avg_delay_ms']),
                'jitter': float(row['jitter_ms']),
                'ber': float(row['avg_ber'])
            })
    return data


def print_table(data):
    print("\n" + "="*100)
    print(f"{'Chu kỳ':<8} {'Thời gian':<20} {'Nhận':<8} {'Loss %':<10} {'Delay (ms)':<12} {'Jitter (ms)':<12} {'BER':<12}")
    print("="*100)
    
    for row in data:
        print(f"{row['cycle']:<8} {row['timestamp'].strftime('%Y-%m-%d %H:%M:%S'):<20} "
              f"{row['received']:<8} {row['loss']:<10.1f} {row['avg_delay']:<12.2f} "
              f"{row['jitter']:<12.2f} {row['ber']:<12.8f}")
    
    print("="*100)
    
    # Thống kê tổng hợp
    avg_loss = sum(r['loss'] for r in data) / len(data)
    avg_delay = sum(r['avg_delay'] for r in data) / len(data)
    avg_jitter = sum(r['jitter'] for r in data) / len(data)
    avg_ber = sum(r['ber'] for r in data) / len(data)
    
    print(f"\nTổng số chu kỳ: {len(data)}")
    print(f"Packet Loss trung bình: {avg_loss:.2f}%")
    print(f"Delay trung bình: {avg_delay:.2f} ms")
    print(f"Jitter trung bình: {avg_jitter:.2f} ms")
    print(f"BER trung bình: {avg_ber:.8f}")


def plot_trends(data):
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        print("\n[WARN] matplotlib chưa được cài. Chạy: pip install matplotlib")
        return

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("Xu hướng chất lượng WiFi theo thời gian", fontsize=14, fontweight="bold")
    
    times = [r['timestamp'] for r in data]
    
    # 1. Packet Loss
    ax1 = axes[0, 0]
    ax1.plot(times, [r['loss'] for r in data], 'o-', color='red', linewidth=2, markersize=4)
    ax1.set_title("Packet Loss (%)")
    ax1.set_ylabel("Loss (%)")
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    
    # 2. Delay
    ax2 = axes[0, 1]
    ax2.plot(times, [r['avg_delay'] for r in data], 'o-', color='steelblue', linewidth=2, markersize=4)
    ax2.set_title("Inter-arrival Delay (ms)")
    ax2.set_ylabel("Delay (ms)")
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    
    # 3. Jitter
    ax3 = axes[1, 0]
    ax3.plot(times, [r['jitter'] for r in data], 'o-', color='orange', linewidth=2, markersize=4)
    ax3.set_title("Jitter (ms)")
    ax3.set_ylabel("Jitter (ms)")
    ax3.set_xlabel("Thời gian")
    ax3.grid(True, alpha=0.3)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    
    # 4. BER
    ax4 = axes[1, 1]
    ax4.plot(times, [r['ber'] for r in data], 'o-', color='purple', linewidth=2, markersize=4)
    ax4.set_title("BER (Bit Error Rate)")
    ax4.set_ylabel("BER")
    ax4.set_xlabel("Thời gian")
    ax4.grid(True, alpha=0.3)
    ax4.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    
    plt.tight_layout()
    plt.savefig("summary_trends.png", dpi=150, bbox_inches="tight")
    print("\n[OK] Biểu đồ xu hướng → summary_trends.png")
    plt.show()


if __name__ == "__main__":
    data = load_summary()
    print_table(data)
    plot_trends(data)
