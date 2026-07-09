from tkinter import *
import tkinter.messagebox
from PIL import Image, ImageTk
import socket, threading, sys, os, io

tkMessageBox = tkinter.messagebox

from RtpPacket import RtpPacket
from Config import DEFAULT_MEDIA_FILE, RTP_MULTICAST_GROUP, RTP_MULTICAST_PORT, STATE_MULTICAST_GROUP, STATE_MULTICAST_PORT
from StatePacket import PAUSED as STREAM_PAUSED, PLAYING as STREAM_PLAYING, READY as STREAM_READY, STOPPED as STREAM_STOPPED, decode_state_packet

class Client:
    INIT = 0
    READY = 1
    PLAYING = 2
    state = INIT

    SETUP = 0
    PLAY = 1
    PAUSE = 2
    TEARDOWN = 3

    def __init__(self, master, serveraddr, serverport, filename=DEFAULT_MEDIA_FILE):
        self.master = master
        self.master.protocol("WM_DELETE_WINDOW", self.handler)
        self.createWidgets()
        self.serverAddr = serveraddr
        self.serverPort = int(serverport)
        self.fileName = filename
        self.rtspSeq = 0
        self.sessionId = 0
        self.requestSent = -1
        self.teardownAcked = 0
        self.frameNbr = -1
        self.transport = "UDP"
        self.quality = "multicast"
        self.rtpSocket = None
        self.playEvent = threading.Event()

        # State sync
        self.setupInProgress = False
        self.stateSocket = None
        self.stateEvent = threading.Event()
        self.lastStateVersion = 0
        self.serverStreamState = STREAM_STOPPED

        self.connectToServer()
        self.startStateListener()

    def createWidgets(self):
        """Build GUI."""
        self.setup = Button(self.master, width=20, padx=3, pady=3)
        self.setup["text"] = "Setup"
        self.setup["command"] = self.setupMovie
        self.setup.grid(row=1, column=0, padx=2, pady=2)

        self.start = Button(self.master, width=20, padx=3, pady=3)
        self.start["text"] = "Play"
        self.start["command"] = self.playMovie
        self.start.grid(row=1, column=1, padx=2, pady=2)

        self.pause = Button(self.master, width=20, padx=3, pady=3)
        self.pause["text"] = "Pause"
        self.pause["command"] = self.pauseMovie
        self.pause.grid(row=1, column=2, padx=2, pady=2)

        self.teardown = Button(self.master, width=20, padx=3, pady=3)
        self.teardown["text"] = "Teardown"
        self.teardown["command"] = self.exitClient
        self.teardown.grid(row=1, column=3, padx=2, pady=2)

        # No fixed size — scales with video resolution
        self.label = Label(self.master, bg="black")
        self.label.grid(row=0, column=0, columnspan=4, padx=5, pady=5)

    def setupMovie(self):
        """Setup button handler."""
        if self.state == self.INIT:
            self.setupInProgress = True
            self.transport = "UDP"
            self.sendRtspRequest(self.SETUP)

    def playMovie(self):
        """Play button handler."""
        if self.state == self.READY:
            self.startPlaybackPipeline(sendRtsp=True)

    def pauseMovie(self):
        """Pause button handler."""
        if self.state == self.PLAYING:
            self.sendRtspRequest(self.PAUSE)

    def exitClient(self):
        """Teardown button handler."""
        self.sendRtspRequest(self.TEARDOWN)
        self.master.destroy()

    def startPlaybackPipeline(self, sendRtsp=False):
        """Start the RTP receive thread. Frames are displayed immediately as they arrive."""
        if not self.rtpSocket:
            return

        # Stop any existing receive thread
        self.playEvent.set()
        if hasattr(self, '_rtpThread') and self._rtpThread.is_alive():
            self._rtpThread.join(timeout=1.0)

        # Fresh event for new thread
        self.playEvent = threading.Event()
        self.frameNbr = -1          # last displayed RTP seq (marker-bit packet)

        self._rtpThread = threading.Thread(target=self.listenRtp, daemon=True)
        self._rtpThread.start()

        if sendRtsp:
            self.sendRtspRequest(self.PLAY)
        self.state = self.PLAYING

    def listenRtp(self):
        """Receive RTP packets and immediately display each complete frame.
        No buffering — raw read and display for easy debugging."""
        fragment_buffer = []
        while not self.playEvent.is_set():
            try:
                data = self.rtpSocket.recv(65535)
                if not data:
                    continue

                rtpPacket = RtpPacket()
                rtpPacket.decode(data)

                currSeqNbr = rtpPacket.seqNum()
                print(f"Seq: {currSeqNbr}  size: {len(data)}")

                # Accumulate all fragments unconditionally.
                # Only discard if we somehow receive a fragment with a seq num
                # that is behind the last *complete* frame we already displayed.
                fragment_buffer.append(rtpPacket.getPayload())

                # Marker bit = last fragment of this frame
                if rtpPacket.marker() == 1:
                    # Only display if this is a newer frame than the last one shown
                    if currSeqNbr > self.frameNbr:
                        self.frameNbr = currSeqNbr
                        frame_bytes = b''.join(fragment_buffer)
                        # Schedule GUI update on the main thread
                        self.master.after(0, self.updateMovie, frame_bytes)
                    fragment_buffer.clear()

            except socket.timeout:
                continue
            except OSError:
                break
            except Exception as e:
                print(f"listenRtp error: {e}")
                fragment_buffer.clear()

    def updateMovie(self, data):
        """Display a frame directly from raw bytes (no disk I/O)."""
        try:
            photo = ImageTk.PhotoImage(Image.open(io.BytesIO(data)))
            self.label.configure(image=photo)
            self.label.image = photo
        except Exception as e:
            print(f"Frame display error: {e}")

    # ── Network ────────────────────────────────────────────────────────────────

    def connectToServer(self):
        """Connect to the Server via RTSP/TCP."""
        self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.rtspSocket.connect((self.serverAddr, self.serverPort))
        except:
            tkMessageBox.showwarning('Connection Failed',
                f"Connection to '{self.serverAddr}' failed.")

    def openRtpPort(self):
        """Open and join the UDP multicast RTP socket."""
        if self.rtpSocket:
            try:
                self.rtpSocket.close()
            except:
                pass

        self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.rtpSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, 'SO_REUSEPORT'):
            try:
                self.rtpSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        self.rtpSocket.settimeout(0.5)
        try:
            self.rtpSocket.bind(('', RTP_MULTICAST_PORT))
            mreq = socket.inet_aton(RTP_MULTICAST_GROUP) + socket.inet_aton('0.0.0.0')
            self.rtpSocket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            print(f"Joined RTP multicast {RTP_MULTICAST_GROUP}:{RTP_MULTICAST_PORT}")
        except Exception as e:
            tkMessageBox.showwarning('Multicast Join Failed', str(e))

    # ── State Multicast Listener ───────────────────────────────────────────────

    def startStateListener(self):
        """Join the state multicast group to receive server state updates."""
        self.stateSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.stateSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, 'SO_REUSEPORT'):
            try:
                self.stateSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        try:
            self.stateSocket.bind(('', STATE_MULTICAST_PORT))
            mreq = socket.inet_aton(STATE_MULTICAST_GROUP) + socket.inet_aton('0.0.0.0')
            self.stateSocket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            self.stateSocket.settimeout(0.5)
        except Exception as e:
            print(f"Unable to join state multicast: {e}")
            self.stateSocket = None
            return

        self._stateThread = threading.Thread(target=self.listenStateMulticast, daemon=True)
        self._stateThread.start()
        print(f"Listening for state on {STATE_MULTICAST_GROUP}:{STATE_MULTICAST_PORT}")

    def listenStateMulticast(self):
        """Receive server state packets and apply them on the UI thread."""
        while not self.stateEvent.is_set():
            try:
                data, address = self.stateSocket.recvfrom(1024)
                packet = decode_state_packet(data)
                if packet['is_server']:
                    print(f"State from {address[0]}: {packet['state']} v{packet['version']}")
                    self.master.after(0, self.applyServerState, packet['state'], packet['version'])
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception as e:
                print(f"Invalid state packet: {e}")

    def applyServerState(self, streamState, version):
        """React to the server's broadcasted state."""
        if version <= self.lastStateVersion:
            return
        self.lastStateVersion = version
        self.serverStreamState = streamState

        if streamState == STREAM_READY:
            if self.state == self.INIT and not self.setupInProgress:
                print("Server READY → auto SETUP")
                self.setupInProgress = True
                self.transport = "UDP"
                self.sendRtspRequest(self.SETUP)
            elif self.state == self.PLAYING:
                # Server paused/stopped — stop our receive thread
                self.playEvent.set()
                self.state = self.READY

        elif streamState == STREAM_PLAYING:
            if self.state == self.INIT and not self.setupInProgress:
                print("Server PLAYING → auto SETUP")
                self.setupInProgress = True
                self.transport = "UDP"
                self.sendRtspRequest(self.SETUP)
            elif self.state == self.READY:
                print("Server PLAYING → auto PLAY")
                self.startPlaybackPipeline(sendRtsp=False)

        elif streamState == STREAM_PAUSED:
            if self.state == self.PLAYING:
                self.playEvent.set()
                self.state = self.READY

        elif streamState == STREAM_STOPPED:
            self.playEvent.set()
            self.state = self.INIT
            self.setupInProgress = False
            self.frameNbr = -1

    def closeStateListener(self):
        """Stop the state multicast listener."""
        self.stateEvent.set()
        if self.stateSocket:
            try:
                self.stateSocket.close()
            except:
                pass

    # ── RTSP ───────────────────────────────────────────────────────────────────

    def sendRtspRequest(self, requestCode):
        """Send an RTSP request to the server."""
        if requestCode == self.SETUP:
            threading.Thread(target=self.recvRtspReply, daemon=True).start()
            self.rtspSeq += 1
            request = (f"SETUP {self.fileName} RTSP/1.0\n"
                       f"CSeq: {self.rtspSeq}\n"
                       f"Transport: RTP/{self.transport}; client_port= {RTP_MULTICAST_PORT}")
            self.requestSent = self.SETUP

        elif requestCode == self.PLAY and self.state == self.READY:
            self.rtspSeq += 1
            request = (f"PLAY {self.fileName} RTSP/1.0\n"
                       f"CSeq: {self.rtspSeq}\n"
                       f"Session: {self.sessionId}")
            self.requestSent = self.PLAY

        elif requestCode == self.PAUSE and self.state == self.PLAYING:
            self.rtspSeq += 1
            request = (f"PAUSE {self.fileName} RTSP/1.0\n"
                       f"CSeq: {self.rtspSeq}\n"
                       f"Session: {self.sessionId}")
            self.requestSent = self.PAUSE

        elif requestCode == self.TEARDOWN and self.state != self.INIT:
            self.rtspSeq += 1
            request = (f"TEARDOWN {self.fileName} RTSP/1.0\n"
                       f"CSeq: {self.rtspSeq}\n"
                       f"Session: {self.sessionId}")
            self.requestSent = self.TEARDOWN
        else:
            return

        self.rtspSocket.send(request.encode())
        print(f"\nSent:\n{request}")

    def recvRtspReply(self):
        """Receive RTSP replies from the server (runs in a background thread)."""
        while True:
            try:
                reply = self.rtspSocket.recv(1024)
            except:
                break
            if reply:
                self.parseRtspReply(reply.decode("utf-8"))
            if self.requestSent == self.TEARDOWN:
                try:
                    self.rtspSocket.shutdown(socket.SHUT_RDWR)
                    self.rtspSocket.close()
                except:
                    pass
                break

    def parseRtspReply(self, data):
        """Parse the RTSP reply and advance state machine."""
        lines = data.split('\n')
        try:
            seqNum = int(lines[1].split(' ')[1])
        except:
            return
        print(f"Reply:\n{data}")

        if seqNum != self.rtspSeq:
            return

        try:
            session = int(lines[2].split(' ')[1])
        except:
            return

        if self.sessionId == 0:
            self.sessionId = session

        if self.sessionId != session:
            return

        if int(lines[0].split(' ')[1]) != 200:
            return

        if self.requestSent == self.SETUP:
            self.state = self.READY
            self.setupInProgress = False
            self.frameNbr = -1
            self.openRtpPort()
            # Immediate check: state multicast may have arrived before RTSP reply
            if self.serverStreamState == STREAM_PLAYING:
                self.startPlaybackPipeline(sendRtsp=False)
            else:
                # Fallback: re-check after 300ms in case state packet arrives late
                self.master.after(300, self._checkAutoPlay)

        elif self.requestSent == self.PLAY:
            self.state = self.PLAYING

        elif self.requestSent == self.PAUSE:
            # Do NOT stop here. Wait for the PAUSED state multicast so ALL clients
            # (including this one) stop on the exact same signal at the exact same time.
            pass  # applyServerState(STREAM_PAUSED) will call playEvent.set()

        elif self.requestSent == self.TEARDOWN:
            self.playEvent.set()
            self.state = self.INIT
            self.teardownAcked = 1

    def _checkAutoPlay(self):
        """Delayed fallback: start playback if server is PLAYING but we missed the state packet."""
        if self.state == self.READY and self.serverStreamState == STREAM_PLAYING:
            print("Delayed auto-play triggered")
            self.startPlaybackPipeline(sendRtsp=False)

    # ── Window ─────────────────────────────────────────────────────────────────

    def handler(self):
        """Handle window close button."""
        if tkMessageBox.askokcancel("Quit?", "Are you sure you want to quit?"):
            self.closeStateListener()
            self.playEvent.set()
            self.exitClient()
