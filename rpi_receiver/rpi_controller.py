import socket
import struct
import time
import csv
import os
import threading
import numpy as np
from collections import deque
import torch
import torch.nn as nn
import json
import asyncio
import websockets


class GRUClassifier(nn.Module):
    def __init__(self, input_size, hidden_size, num_layers, num_classes, dropout):
        super().__init__()
        proj_dim = input_size * 4
        self.input_proj = nn.Sequential(
            nn.Linear(input_size, proj_dim),
            nn.LayerNorm(proj_dim),
            nn.Tanh(),
        )
        self.gru = nn.GRU(
            input_size  = proj_dim,
            hidden_size = hidden_size,
            num_layers  = num_layers,
            batch_first = True,
            dropout     = dropout if num_layers > 1 else 0.0,
        )
        self.classifier = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(hidden_size, num_classes),
        )

    def forward(self, x):
        B, T, F = x.shape
        x = self.input_proj(x.view(B * T, F)).view(B, T, -1)
        out, _ = self.gru(x)
        return self.classifier(out[:, -1, :])


# ===== Cấu hình =====
UDP_IP           = "0.0.0.0"
UDP_PORT_DATA    = 4444
ESP8266_PORT_ACK   = 5555

HEADER_SIZE      = 10
WINDOW_MS        = 2000.0
FEATURES         = 3
PACKETS_PER_WIN  = 50
MODEL_PATH       = "gru_model.pt"
LOG_CSV          = "session_log.csv"
LOG_TXT          = "session_log.txt"

# Auto update next window when esp8266 send 50 packet completely
BURST_SILENCE_MS = 300


# ===== Load model =====
if not os.path.exists(MODEL_PATH):
    raise FileNotFoundError(f"Không tìm thấy model: {MODEL_PATH}")

checkpoint  = torch.load(MODEL_PATH, map_location=torch.device('cpu'))
WINDOW_SIZE = int(checkpoint['seq_len'])

model = GRUClassifier(
    input_size  = checkpoint['input_size'],
    hidden_size = checkpoint['hidden_size'],
    num_layers  = checkpoint['num_layers'],
    num_classes = checkpoint['num_classes'],
    dropout     = checkpoint['dropout'],
)
model.load_state_dict(checkpoint['model_state_dict'])
model.eval()

mins = checkpoint['mins'].numpy().astype(np.float32)
maxs = checkpoint['maxs'].numpy().astype(np.float32)
maxs[maxs == mins] = 1.0

DECISION_LABEL = {0: "SEND", 1: "COMPRESS", 2: "WAIT"}


# ===== Logging =====
csv_file   = open(LOG_CSV, 'w', newline='')
csv_writer = csv.writer(csv_file)
csv_writer.writerow(["timestamp", "window_id", "recv_pkts",
                     "packet_loss", "avg_delay_ms", "throughput_bps",
                     "decision", "decision_label", "gru_scores"])
txt_file   = open(LOG_TXT, 'w')

def log(msg: str):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line)
    txt_file.write(line + "\n")
    txt_file.flush()

def log_csv(window_id, recv, loss, delay, thr, decision, scores):
    csv_writer.writerow([
        time.strftime('%Y-%m-%d %H:%M:%S'),
        window_id, recv,
        f"{loss:.4f}", f"{delay:.2f}", f"{thr:.1f}",
        decision, DECISION_LABEL.get(decision, "?"),
        " ".join(f"{s:.4f}" for s in scores),
    ])
    csv_file.flush()



state_lock          = threading.Lock()
window_buffer       = deque(maxlen=WINDOW_SIZE)
current_window_id   = None
packets_this_window = []
last_packet_mono    = None    # time.monotonic() của gói cuối nhận được
window_flushed      = False   # True nếu window hiện tại đã được flush (tránh flush 2 lần)
esp8266_addr          = None
# ===== WebSocket server =====
WS_PORT    = 8765
_ws_loop   = None
_ws_clients = set()

async def _ws_handler(ws):
    _ws_clients.add(ws)
    try:
        await ws.wait_closed()
    finally:
        _ws_clients.discard(ws)

async def _ws_serve():
    async with websockets.serve(_ws_handler, "0.0.0.0", WS_PORT):
        await asyncio.Future()   # chạy mãi

