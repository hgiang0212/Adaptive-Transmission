"""
train_gru.py
============
GRU phân loại chất lượng mạng từ chuỗi 5 cửa sổ UDP.

FORMULATION ĐÚNG (khác với predict-future):
  Input  : window[t-4], window[t-3], ..., window[t]   → (5, 3)
  Output : decision cho window[t+1]: SEND / COMPRESS / WAIT

Lý do KHÔNG predict window[t+1]:
  - packet_loss WiFi thực tế có autocorrelation chỉ 0.31 (lag-1)
  - Markov-1 Bayes ceiling chỉ ~50% → không thể vượt qua
  - Formulation đúng: GRU phân loại STATE HIỆN TẠI của mạng
    từ 5 cửa sổ gần nhất (smoothing + trend) → quyết định tốt hơn
    threshold cứng vì khai thác được context (recovering/degrading)

3 FEATURES (chuẩn hóa min-max trên train):
  packet_loss    [0, 1]
  avg_delay_ms   [ms]
  throughput_bps [B/s]

LABELS (theo ngưỡng từ phân tích KMeans + Decision Tree):
  0 = SEND      (packet_loss < 0.20)
  1 = COMPRESS  (0.20 ≤ packet_loss < 0.54)
  2 = WAIT      (packet_loss ≥ 0.54)
"""

import os, random
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset, WeightedRandomSampler
from sklearn.model_selection import StratifiedShuffleSplit
from sklearn.metrics import classification_report, confusion_matrix
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

# ── Cấu hình ──────────────────────────────────────────────────────────────────
CSV_PATH    = "raw_metrics.csv"
MODEL_OUT   = "gru_model.pt"
PLOT_OUT    = "training_report.png"

SEQ_LEN     = 5
FEATURES    = ["packet_loss", "avg_delay_ms", "throughput_bps"]
N_FEATURES  = 3
N_CLASSES   = 3

HIDDEN_SIZE  = 32
NUM_LAYERS   = 1        # 1 layer đủ cho sequence ngắn (5 steps), tránh overfit
DROPOUT      = 0.2
LABEL_SMOOTH = 0.05

BATCH_SIZE  = 32
MAX_EPOCHS  = 300
LR          = 3e-4
PATIENCE    = 30

SEED = 42
torch.manual_seed(SEED); np.random.seed(SEED); random.seed(SEED)

LABEL_MAP = {0: "SEND", 1: "COMPRESS", 2: "WAIT"}

# ── 1. Load & clean ────────────────────────────────────────────────────────────
df = pd.read_csv(CSV_PATH)
df = df[
    (df["packet_loss"] >= 0) & (df["packet_loss"] <= 1) &
    (df["recv_pkts"] <= 50) &
    (df["avg_delay_ms"] < 500)
].sort_values("window_id").reset_index(drop=True)

def assign_label(r):
    loss = r["packet_loss"]
    if loss < 0.20: return 0
    if loss < 0.54: return 1
    return 2

df["label"] = df.apply(assign_label, axis=1)

print("=" * 60)
print("  GRU Network Quality Classifier")
print("=" * 60)
print(f"\nRows sau làm sạch: {len(df)}")
print("Phân phối nhãn:")
for c, n in LABEL_MAP.items():
    k = (df["label"] == c).sum()
    print(f"  {n:10s}: {k:4d}  ({k/len(df)*100:.1f}%)")

# ── 2. Sliding window — target là window HIỆN TẠI (cuối sequence) ─────────────
# X[i] = [window[t-4], ..., window[t]]   shape (5, 3)
# y[i] = label[window[t]]                → quyết định cho window[t+1]
raw_X = df[FEATURES].values.astype(np.float32)
raw_y = df["label"].values.astype(np.int64)
wids  = df["window_id"].values

