import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

# ===== 1. Tạo dữ liệu giả =====
timesteps = 10
features = 3  # [packet_loss, delay, throughput]
num_classes = 3

np.random.seed(42)
X_list, y_list = [], []
for _ in range(5000):
    seq = np.zeros((timesteps, features))
    seq[:, 0] = np.clip(np.random.normal(0.1, 0.1, timesteps), 0, 1)  # loss
    seq[:, 1] = np.clip(np.random.normal(50, 20, timesteps), 5, 200)  # delay (ms)
    seq[:, 2] = np.clip(np.random.normal(1000, 300, timesteps), 100, 2000)  # throughput (B/s)

    avg_loss = np.mean(seq[:, 0])
    avg_delay = np.mean(seq[:, 1])
    if avg_loss < 0.05 and avg_delay < 60:
        label = 0  # SEND
    elif avg_loss < 0.3 and avg_delay < 100:
        label = 1  # COMPRESS
    else:
        label = 2  # WAIT
    X_list.append(seq)
    y_list.append(label)

X = np.array(X_list, dtype=np.float32)  # (N, 10, 3)
y = np.array(y_list, dtype=np.int64)


# ===== 2. Chuẩn hoá dữ liệu (Min-Max) =====
# Tính min, max trên tập huấn luyện cho từng feature (cột thứ 2)
X_reshaped = X.reshape(-1, features)  # (N*10, 3)
mins = X_reshaped.min(axis=0)
maxs = X_reshaped.max(axis=0)
# Tránh chia cho 0
maxs[maxs == mins] = 1.0
X_norm = (X - mins) / (maxs - mins)  # broadcast: (N,10,3) - (3,) -> ok


# Chia train/val
split = int(0.8 * len(X_norm))
X_train, X_val = X_norm[:split], X_norm[split:]
y_train, y_val = y[:split], y[split:]

train_dataset = TensorDataset(torch.tensor(X_train), torch.tensor(y_train))
val_dataset = TensorDataset(torch.tensor(X_val), torch.tensor(y_val))
train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
val_loader = DataLoader(val_dataset, batch_size=32)


# ===== 3. Định nghĩa mô hình GRU =====
class GRUNet(nn.Module):
    def __init__(self, input_size=3, hidden_size=16, num_classes=3):
        super().__init__()
        self.gru = nn.GRU(input_size, hidden_size, batch_first=True)
        self.fc = nn.Linear(hidden_size, num_classes)

    def forward(self, x):
        # x: (batch, seq_len, input_size)
        out, _ = self.gru(x)
        last_out = out[:, -1, :]  # lấy hidden state cuối cùng
        return self.fc(last_out)


model = GRUNet()
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(model.parameters(), lr=0.001)

# ===== 4. Huấn luyện =====
epochs = 20
for epoch in range(epochs):
    model.train()
    train_loss, correct = 0, 0
    for batch_x, batch_y in train_loader:
        optimizer.zero_grad()
        output = model(batch_x)
        loss = criterion(output, batch_y)
        loss.backward()
        optimizer.step()
        train_loss += loss.item() * len(batch_x)
        correct += (output.argmax(1) == batch_y).sum().item()
    train_loss /= len(train_loader.dataset)
    train_acc = correct / len(train_loader.dataset)

    # Validation
    model.eval()
    val_loss, val_correct = 0, 0
    with torch.no_grad():
        for batch_x, batch_y in val_loader:
            output = model(batch_x)
            val_loss += criterion(output, batch_y).item() * len(batch_x)
            val_correct += (output.argmax(1) == batch_y).sum().item()
    val_loss /= len(val_loader.dataset)
    val_acc = val_correct / len(val_loader.dataset)
    print(
        f"Epoch {epoch + 1}/{epochs} - Train Loss: {train_loss:.4f} Acc: {train_acc:.4f} | Val Loss: {val_loss:.4f} Acc: {val_acc:.4f}")

# ===== 5. Lưu model và tham số chuẩn hoá =====
torch.save({
    'model_state_dict': model.state_dict(),
    'mins': torch.tensor(mins, dtype=torch.float32),
    'maxs': torch.tensor(maxs, dtype=torch.float32),
    'hidden_size': 16,
    'input_size': 3,
    'num_classes': 3
}, 'gru_model.pt')
print("Model saved to gru_model.pt")