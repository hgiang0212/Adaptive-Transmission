"""
View continuous measurement summaries from summary.csv.
"""

import csv
import os
import sys
from datetime import datetime

SUMMARY_FILE = "summary.csv"


def _first_value(row, *keys, default="0"):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return default


def load_summary():
    if not os.path.exists(SUMMARY_FILE):
        print(f"[ERR] Summary file not found: {SUMMARY_FILE}")
        print("      Run the receiver first.")
        sys.exit(1)

    data = []
    with open(SUMMARY_FILE, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("timestamp") == "timestamp":
                continue

            data.append({
                "timestamp": datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S"),
                "cycle": int(row["cycle"]),
                "received": int(row["received"]),
                "loss": float(row["loss_%"]),
                "avg_delay": float(_first_value(
                    row,
                    "inter_arrival_avg_ms",
                    "e2e_delay_avg_ms",
                    "avg_delay_ms",
                )),
                "jitter": float(_first_value(row, "jitter_ms")),
                "throughput": float(_first_value(row, "throughput_mbps")),
            })
    return data


def print_table(data):
    if not data:
        print("[INFO] No summary rows found.")
        return

    print("\n" + "=" * 104)
    print(
        f"{'Cycle':<8} {'Time':<20} {'Recv':<8} {'Loss %':<10} "
        f"{'Inter-arr (ms)':<16} {'Jitter (ms)':<12} {'Mbps':<8}"
    )
    print("=" * 104)

    for row in data:
        print(
            f"{row['cycle']:<8} {row['timestamp'].strftime('%Y-%m-%d %H:%M:%S'):<20} "
            f"{row['received']:<8} {row['loss']:<10.1f} "
            f"{row['avg_delay']:<16.2f} {row['jitter']:<12.2f} "
            f"{row['throughput']:<8.2f}"
        )

    print("=" * 104)

    avg_loss = sum(r["loss"] for r in data) / len(data)
    avg_delay = sum(r["avg_delay"] for r in data) / len(data)
    avg_jitter = sum(r["jitter"] for r in data) / len(data)
    avg_throughput = sum(r["throughput"] for r in data) / len(data)

    print(f"\nTotal cycles: {len(data)}")
    print(f"Average packet loss: {avg_loss:.2f}%")
    print(f"Average inter-arrival: {avg_delay:.2f} ms")
    print(f"Average jitter: {avg_jitter:.2f} ms")
    print(f"Average throughput: {avg_throughput:.2f} Mbps")


def plot_trends(data):
    if not data:
        return

    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        print("\n[WARN] matplotlib is not installed. Run: pip install matplotlib")
        return

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("WiFi quality trends over time", fontsize=14, fontweight="bold")

    times = [r["timestamp"] for r in data]

    ax1 = axes[0, 0]
    ax1.plot(times, [r["loss"] for r in data], "o-", color="red", linewidth=2, markersize=4)
    ax1.set_title("Packet Loss (%)")
    ax1.set_ylabel("Loss (%)")
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

    ax2 = axes[0, 1]
    ax2.plot(times, [r["avg_delay"] for r in data], "o-", color="steelblue", linewidth=2, markersize=4)
    ax2.set_title("Inter-arrival Avg (ms)")
    ax2.set_ylabel("ms")
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

    ax3 = axes[1, 0]
    ax3.plot(times, [r["jitter"] for r in data], "o-", color="orange", linewidth=2, markersize=4)
    ax3.set_title("Jitter (ms)")
    ax3.set_ylabel("ms")
    ax3.set_xlabel("Time")
    ax3.grid(True, alpha=0.3)
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

    ax4 = axes[1, 1]
    ax4.plot(times, [r["throughput"] for r in data], "o-", color="purple", linewidth=2, markersize=4)
    ax4.set_title("Throughput (Mbps)")
    ax4.set_ylabel("Mbps")
    ax4.set_xlabel("Time")
    ax4.grid(True, alpha=0.3)
    ax4.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

    plt.tight_layout()
    plt.savefig("summary_trends.png", dpi=150, bbox_inches="tight")
    print("\n[OK] Trend chart saved to summary_trends.png")
    plt.show()


if __name__ == "__main__":
    summary = load_summary()
    print_table(summary)
    plot_trends(summary)