X_seqs, y_seqs = [], []
for i in range(len(raw_X) - SEQ_LEN + 1):
    end_idx = i + SEQ_LEN - 1
    if end_idx >= len(raw_X): break
    # Kiểm tra window_id liên tiếp, không có gap
    if wids[end_idx] - wids[i] == SEQ_LEN - 1:
        X_seqs.append(raw_X[i : i + SEQ_LEN])   # (5, 3)
        y_seqs.append(raw_y[end_idx])            # label của window cuối

X_seqs = np.array(X_seqs, dtype=np.float32)
y_seqs = np.array(y_seqs, dtype=np.int64)

print(f"\nSố sequences: {len(X_seqs)}")
print(f"Shape X: {X_seqs.shape},  y: {y_seqs.shape}")
print(f"Label dist: SEND={np.sum(y_seqs==0)}  COMPRESS={np.sum(y_seqs==1)}  WAIT={np.sum(y_seqs==2)}")

# ── 3. Stratified split 70 / 15 / 15 ──────────────────────────────────────────
sss_tv = StratifiedShuffleSplit(n_splits=1, test_size=0.30, random_state=SEED)
idx_train, idx_temp = next(sss_tv.split(X_seqs, y_seqs))

sss_vt = StratifiedShuffleSplit(n_splits=1, test_size=0.50, random_state=SEED)
idx_val_rel, idx_test_rel = next(sss_vt.split(X_seqs[idx_temp], y_seqs[idx_temp]))
idx_val  = idx_temp[idx_val_rel]
idx_test = idx_temp[idx_test_rel]

X_train, y_train = X_seqs[idx_train], y_seqs[idx_train]
X_val,   y_val   = X_seqs[idx_val],   y_seqs[idx_val]
X_test,  y_test  = X_seqs[idx_test],  y_seqs[idx_test]

print(f"\nSplit: train={len(X_train)}  val={len(X_val)}  test={len(X_test)}")
for split_name, y_split in [("train", y_train), ("val", y_val), ("test", y_test)]:
    bc = np.bincount(y_split, minlength=3)
    print(f"  {split_name}: SEND={bc[0]}  COMPRESS={bc[1]}  WAIT={bc[2]}")

# ── 4. Normalize min-max fit on train ─────────────────────────────────────────
flat     = X_train.reshape(-1, N_FEATURES)
feat_min = flat.min(axis=0)
feat_max = flat.max(axis=0)
feat_max[feat_max == feat_min] = 1.0

def norm(X):
    return (X - feat_min) / (feat_max - feat_min)

X_train_n = norm(X_train)
X_val_n   = norm(X_val)
X_test_n  = norm(X_test)

# ── 5. DataLoaders với WeightedRandomSampler ──────────────────────────────────
train_ds = TensorDataset(torch.tensor(X_train_n), torch.tensor(y_train))
val_ds   = TensorDataset(torch.tensor(X_val_n),   torch.tensor(y_val))
test_ds  = TensorDataset(torch.tensor(X_test_n),  torch.tensor(y_test))

class_counts  = np.bincount(y_train, minlength=N_CLASSES).astype(float)
class_weights = 1.0 / (class_counts + 1e-8)
sample_w      = class_weights[y_train]
sampler       = WeightedRandomSampler(torch.tensor(sample_w, dtype=torch.float32),
                                      len(train_ds), replacement=True)

train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, sampler=sampler)
val_loader   = DataLoader(val_ds,   batch_size=BATCH_SIZE, shuffle=False)
test_loader  = DataLoader(test_ds,  batch_size=BATCH_SIZE, shuffle=False)

