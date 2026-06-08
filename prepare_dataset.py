import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler

# Đọc dữ liệu thô
df = pd.read_csv("raw_metrics.csv")
# Sắp xếp theo window_id
df = df.sort_values("window_id")
windows = df[['packet_loss', 'avg_delay_ms', 'throughput_bps']].values

SEQ_LEN = 5   # 5 cửa sổ (10 giây)

# Hàm gán nhãn theo quy tắc (có thể tuỳ chỉnh)
def label_window(loss, delay, thr):
    LOSS_GOOD = 0.02
    LOSS_BAD  = 0.15
    DELAY_GOOD = 50.0
    DELAY_BAD  = 150.0
    THR_GOOD = 5000.0
    THR_BAD  = 1500.0

    if delay > DELAY_BAD or loss > LOSS_BAD or thr < THR_BAD:
        return 2   # WAIT
    if loss > LOSS_GOOD or delay > DELAY_GOOD or thr < THR_GOOD:
        return 1   # COMPRESS
    return 0       # SEND

X_list, y_list = [], []
for i in range(len(windows) - SEQ_LEN):
    seq = windows[i:i+SEQ_LEN]                # (5, 3)
    next_win = windows[i+SEQ_LEN]             # metrics của window thứ 6
    label = label_window(next_win[0], next_win[1], next_win[2])
    X_list.append(seq)
    y_list.append(label)

X = np.array(X_list, dtype=np.float32)        # (N, 5, 3)
y = np.array(y_list, dtype=np.int64)          # (N,)

# Chuẩn hóa Min-Max
scaler = MinMaxScaler()
X_flat = X.reshape(-1, 3)
scaler.fit(X_flat)
X_norm = scaler.transform(X_flat).reshape(X.shape)
mins = scaler.data_min_
maxs = scaler.data_max_

# Lưu dataset
np.savez("dataset.npz", X=X_norm, y=y, mins=mins, maxs=maxs)
print(f"Saved dataset: {X.shape[0]} samples, X shape {X.shape}, y shape {y.shape}")
print(f"Class distribution (SEND/COMPRESS/WAIT): {np.bincount(y)}")