# High-Performance RTSP/RTP Video Streaming System

[![Language: Python](https://img.shields.io/badge/Language-Python%203-blue.svg?style=flat-square&logo=python)](https://www.python.org/)
[![Protocol: RTSP/RTP](https://img.shields.io/badge/Protocols-RTSP%20%2F%20RTP-orange.svg?style=flat-square)](#architecture)
[![Institution: HCMUS](https://img.shields.io/badge/HCMUS-Computer%20Networks-red.svg?style=flat-square)](https://hcmus.edu.vn/)

Real-time video streaming pipeline built from scratch in Python, utilizing **RTSP** (Real-Time Streaming Protocol) for control signaling, **RTP** (Real-Time Transport Protocol) for packetized media transmission, and **I/O Multiplexing** for scalable concurrent connections. 

Designed and implemented as a professional university project for the **Computer Networks** course at **Ho Chi Minh City University of Science (HCMUS)**.

---

## 🌟 Key Features

*   **⚡ Non-Blocking Multiplexed Server:** Built with the Python `selectors` module to implement I/O multiplexing. The server manages multiple client RTSP signaling channels concurrently on a single thread without blocking, ensuring optimal resource utilization.
*   **📡 UDP Multicast Media Architecture:** Video frames are packetized as RTP and sent once to a shared UDP multicast group. RTSP remains a per-client TCP control channel for SETUP, PLAY, PAUSE, and TEARDOWN.
*   **📶 Client-Side Jitter Buffer (Double-Buffered State Machine):**
    *   Implements a thread-safe, lock-protected queue that acts as a client caching layer.
    *   Utilizes a **Low-Water / High-Water Mark state machine** (`minBufferSize = 15` frames) to dynamically pause/resume visual rendering, absorbing network jitter and packet arrival fluctuations.
*   **🎬 Shared Live Stream Control:** Clients join the same multicast media group and follow the server's official stream state announcements.
*   **📦 UDP Fragmentation & RTP Reassembly:** Features robust fragmentation for UDP payloads exceeding MTU limits (1400 bytes). Employs RTP Marker bits to detect frame boundaries, facilitating perfect client-side JPEG reassembly.
*   **🎨 Premium Responsive Tkinter GUI:** A dark-themed, sleek user interface displaying live video playback, buffer state visualizations, and intuitive playback controls (Setup, Play, Pause, and Teardown).

---

## 📐 System Architecture

The application separates control messaging and media delivery channels, maintaining clean state machine transitions at both client and server nodes:

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Client as RTP/RTSP Client
    participant Server as Multiplexed RTSP Server

    User->>Client: Clicks "Setup"
    Client->>Server: RTSP SETUP (Transport: UDP)
    Server-->>Client: RTSP 200 OK (Session ID)
    
    User->>Client: Clicks "Play"
    Client->>Server: RTSP PLAY
    Server-->>Client: RTSP 200 OK
    Note over Server, Client: RTP Media Channel Activated
    
    rect rgb(20, 20, 30)
        Note over Server, Client: Media Streaming Loop
        Server->>Server: Read MJPEG Frame
        Server->>Server: Fragment Frame (MTU = 1400 bytes)
        Server->>Client: Send RTP Packets to UDP multicast group
        Client->>Client: Reassemble & Queue in Jitter Buffer
        Client->>Client: Render from Buffer (Min Buffer: 15 frames)
    end

    User->>Client: Clicks "Setup" (Reset Stream)
    Note over Client: Enters isDraining Pipeline Mode
    Note over Client: Plays out cached frames to avoid abrupt cut
    Client->>Server: RTSP SETUP
    Server->>Server: Re-initialize Shared Video Stream
    Server-->>Client: RTSP 200 OK
    Client->>Server: RTSP PLAY
    Server-->>Client: RTSP 200 OK
    Note over Server, Client: New RTP Media Channel Starts
```

---

## 🛠️ State Machine

The client state engine integrates network operations and buffer rendering transitions seamlessly:

```
                  +--------------------------------+
                  |              INIT              |
                  +--------------------------------+
                                  |
                                  | SETUP (Join Multicast)
                                  v
                  +--------------------------------+
                  |             READY              |
                  +--------------------------------+
                    ^                            |
    TEARDOWN / Reset |                            | PLAY
                     |                            v
                  +--------------------------------+
                  |            PLAYING             |
                  +--------------------------------+
                    |                            ^
                    | PAUSE                      | PLAY
                    v                            |
                  +--------------------------------+
                  |        PAUSED (READY)          |
                  +--------------------------------+
```

---

## 🚀 Quick Start

### 📋 Prerequisites
*   Python 3.8+
*   `Pillow` (PIL) library for GUI image rendering
*   Tkinter support installed on your system (e.g., `sudo apt-get install python3-tk` on Ubuntu/Debian)

### 📥 Installation & Setup
1. Clone the repository:
   ```bash
   git clone https://github.com/<your-username>/python_rtp.git
   cd python_rtp
   ```
2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install Pillow
   ```

### 💻 Running the Application

1. **Start the Multi-Client RTSP Server:**
   ```bash
   python Server.py <server_port>
   
   # Example:
   python Server.py 8554
   ```
2. **Launch the Video Client:**
   ```bash
   python ClientLauncher.py <server_ip> <server_port> <rtp_port> <video_file>
   
   # Example (running client locally connecting to server):
   python ClientLauncher.py 127.0.0.1 8554 25000 movie.Mjpeg
   ```

### 📡 Multicast Demo

The RTSP server still listens on the port you pass to `Server.py`, but the media and state channels use fixed multicast groups from `Config.py`:

```text
RTP media multicast:  239.10.10.1:5004
State multicast:      239.10.10.2:7000
Multicast TTL:        1
```

Run one server:

```bash
python Server.py 8554
```

Then launch two or more clients in separate terminals:

```bash
python ClientLauncher.py 127.0.0.1 8554 25000 movie.Mjpeg
python ClientLauncher.py 127.0.0.1 8554 25001 movie.Mjpeg
```

The `<rtp_port>` argument is kept for launcher compatibility. In multicast mode, clients join the shared RTP multicast port `5004` instead of using a unique RTP media port.

Expected demo flow:

```text
1. Start the server.
2. Start Client A and click Setup.
3. Start Client B and click Setup.
4. Click Play from either client.
5. Both clients should follow the same server stream state and receive the same RTP multicast media.
6. Click Pause from either client to pause the shared stream for all clients.
7. Close one client; the other client should remain connected unless it is the last active client.
```

Useful console logs during the demo:

```text
Multicast client registered: <session> (<count> active)
RTP multicast sender ready: 239.10.10.1:5004 ttl=1
State multicast sent: PLAYING v<version>
Joined RTP multicast group 239.10.10.1:5004
Listening for state multicast on 239.10.10.2:7000
State multicast received from <server>:<port>: PLAYING v<version>
```

---

## 📁 Repository Structure

```hl
.
├── Client.py             # RTSP Client core logic & Jitter Buffer controls
├── ClientLauncher.py     # GUI and Client initialization entry point
├── Config.py             # Shared multicast group, port, and TTL settings
├── MulticastStreamManager.py # Shared RTP multicast sender and server state owner
├── RtpPacket.py          # RTP Packet encapsulation & header parsing (12-byte headers)
├── Server.py             # Non-blocking I/O multiplexing RTSP Server entry point
├── ServerWorker.py       # RTSP State Machine, TCP/UDP Media Streamer, Frame Fragmenter
├── StatePacket.py        # UDP multicast state announcement encoder/decoder
├── VideoStream.py        # MJPEG parser and frame extraction engine
├── movie.Mjpeg           # Sample MJPEG video file
├── doc/
│   ├── report_template.pdf  # Comprehensive system specification report
│   └── report_template.tex  # LaTeX source file of the report
└── README.md             # This documentation
```

---

## 👥 Authors

*   **Đặng Võ Hồng Phúc** - HCMUS
*   **Trịnh Chấn Duy** - HCMUS

---

## 📄 License
This project is developed for educational purposes under the Computer Networks curriculum at HCMUS. Feel free to use and build upon this code.