# ── 6. GRU Model ──────────────────────────────────────────────────────────────
class GRUClassifier(nn.Module):
    """
    GRU đơn giản, phù hợp với sequence ngắn (5 timestep, 3 features).
    Input projection tăng chiều để GRU có nhiều thông tin hơn.
    """
    def __init__(self):
        super().__init__()
        proj_dim = N_FEATURES * 4   # 12

        # Expand input từ 3 → 12 dimensions
        self.input_proj = nn.Sequential(
            nn.Linear(N_FEATURES, proj_dim),
            nn.LayerNorm(proj_dim),
            nn.Tanh(),
        )
        self.gru = nn.GRU(
            input_size  = proj_dim,
            hidden_size = HIDDEN_SIZE,
            num_layers  = NUM_LAYERS,
            batch_first = True,
            dropout     = DROPOUT if NUM_LAYERS > 1 else 0.0,
        )
        self.classifier = nn.Sequential(
            nn.Dropout(DROPOUT),
            nn.Linear(HIDDEN_SIZE, N_CLASSES),
        )

    def forward(self, x):
        # x: (B, T=5, F=3)
        B, T, F = x.shape
        x = self.input_proj(x.view(B * T, F)).view(B, T, -1)   # (B, T, proj_dim)
        out, _ = self.gru(x)                                     # (B, T, H)
        return self.classifier(out[:, -1, :])                    # (B, n_classes)


device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model  = GRUClassifier().to(device)
n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
print(f"\nDevice: {device}  |  Trainable params: {n_params:,}")

# Loss: label smoothing + class weight
cw_tensor = torch.tensor(
    class_weights / class_weights.sum() * N_CLASSES,
    dtype=torch.float32
).to(device)
criterion = nn.CrossEntropyLoss(weight=cw_tensor, label_smoothing=LABEL_SMOOTH)

optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-3)
scheduler = torch.optim.lr_scheduler.CosineAnnealingWarmRestarts(
    optimizer, T_0=50, T_mult=2, eta_min=1e-5
)

# ── 7. Training loop ───────────────────────────────────────────────────────────
def evaluate(loader):
    model.eval()
    correct = total = 0
    with torch.no_grad():
        for xb, yb in loader:
            xb, yb = xb.to(device), yb.to(device)
            correct += (model(xb).argmax(1) == yb).sum().item()
            total   += len(yb)
    return correct / total

def eval_per_class(loader):
    model.eval()
    preds_all, true_all = [], []
    with torch.no_grad():
        for xb, yb in loader:
            preds_all.extend(model(xb.to(device)).argmax(1).cpu().numpy())
            true_all.extend(yb.numpy())
    return np.array(preds_all), np.array(true_all)

history = {"loss": [], "train_acc": [], "val_acc": []}
best_val, best_ep, patience_ctr = 0.0, 0, 0

print("\n" + "─" * 62)
print(f"{'Ep':>5} {'Loss':>8} {'Train':>7} {'Val':>7} {'LR':>10}  Note")
print("─" * 62)

for ep in range(1, MAX_EPOCHS + 1):
    model.train()
    tot_loss = 0.0
    for xb, yb in train_loader:
        xb, yb = xb.to(device), yb.to(device)
        optimizer.zero_grad()
        loss = criterion(model(xb), yb)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        tot_loss += loss.item() * len(yb)

    scheduler.step()
    avg_loss  = tot_loss / len(train_ds)
    train_acc = evaluate(train_loader)
    val_acc   = evaluate(val_loader)
    lr_now    = optimizer.param_groups[0]["lr"]

    history["loss"].append(avg_loss)
    history["train_acc"].append(train_acc)
    history["val_acc"].append(val_acc)

    note = ""
    if val_acc > best_val:
        best_val, best_ep, patience_ctr = val_acc, ep, 0
        note = "← best"
        torch.save({
            "model_state_dict": model.state_dict(),
            "input_size":  N_FEATURES,
            "hidden_size": HIDDEN_SIZE,
            "num_layers":  NUM_LAYERS,
            "num_classes": N_CLASSES,
            "dropout":     DROPOUT,
            "seq_len":     SEQ_LEN,
            "features":    FEATURES,
            "mins":        torch.tensor(feat_min),
            "maxs":        torch.tensor(feat_max),
        }, MODEL_OUT)
    else:
        patience_ctr += 1
        if patience_ctr >= PATIENCE:
            print(f"{ep:>5} {avg_loss:>8.4f} {train_acc:>6.1%} {val_acc:>6.1%} {lr_now:>10.2e}  early stop")
            break

    if ep % 20 == 0 or ep == 1 or note:
        print(f"{ep:>5} {avg_loss:>8.4f} {train_acc:>6.1%} {val_acc:>6.1%} {lr_now:>10.2e}  {note}")

