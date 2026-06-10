# 🚀 Intelligent Edge-AI Adaptive Communication System



---

# 📖 Overview

This project proposes an intelligent Edge-AI communication framework capable of dynamically adapting IoT transmission behavior according to real-time network conditions.

The system continuously monitors:

* Packet Loss
* Delay
* Throughput

and uses a GRU neural network running on a Raspberry Pi edge device to determine the optimal transmission strategy.

The resulting decision is fed back to the ESP8266 node, creating a fully autonomous closed-loop communication system.

---

# 🎬 Live Dashboard Demo

> Real-time monitoring of packet loss, delay, throughput, GRU prediction scores and communication decisions.
<p align="center">
  <img src="docs/dashboard.gif" width="900"/>
</p>

---

# 🏗 System Architecture

The architecture consists of:

### Sensor Layer

* ESP8266 Node
* Data Collection
* UDP Packet Generation

### Communication Layer

* Wi-Fi Network
* UDP Protocol
* Cristian Time Synchronization

### Edge Computing Layer

* Raspberry Pi 4B
* Packet Collection
* Feature Extraction

### Edge AI Layer

* GRU Neural Network
* Temporal Sequence Learning
* Decision Prediction

### Feedback Layer

* ACK Transmission
* Adaptive Control

### Monitoring Layer

* WebSocket Dashboard
* CSV Logging
* TXT Logging

---

# 🔄 System Workflow

The complete workflow consists of:

1. Time Synchronization
2. UDP Data Transmission
3. Window Aggregation
4. Burst Detection
5. Feature Extraction
6. Sliding Window Buffering
7. GRU Inference
8. Decision Generation
9. ACK Feedback
10. Adaptive Transmission

<p align="center">
  <img src="docs/images/system_archi.png" width="900"/>
</p>

---

# 🧠 Edge AI Decision Engine

The Raspberry Pi computes three network metrics for every communication window:

| Feature     | Description        |
| ----------- | ------------------ |
| Packet Loss | Packet loss ratio  |
| Delay       | Average delay (ms) |
| Throughput  | Throughput (B/s)   |

These metrics form the GRU input sequence:

```text
[
 packet_loss,
 average_delay,
 throughput
]
```

The model predicts one of three classes.

---

## Decision Classes

| Class | Action   |
| ----- | -------- |
| 0     | SEND     |
| 1     | COMPRESS |
| 2     | WAIT     |

### SEND

```text
Payload = 64 Bytes
```

Normal communication.

---

### COMPRESS

```text
Payload = 32 Bytes
```

Reduced bandwidth usage.

---

### WAIT

```text
Pause = 5 Seconds
```

Congestion avoidance mode.

---

# 📊 Dashboard Features

The real-time dashboard displays:

* Window ID
* Packet Loss
* Delay
* Throughput
* GRU Scores
* Predicted Class
* Historical Trends

Communication updates are streamed using:

```text
WebSocket Port 8765
```

---

# 📂 Project Structure

```text
.
├── esp_sender/
│   └── esp_sender.ino
│
├── raspberry_pi/
│   ├── rpi_controller.py
│
├── logs/
│   ├── session_log.csv
│   └── session_log.txt
│
├── docs/
│   ├── images/
│   │   ├── system_architecture.png
│   │   └── dashboard.gif
│
├── src/ 
│   ├── collect_data/ 
│   │   ├── esp_data.ino 
│   │   ├── rpi_data.py
│   ├── dashboard.html
│   ├── train.py
│
├── requirements.txt
│
└── README.md
```

---

# ⚙ Installation

## Raspberry Pi

```bash
git clone https://github.com/hgiang0212/Adaptive-Transmission.git

pip install -r requirements.txt
```

Run controller:

```bash
python rpi_controller.py
```

---

## ESP8266

Upload:

```text
esp_sender.ino
```

using:

* Arduino IDE
* PlatformIO

Configure:

```cpp
const char* WIFI_SSID = "...";
const char* WIFI_PASSWORD = "...";
```

---

# 📈 Experimental Results

The proposed adaptive communication framework achieved:

| Metric                     | Improvement |
| -------------------------- | ----------- |
| Packet Loss                | ↓           |
| Delay                      | ↓           |
| Network Congestion         | ↓           |
| Bandwidth Efficiency       | ↑           |
| Autonomous Decision Making | ✓           |

---

# 🔬 Research Contributions

✔ Edge AI-based Communication Control

✔ GRU-based Network Condition Prediction

✔ Closed-loop Adaptive Transmission

✔ Lightweight IoT Deployment

✔ Real-time Dashboard Monitoring

✔ Raspberry Pi Edge Inference

---

# 🛠 Technology Stack

### Hardware

* ESP8266
* Raspberry Pi 4B

### Communication

* UDP
* Wi-Fi
* WebSocket

### Machine Learning

* PyTorch
* GRU

### Software

* Python
* Arduino C++

---

# ⭐ Acknowledgements

This project was developed as part of research on:

* Edge Intelligence
* Intelligent IoT Systems
* Adaptive Communication Networks
* Machine Learning for Network Optimization