def _start_ws():
    global _ws_loop
    _ws_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_ws_loop)
    _ws_loop.run_until_complete(_ws_serve())

threading.Thread(target=_start_ws, daemon=True).start()

def ws_broadcast(data: dict):
    """Gọi từ do_flush() để push data lên dashboard."""
    if not _ws_clients or _ws_loop is None:
        return
    msg = json.dumps(data)
    async def _send():
        await asyncio.gather(
            *[c.send(msg) for c in list(_ws_clients)],
            return_exceptions=True
        )
    asyncio.run_coroutine_threadsafe(_send(), _ws_loop)

# ===== Sockets =====
sock     = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT_DATA))
sock.settimeout(0.02)   # 20ms — đủ nhạy để phát hiện silence 300ms
ack_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


# ===== Hàm tiện ích =====
def send_ack(window_id: int, decision: int):
    if esp8266_addr is None:
        return
    msg = struct.pack('>HB', window_id, decision)
    ack_sock.sendto(msg, (esp8266_addr[0], ESP8266_PORT_ACK))
    log(f"  ACK → {esp8266_addr[0]}:{ESP8266_PORT_ACK}  "
        f"window={window_id}  decision={decision} ({DECISION_LABEL.get(decision, '?')})")


def handle_sync(addr):
    ts = int(time.time() * 1000) & 0xFFFFFFFF
    sock.sendto(struct.pack('>I', ts), addr)
    log(f"SYNC: ts={ts} ms → {addr}")


def parse_header(data: bytes):
    if len(data) < HEADER_SIZE:
        return None
    window_id   = (data[0] << 8) | data[1]
    seq         = data[2]
    total       = data[3]
    timestamp   = struct.unpack_from('>I', data, 4)[0]
    payload_len = (data[8] << 8) | data[9]
    return window_id, seq, total, timestamp, payload_len


def compute_metrics(packets):
    total_expected = packets[0][1]
    received       = len(packets)
    packet_loss    = 1.0 - received / total_expected if total_expected > 0 else 0.0

    delays = []
    for pkt in packets:
        diff = (pkt[4] - pkt[2]) & 0xFFFFFFFF
        delays.append(float(diff) if diff <= 0x7FFFFFFF else 0.0)
    avg_delay = float(np.mean(delays)) if delays else 0.0

    total_bytes    = sum(HEADER_SIZE + pkt[3] for pkt in packets)
    first_recv = packets[0][4]
    last_recv = packets[-1][4]
    duration_ms = last_recv - first_recv
    if duration_ms > 0:
        throughput_bps = total_bytes / (duration_ms / 1000.0)
    else:
        throughput_bps = 0.0
    return packet_loss, avg_delay, throughput_bps


def run_inference():
    seq_np   = np.array(window_buffer, dtype=np.float32).reshape(1, WINDOW_SIZE, FEATURES)
    seq_norm = np.clip((seq_np - mins) / (maxs - mins), 0.0, 1.0)
    tensor   = torch.tensor(seq_norm, dtype=torch.float32)
    with torch.no_grad():
        output   = model(tensor)
        scores   = output.numpy().flatten().tolist()
        decision = int(output.argmax(dim=1).item())
    return decision, scores


def flush_current_window(reason=""):
    """
    Flush window đang mở: compute metrics → GRU inference → gửi ACK.
    Gọi bên trong state_lock, nhưng send_ack/log chạy ngoài lock.
    Trả về (wid, packets) để caller thực hiện flush ngoài lock.
    """
    global window_flushed
    if window_flushed or current_window_id is None or not packets_this_window:
        return None, None
    window_flushed = True
    return current_window_id, list(packets_this_window)