print("─" * 62)
print(f"Best val acc: {best_val:.1%}  @ epoch {best_ep}")

# ── 8. Test evaluation ─────────────────────────────────────────────────────────
checkpoint = torch.load(MODEL_OUT, map_location=device)
model.load_state_dict(checkpoint["model_state_dict"])

preds, trues = eval_per_class(test_loader)
acc = (preds == trues).mean()

print(f"\n{'='*60}")
print(f"  TEST ACCURACY: {acc:.4f}  ({acc:.1%})")
print(f"{'='*60}")
print(classification_report(trues, preds,
      target_names=[LABEL_MAP[i] for i in range(N_CLASSES)],
      zero_division=0))

# Baseline comparison
# Instant rule: dùng packet_loss của window cuối (timestep -1) trong mỗi sequence
# X_test[:, -1, 0] = packet_loss của window hiện tại
loss_last = X_test[:, -1, 0] * (feat_max[0] - feat_min[0]) + feat_min[0]
rule_pred  = np.where(loss_last < 0.20, 0, np.where(loss_last < 0.54, 1, 2))
rule_acc   = (rule_pred == y_test).mean()
print(f"Baseline (instant threshold on last window): {rule_acc:.1%}")
print(f"GRU vs baseline: {(acc - rule_acc)*100:+.1f}pp")

# ── 9. Plots ───────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 3, figsize=(16, 5))
fig.suptitle(
    f"GRU Network Quality Classifier  |  seq_len={SEQ_LEN}  hidden={HIDDEN_SIZE}\n"
    f"test acc={acc:.1%}  vs  instant-threshold baseline={rule_acc:.1%}",
    fontsize=11, y=1.02
)

ep_ax = range(1, len(history["loss"]) + 1)

ax = axes[0]
ax.plot(ep_ax, history["loss"], color="#5064d4", lw=1.5)
ax.axvline(best_ep, color="#c0392b", ls="--", lw=1.0, label=f"best @ ep{best_ep}")
ax.set_title("Training Loss"); ax.set_xlabel("Epoch"); ax.set_ylabel("Cross-Entropy")
ax.legend(fontsize=9); ax.grid(alpha=0.25)

ax = axes[1]
ax.plot(ep_ax, [v*100 for v in history["train_acc"]], label="Train", color="#5064d4", lw=1.5)
ax.plot(ep_ax, [v*100 for v in history["val_acc"]],   label="Val",   color="#e07b39", lw=1.5)
ax.axvline(best_ep, color="#c0392b", ls="--", lw=1.0)
ax.axhline(best_val*100,  color="#e07b39", ls=":", lw=0.8, label=f"best val {best_val:.1%}")
ax.axhline(rule_acc*100,  color="#27ae60", ls="-.", lw=1.0, label=f"rule baseline {rule_acc:.1%}")
ax.set_title("Accuracy"); ax.set_xlabel("Epoch"); ax.set_ylabel("Accuracy (%)")
ax.legend(fontsize=9); ax.grid(alpha=0.25); ax.set_ylim(0, 105)

cm  = confusion_matrix(trues, preds)
pct = cm.astype(float) / cm.sum(axis=1, keepdims=True) * 100
ax  = axes[2]
sns.heatmap(pct, annot=True, fmt=".1f", cmap="Blues", ax=ax,
            xticklabels=[LABEL_MAP[i] for i in range(N_CLASSES)],
            yticklabels=[LABEL_MAP[i] for i in range(N_CLASSES)],
            cbar_kws={"label": "% của true class"})
ax.set_title(f"Confusion Matrix — test acc {acc:.1%}")
ax.set_xlabel("Predicted"); ax.set_ylabel("True")

plt.tight_layout()
plt.savefig(PLOT_OUT, dpi=150, bbox_inches="tight")
print(f"\nModel : {MODEL_OUT}")
print(f"Report: {PLOT_OUT}")