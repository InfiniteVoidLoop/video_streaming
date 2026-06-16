# Multicast Design Checkpoint

This document records the current behavior and the target multicast design before code changes are made. It is intended as a safe checkpoint for review and rollback.

## Current Behavior

The current project uses RTSP over TCP for control and sends media per client.

Control path:

```text
Client -> Server
RTSP over TCP
SETUP / PLAY / PAUSE / TEARDOWN
```

Media path:

```text
ServerWorker -> one client
RTP over UDP, or custom frame delivery over TCP
```

For UDP streaming, the server sends each RTP packet directly to the requesting client's IP address and RTP port. Each client has its own `ServerWorker`, its own `VideoStream`, and its own media sending loop.

Current UDP media model:

```text
Client A SETUP/PLAY -> ServerWorker A -> RTP packets to Client A
Client B SETUP/PLAY -> ServerWorker B -> RTP packets to Client B
```

This is multi-client unicast, not multicast. Multiple clients can connect, but the server still sends separate media streams to each client.

## Target Multicast Behavior

The target design keeps RTSP as the unicast control protocol and changes RTP media delivery to UDP multicast.

Target control path:

```text
Client -> Server
RTSP over TCP
SETUP / PLAY / PAUSE / TEARDOWN
```

Target media path:

```text
Server -> RTP multicast group
UDP multicast
All joined clients receive the same RTP stream
```

Target media model:

```text
Server -> 239.10.10.1:5004
              -> Client A, if joined
              -> Client B, if joined
```

The server sends each RTP packet once to the multicast group. Clients receive video by joining the multicast group and listening on the multicast RTP port.

## Target State Model

The server owns the official shared stream state.

Proposed states:

```text
STOPPED
READY
PLAYING
PAUSED
```

The target design may use a separate state announcement multicast channel so all clients can observe the official state.

State channel:

```text
Server -> 239.10.10.2:7000
UDP multicast state announcements
```

Example flow:

```text
Client A sends RTSP PAUSE to server
Server changes shared stream state to PAUSED
Server multicasts STATE_PAUSED
All clients receive STATE_PAUSED and update local UI/playback state
```

Clients do not directly control each other. Clients request control from the server, and the server announces the official state.

## Assumptions

- RTSP remains TCP unicast per client.
- RTP media is multicast over UDP.
- The multicast stream is shared by all clients.
- PLAY and PAUSE are global stream controls in the multicast design.
- TEARDOWN should disconnect the requesting client; it should not necessarily stop the shared stream for all clients.
- Late-joining clients start from the current live stream position, not from the beginning of the video.
- A simple LAN/demo environment is assumed.
- Security and authentication for state packets are out of scope.

## Out Of Scope For Initial Multicast Work

- RTCP implementation.
- H.264 encoding changes.
- Authentication or anti-spoofing for multicast state messages.
- WAN multicast routing support.
- Production-grade stream discovery.

## Implementation Direction

The main architectural change is moving from per-client media streams to one shared multicast stream.

Current ownership:

```text
ServerWorker owns VideoStream and RTP sending loop
```

Target ownership:

```text
Shared multicast stream manager owns VideoStream and RTP sending loop
ServerWorker handles RTSP control requests and delegates shared stream control
```

This keeps the existing RTSP client/server structure while replacing the media delivery path with multicast.