def do_flush(wid, packets, reason=""):
    """Thực hiện flush ngoài lock."""
    recv_count = len(packets)
    loss, delay, thr = compute_metrics(packets)

    tag = f" [{reason}]" if reason else ""
    log(f"Window {wid:4d}{tag} | "
        f"recv={recv_count}/{PACKETS_PER_WIN}  "
        f"loss={loss:.1%}  delay={delay:.1f}ms  thr={thr:.0f}B/s")

    window_buffer.append((loss, delay, thr))

    if len(window_buffer) >= WINDOW_SIZE:
        decision, scores = run_inference()
        log(f"  GRU scores={[f'{s:.3f}' for s in scores]}  "
            f"→ decision={decision} ({DECISION_LABEL[decision]})")
    else:
        decision, scores = 0, []
        log(f"  Buffer {len(window_buffer)}/{WINDOW_SIZE} → fallback SEND")

    send_ack(wid, decision)
    log_csv(wid, recv_count, loss, delay, thr, decision, scores)
    ws_broadcast({
        "id": wid,
        "loss": round(loss, 4),
        "recv": recv_count,
        "delay": round(delay, 2),
        "thr": round(thr, 1),
        "decision": decision,
        "label": DECISION_LABEL[decision],
        "scores": [round(s, 4) for s in scores],
    })


# ===== Burst-silence detector thread =====
# Nguyên lý: ESP8266 gửi 50 gói trong ~50ms, sau đó im ~1950ms.
# Thread poll mỗi 20ms, phát hiện khoảng lặng >= BURST_SILENCE_MS sau khi
# đã nhận ít nhất 1 gói trong window hiện tại → burst kết thúc → flush ngay.
# Không phụ thuộc vào window_id, không cần heartbeat.
def silence_detector():
    global current_window_id, packets_this_window, last_packet_mono, window_flushed

    while True:
        time.sleep(0.02)   # poll 50 Hz

        wid, packets = None, None
        with state_lock:
            if (current_window_id is None
                    or window_flushed
                    or last_packet_mono is None
                    or not packets_this_window):
                continue

            silence = (time.monotonic() - last_packet_mono) * 1000   # ms
            if silence < BURST_SILENCE_MS:
                continue

            # Burst đã xong — lấy dữ liệu để flush ngoài lock
            wid, packets = flush_current_window(reason="SILENCE")

        if wid is not None:
            do_flush(wid, packets, reason="SILENCE")


# ===== Main =====
log("=" * 60)
log(f" RPi Controller  |  model: {MODEL_PATH}  seq_len={WINDOW_SIZE}")
log(f" Data :{UDP_PORT_DATA}   ACK → ESP32:{ESP8266_PORT_ACK}")
log(f" Burst-silence timeout: {BURST_SILENCE_MS}ms")
log(f" Log: {LOG_CSV}  {LOG_TXT}")
log("=" * 60)

detector = threading.Thread(target=silence_detector, daemon=True)
detector.start()

try:
    while True:
        try:
            data, addr = sock.recvfrom(2048)
        except socket.timeout:
            continue

        recv_time_ms = int(time.time() * 1000) & 0xFFFFFFFF

        wid_to_flush, pkts_to_flush = None, None

        with state_lock:
            last_packet_mono = time.monotonic()

            if esp8266_addr is None:

                esp8266_addr = addr
                log(f"Phát hiện ESP32 tại {esp8266_addr[0]}:{esp8266_addr[1]}")

            # SYNC
            if len(data) == 1 and data[0] == ord('S'):
                handle_sync(addr)
                continue

            # Parse header
            parsed = parse_header(data)
            if not parsed:
                log(f"WARN: gói không hợp lệ ({len(data)}B) từ {addr}")
                continue

            window_id, seq, total, timestamp, payload_len = parsed

            # Window mới bắt đầu
            if window_id != current_window_id:
                # Nếu window cũ chưa được flush bởi silence_detector
                # (ví dụ: burst sát nhau < 300ms gap), flush ngay tại đây
                if not window_flushed and current_window_id is not None and packets_this_window:
                    wid_to_flush, pkts_to_flush = flush_current_window(reason="BOUNDARY")

                # Khởi tạo window mới
                current_window_id   = window_id
                packets_this_window = [(seq, total, timestamp, payload_len, recv_time_ms)]
                window_flushed      = False
                log(f"\nWindow {window_id} — bắt đầu nhận...")

            else:
                # Gói trong cùng window — chỉ append nếu chưa flush
                if not window_flushed:
                    packets_this_window.append(
                        (seq, total, timestamp, payload_len, recv_time_ms))

        # Flush ngoài lock
        if wid_to_flush is not None:
            do_flush(wid_to_flush, pkts_to_flush)

except KeyboardInterrupt:
    log("Dừng controller.")
finally:
    sock.close()
    ack_sock.close()
    csv_file.close()
    txt_file.close()