"""
analyze_pi.py - Phân tích và vẽ biểu đồ từ pi_raw_log.csv
Chạy trên Raspberry Pi sau khi pi_receiver.py đã hoàn thành.

Yêu cầu: pip install matplotlib pandas
"""

import csv
import os
import sys

LOG_FILE = "pi_raw_log.csv"


def load_csv(path: str):
    if not os.path.exists(path):
        print(f"[ERR] Không tìm thấy file: {path}")
        print("      Hãy chạy pi_receiver.py trước để thu thập dữ liệu.")
        sys.exit(1)

    seqs, inter_delays, bers = [], [], []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            seqs.append(int(row["seq"]))
            inter_delays.append(float(row["inter_delay_ms"]))
            bers.append(float(row["ber"]))
    return seqs, inter_delays, bers


def print_summary(seqs, inter_delays, bers, total=100):
    n    = len(seqs)
    loss = (total - n) / total * 100

    # Bỏ qua packet đầu tiên (inter_delay = 0)
    valid_delays = [d for d in inter_delays if d > 0]
    
    avg_d = sum(valid_delays) / len(valid_delays) if valid_delays else 0
    min_d = min(valid_delays) if valid_delays else 0
    max_d = max(valid_delays) if valid_delays else 0

    # Jitter
    diffs  = [abs(valid_delays[i] - valid_delays[i-1]) for i in range(1, len(valid_delays))]
    jitter = sum(diffs) / len(diffs) if diffs else 0

    avg_ber = sum(bers) / n if n else 0

    print("══════════════ PHÂN TÍCH ══════════════")
    print(f"  Tổng nhận         : {n}/{total} packets")
    print(f"  Packet Loss       : {loss:.1f}%")
    print(f"  Inter-delay avg   : {avg_d:.2f} ms")
    print(f"  Inter-delay min   : {min_d:.2f} ms")
    print(f"  Inter-delay max   : {max_d:.2f} ms")
    print(f"  Jitter            : {jitter:.2f} ms")
    print(f"  BER avg           : {avg_ber:.8f}")
    print("═══════════════════════════════════════")


def plot(seqs, inter_delays, bers):
    try:
        import matplotlib.pyplot as plt
        import matplotlib.gridspec as gridspec
    except ImportError:
        print("[WARN] matplotlib chưa được cài. Chạy: pip install matplotlib")
        return

    # Bỏ packet đầu tiên (inter_delay = 0)
    plot_seqs = [s for s, d in zip(seqs, inter_delays) if d > 0]
    plot_delays = [d for d in inter_delays if d > 0]
    plot_bers = [b for s, b, d in zip(seqs, bers, inter_delays) if d > 0]

    fig = plt.figure(figsize=(12, 8))
    fig.suptitle("Kết quả đo lường WiFi (ESP → Pi)", fontsize=14, fontweight="bold")
    gs  = gridspec.GridSpec(2, 2, figure=fig, hspace=0.4, wspace=0.35)

    # ── 1. Inter-arrival delay theo seq ──
    ax1 = fig.add_subplot(gs[0, :])
    ax1.plot(plot_seqs, plot_delays, color="steelblue", linewidth=1, marker=".", markersize=3)
    avg_delay = sum(plot_delays) / len(plot_delays) if plot_delays else 0
    ax1.axhline(avg_delay, color="red", linestyle="--",
                linewidth=1, label=f"Avg = {avg_delay:.2f} ms")
    ax1.set_title("Inter-arrival Delay theo số thứ tự packet")
    ax1.set_xlabel("Sequence number")
    ax1.set_ylabel("Inter-arrival Delay (ms)")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # ── 2. Histogram delay ──
    ax2 = fig.add_subplot(gs[1, 0])
    ax2.hist(plot_delays, bins=20, color="steelblue", edgecolor="white", alpha=0.85)
    ax2.set_title("Phân phối Inter-arrival Delay")
    ax2.set_xlabel("Delay (ms)")
    ax2.set_ylabel("Số packet")
    ax2.grid(True, alpha=0.3)

    # ── 3. BER theo seq ──
    ax3 = fig.add_subplot(gs[1, 1])
    ax3.bar(plot_seqs, plot_bers, color="tomato", alpha=0.8, width=0.8)
    ax3.set_title("BER theo số thứ tự packet")
    ax3.set_xlabel("Sequence number")
    ax3.set_ylabel("BER")
    ax3.grid(True, alpha=0.3, axis="y")

    plt.savefig("pi_result_plot.png", dpi=150, bbox_inches="tight")
    print("[OK] Biểu đồ đã lưu → pi_result_plot.png")
    plt.show()


if __name__ == "__main__":
    seqs, inter_delays, bers = load_csv(LOG_FILE)
    print_summary(seqs, inter_delays, bers)
    plot(seqs, inter_delays, bers)
