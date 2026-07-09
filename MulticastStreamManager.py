import socket
import threading

from Config import RTP_MULTICAST_GROUP, RTP_MULTICAST_PORT, STATE_MULTICAST_GROUP, STATE_MULTICAST_PORT, MULTICAST_TTL
from RtpPacket import RtpPacket
from StatePacket import READY, PLAYING, PAUSED, STOPPED, encode_state_packet
from VideoStream import VideoStream


class MulticastStreamManager:
    MAX_RTP_PAYLOAD_SIZE = 1400

    def __init__(self):
        self.lock = threading.Lock()
        self.videoStream = None
        self.filename = None
        self.rtpSocket = None
        self.worker = None
        self.stopEvent = threading.Event()
        self.state = STOPPED
        self.stateVersion = 0
        self.rtpSeq = 0
        self.clientSessions = set()
        self._heartbeat = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat.start()

    def register_client(self, session):
        """Track a client that joined the shared multicast stream."""
        with self.lock:
            self.clientSessions.add(session)
            clientCount = len(self.clientSessions)

        print(f"Multicast client registered: {session} ({clientCount} active)")

    def unregister_client(self, session):
        """Remove one client and stop the stream only when no clients remain."""
        should_stop = False
        with self.lock:
            if session not in self.clientSessions:
                return

            self.clientSessions.remove(session)
            clientCount = len(self.clientSessions)
            should_stop = clientCount == 0

            if should_stop:
                self._stop_locked(close_socket=True)
                self.state = STOPPED

        print(f"Multicast client unregistered: {session} ({clientCount} active)")

        if should_stop:
            self._send_state_multicast_burst(STOPPED)

    def setup(self, filename):
        """Prepare one shared video stream for multicast delivery."""
        with self.lock:
            if self.videoStream is not None and self.filename == filename and self.state != STOPPED:
                currentState = self.state
                should_announce_ready = False
            else:
                self._stop_locked(close_socket=True)
                self.videoStream = VideoStream(filename)
                self.filename = filename
                self.rtpSeq = 0
                self.state = READY
                currentState = READY
                should_announce_ready = True

        if should_announce_ready:
            self._send_state_multicast(READY)
        elif currentState != STOPPED:
            self._send_state_multicast(currentState)

    def play(self):
        """Start or resume the shared multicast sender."""
        with self.lock:
            if self.videoStream is None:
                raise IOError

            self.stopEvent.clear()
            self._open_rtp_socket_locked()
            should_start = self.worker is None or not self.worker.is_alive()
            self.state = PLAYING
            if should_start:
                self.worker = threading.Thread(target=self._send_rtp_loop, daemon=True)
                self.worker.start()

        self._send_state_multicast_burst(PLAYING)

    def pause(self):
        """Pause the shared multicast sender without resetting the video."""
        with self.lock:
            if self.state == PAUSED:
                should_announce_paused = True
                worker = None
            elif self.state != PLAYING:
                return
            else:
                should_announce_paused = True
                self.state = PAUSED
                self.stopEvent.set()
                worker = self.worker

        if worker:
            worker.join(timeout=0.5)

        with self.lock:
            if self.worker is worker:
                self.worker = None

        if should_announce_paused:
            self._send_state_multicast_burst(PAUSED)

    def stop(self):
        """Stop the shared stream and release multicast resources."""
        with self.lock:
            self.clientSessions.clear()
            self._stop_locked(close_socket=True)
            self.state = STOPPED

        self._send_state_multicast_burst(STOPPED)

    def _heartbeat_loop(self):
        """Re-broadcast current state every 0.5s so late-joining clients sync fast."""
        import time
        while True:
            time.sleep(0.5)
            with self.lock:
                current = self.state
                version = self.stateVersion
            if current != STOPPED:
                self._send_state_multicast_direct(current, version)

    def _stop_locked(self, close_socket):
        self.stopEvent.set()
        worker = self.worker
        self.worker = None

        if worker and worker.is_alive() and worker is not threading.current_thread():
            self.lock.release()
            try:
                worker.join(timeout=0.5)
            finally:
                self.lock.acquire()

        if close_socket and self.rtpSocket:
            try:
                self.rtpSocket.close()
            except:
                pass
            self.rtpSocket = None

        self.videoStream = None
        self.filename = None

    def _open_rtp_socket_locked(self):
        if self.rtpSocket:
            return

        self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rtpSocket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, MULTICAST_TTL)
        print(f"RTP multicast sender ready: {RTP_MULTICAST_GROUP}:{RTP_MULTICAST_PORT} ttl={MULTICAST_TTL}")

    def _send_rtp_loop(self):
        while not self.stopEvent.wait(0.05):
            with self.lock:
                videoStream = self.videoStream
                rtpSocket = self.rtpSocket

            if videoStream is None or rtpSocket is None:
                break

            data = videoStream.nextFrame()
            if not data:
                with self.lock:
                    self.state = STOPPED
                    self.worker = None
                    self.stopEvent.set()
                self._send_state_multicast_burst(STOPPED)
                break

            self._send_frame(data, rtpSocket)

    def _send_frame(self, data, rtpSocket):
        frameSize = len(data)
        bytesSent = 0

        while bytesSent < frameSize and not self.stopEvent.isSet():
            chunkSize = min(self.MAX_RTP_PAYLOAD_SIZE, frameSize - bytesSent)
            chunkData = data[bytesSent:bytesSent + chunkSize]
            markerBit = (bytesSent + chunkSize) == frameSize

            with self.lock:
                packet = self._make_rtp(chunkData, self.rtpSeq, markerBit)
                self.rtpSeq += 1

            try:
                rtpSocket.sendto(packet, (RTP_MULTICAST_GROUP, RTP_MULTICAST_PORT))
                bytesSent += chunkSize
            except Exception as e:
                print(f"Sending multicast RTP error: {e}")
                break

    def _make_rtp(self, payload, seqnum, markerBit):
        rtpPacket = RtpPacket()
        rtpPacket.encode(2, 0, 0, 0, seqnum, markerBit, 26, 0, payload)
        return rtpPacket.getPacket()

    def _send_state_multicast(self, state):
        with self.lock:
            self.stateVersion += 1
            version = self.stateVersion
        self._send_state_multicast_direct(state, version)

    def _send_state_multicast_burst(self, state):
        """Send state 3 times 100ms apart (in background) to survive UDP packet loss."""
        import time
        with self.lock:
            self.stateVersion += 1
            version = self.stateVersion

        def _burst():
            for _ in range(3):
                self._send_state_multicast_direct(state, version)
                time.sleep(0.1)

        threading.Thread(target=_burst, daemon=True).start()

    def _send_state_multicast_direct(self, state, version):
        """Send a state packet without incrementing the version counter."""
        packet = encode_state_packet(state, version)
        stateSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            stateSocket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, MULTICAST_TTL)
            stateSocket.sendto(packet, (STATE_MULTICAST_GROUP, STATE_MULTICAST_PORT))
            print(f"State multicast sent: {state} v{version}")
        except Exception as e:
            print(f"Sending state multicast error: {e}")
        finally:
            stateSocket.close()

