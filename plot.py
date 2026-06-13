"""
plot.py
=======
Đọc file logs/session_log.csv và xuất 4 đồ thị PNG trực quan hóa
các chỉ số mạng (packet_loss, avg_delay_ms, throughput_bps) theo thời gian.

Output:
    logs/plot_loss.png
    logs/plot_delay.png
    logs/plot_throughput.png
    logs/plot_combined.png
"""

import sys
import os
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl

# ── Cấu hình đường dẫn ────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH   = os.path.join(SCRIPT_DIR, "logs", "session_log.csv")
OUT_DIR    = os.path.join(SCRIPT_DIR, "logs")

# ── Cấu hình style đồ thị ─────────────────────────────────────────────────────
# Dùng serif font mô phỏng LaTeX, nền trắng, bảng màu Tableau tab10
mpl.rcParams.update({
    "font.family":       "serif",
    "mathtext.fontset":  "dejavuserif",   # math symbols dạng serif
    "figure.facecolor":  "white",
    "axes.facecolor":    "white",
    "axes.edgecolor":    "#333333",
    "axes.labelcolor":   "#333333",
    "xtick.color":       "#333333",
    "ytick.color":       "#333333",
    "text.color":        "#333333",
    "grid.color":        "#cccccc",
    "grid.linestyle":    "--",
    "grid.linewidth":    0.7,
    "axes.titlesize":    13,
    "axes.labelsize":    11,
    "xtick.labelsize":   9,
    "ytick.labelsize":   9,
    "legend.fontsize":   9,
    "figure.dpi":        150,
    "savefig.dpi":       150,
    "savefig.bbox":      "tight",
    "savefig.facecolor": "white",
})

# Bảng màu Tableau tab10 (trầm nhưng rõ nét trên nền trắng)
C_LOSS  = "#1f77b4"   # xanh lam  → packet_loss
C_DELAY = "#ff7f0e"   # cam       → avg_delay_ms
C_THR   = "#2ca02c"   # xanh lục  → throughput_bps

# ── 1. Đọc & kiểm tra file CSV ────────────────────────────────────────────────
try:
    df = pd.read_csv(CSV_PATH)
except FileNotFoundError:
    print(f"[ERROR] Không tìm thấy file: {CSV_PATH}")
    sys.exit(1)

# Kiểm tra các cột bắt buộc
REQUIRED_COLS = {"timestamp", "packet_loss", "avg_delay_ms", "throughput_bps"}
missing = REQUIRED_COLS - set(df.columns)
if missing:
    print(f"[ERROR] File CSV thiếu cột: {missing}")
    sys.exit(1)

print(f"[INFO] Đọc thành công {len(df)} dòng từ: {CSV_PATH}")

# ── 2. Tiền xử lý dữ liệu ─────────────────────────────────────────────────────
# Parse timestamp từ chuỗi 'YYYY-MM-DD HH:MM:SS' → datetime
df["timestamp"] = pd.to_datetime(df["timestamp"], format="%Y-%m-%d %H:%M:%S")

# Tạo cột t: elapsed time (giây) tính từ timestamp đầu tiên
df["t"] = (df["timestamp"] - df["timestamp"].iloc[0]).dt.total_seconds()

print(f"[INFO] Khoảng thời gian: 0 – {df['t'].iloc[-1]:.0f} giây "
      f"({len(df)} windows)")

# ── 3. Hàm tiện ích vẽ đồ thị đơn ────────────────────────────────────────────
def plot_single(x, y, title, ylabel, color, filename):
    """
    Vẽ một đồ thị line đơn và lưu thành file PNG.

    Args:
        x        (Series): trục x — elapsed time (s)
        y        (Series): trục y — chỉ số cần vẽ
        title    (str):    tiêu đề đồ thị
        ylabel   (str):    nhãn trục y kèm đơn vị
        color    (str):    mã màu hex (Tableau tab10)
        filename (str):    đường dẫn file PNG đầu ra
    """
    fig, ax = plt.subplots(figsize=(8, 3.8))

    ax.plot(x, y, color=color, linewidth=1.5, marker="o",
            markersize=3, markerfacecolor=color, markeredgewidth=0)

    ax.set_title(title, fontweight="bold", pad=10)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.5)
    ax.margins(x=0.01)        # bỏ khoảng trắng thừa hai bên x

    plt.tight_layout()
    fig.savefig(filename)
    plt.close(fig)
    print(f"[SAVED] {filename}")


# ── 4. Đồ thị 1: Packet Loss ──────────────────────────────────────────────────
plot_single(
    x        = df["t"],
    y        = df["packet_loss"],
    title    = "Packet Loss over Time",
    ylabel   = "Packet Loss (ratio)",
    color    = C_LOSS,
    filename = os.path.join(OUT_DIR, "plot_loss.png"),
)

# ── 5. Đồ thị 2: Average Delay ────────────────────────────────────────────────
plot_single(
    x        = df["t"],
    y        = df["avg_delay_ms"],
    title    = "Average Delay over Time",
    ylabel   = "Avg Delay (ms)",
    color    = C_DELAY,
    filename = os.path.join(OUT_DIR, "plot_delay.png"),
)

# ── 6. Đồ thị 3: Throughput ───────────────────────────────────────────────────
plot_single(
    x        = df["t"],
    y        = df["throughput_bps"],
    title    = "Throughput over Time",
    ylabel   = "Throughput (B/s)",
    color    = C_THR,
    filename = os.path.join(OUT_DIR, "plot_throughput.png"),
)

# ── 7. Đồ thị 4: Combined — 3 subplots dọc, shared x-axis ────────────────────
fig, axes = plt.subplots(
    nrows=3, ncols=1,
    figsize=(9, 8),
    sharex=True,           # dùng chung trục x
)
fig.suptitle("Network Metrics over Time", fontsize=14, fontweight="bold", y=1.01)

# Dữ liệu cho từng subplot
subplots_cfg = [
    (df["packet_loss"],    "Packet Loss (ratio)",  C_LOSS,  "Packet Loss over Time"),
    (df["avg_delay_ms"],   "Avg Delay (ms)",        C_DELAY, "Average Delay over Time"),
    (df["throughput_bps"], "Throughput (B/s)",      C_THR,   "Throughput over Time"),
]

for ax, (y_data, ylabel, color, title) in zip(axes, subplots_cfg):
    ax.plot(df["t"], y_data, color=color, linewidth=1.5, marker="o",
            markersize=3, markerfacecolor=color, markeredgewidth=0)
    ax.set_title(title, fontweight="bold", pad=6)
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.5)
    ax.margins(x=0.01)

# Chỉ subplot cuối mới hiển thị nhãn trục x (vì sharex=True)
axes[-1].set_xlabel("Time (s)")

plt.tight_layout()
combined_path = os.path.join(OUT_DIR, "plot_combined.png")
fig.savefig(combined_path)
plt.close(fig)
print(f"[SAVED] {combined_path}")

print("\n[DONE] Xuất 4 đồ thị thành công.")
