from tkinter import *
import tkinter.messagebox
from PIL import Image, ImageTk
import socket, threading, sys, traceback, os

tkMessageBox = tkinter.messagebox

from RtpPacket import RtpPacket
from Config import DEFAULT_MEDIA_FILE, RTP_MULTICAST_GROUP, RTP_MULTICAST_PORT, STATE_MULTICAST_GROUP, STATE_MULTICAST_PORT
from StatePacket import PAUSED as STREAM_PAUSED, PLAYING as STREAM_PLAYING, READY as STREAM_READY, STOPPED as STREAM_STOPPED, decode_state_packet

CACHE_FILE_NAME = "cache-"
CACHE_FILE_EXT = ".jpg"

class Client:
    INIT = 0
    READY = 1
    PLAYING = 2
    state = INIT
    
    SETUP = 0
    PLAY = 1
    PAUSE = 2
    TEARDOWN = 3
    
    # Initiation..
    def __init__(self, master, serveraddr, serverport, filename=DEFAULT_MEDIA_FILE):
        self.master = master
        self.master.protocol("WM_DELETE_WINDOW", self.handler)
        self.createWidgets()
        self.serverAddr = serveraddr
        self.serverPort = int(serverport)
        self.rtpPort = RTP_MULTICAST_PORT
        self.fileName = filename
        self.rtspSeq = 0
        self.sessionId = 0
        self.requestSent = -1
        self.teardownAcked = 0
        self.connectToServer()
        self.frameNbr = -1
        self.transport = "UDP"
        self.quality = "multicast"
        self.rtpConnection = None
        self.frameBuffer = []
        # NOTE: Handle buffer access UI and network
        self.bufferLock = threading.Lock()
        self.minBufferSize = 15
        self.isBuffering = True

        # NOTE: Set up again request 
        self.isDraining = False
        self.pendingSetup = False
        self.pendingPause = False
        self.pauseInProgress = False
        self.setupInProgress = False
        self.stateSocket = None
        self.stateEvent = threading.Event()
        self.lastStateVersion = 0
        self.serverStreamState = STREAM_STOPPED
        self.startStateListener()
        
    def createWidgets(self):
        """Build GUI."""
        # Create Setup button
        self.setup = Button(self.master, width=20, padx=3, pady=3)
        self.setup["text"] = "Setup"
        self.setup["command"] = self.setupMovie
        self.setup.grid(row=1, column=0, padx=2, pady=2)
        
        # Create Play button        
        self.start = Button(self.master, width=20, padx=3, pady=3)
        self.start["text"] = "Play"
        self.start["command"] = self.playMovie
        self.start.grid(row=1, column=1, padx=2, pady=2)
        
        # Create Pause button           
        self.pause = Button(self.master, width=20, padx=3, pady=3)
        self.pause["text"] = "Pause"
        self.pause["command"] = self.pauseMovie
        self.pause.grid(row=1, column=2, padx=2, pady=2)
        
        # Create Teardown button
        self.teardown = Button(self.master, width=20, padx=3, pady=3)
        self.teardown["text"] = "Teardown"
        self.teardown["command"] =  self.exitClient
        self.teardown.grid(row=1, column=3, padx=2, pady=2)
        
        # Create a label to display the movie
        self.label = Label(self.master, height=19)
        self.label.grid(row=0, column=0, columnspan=4, sticky=W+E+N+S, padx=5, pady=5) 
    
    def setupMovie(self):
        """Setup button handler - Đã thêm cấu hình xử lý riêng cho trạng thái PAUSE (READY)"""
        if self.state == self.INIT:
            self.chooseMulticastStream()

        elif self.state == self.PLAYING:
            if tkMessageBox.askokcancel("Reset Video?", "Do you want to stop current playback and setup from the beginning?"):
                self.pendingSetup = True
                self.startDrainingPipeline() 

        elif self.state == self.READY:
            if tkMessageBox.askokcancel("Reset Video?", "Do you want to clear buffer and setup from the beginning?"):
                if hasattr(self, 'playEvent'):
                    self.playEvent.set()  # Signal play thread to stop
                with self.bufferLock:
                    self.frameBuffer.clear()  # Clear buffer immediately
                self.state = self.INIT
                self.isBuffering = True
                self.isDraining = False
                self.pendingSetup = False
                self.frameNbr = -1
                self.chooseMulticastStream()

    def startDrainingPipeline(self):
        # print("Stop network stream, draining remaining buffered frames to UI.")
        if hasattr(self, 'playEvent'):
            self.playEvent.set()  # Signal play thread to stop
        self.isDraining = True
        self.state = self.PLAYING

    def chooseMulticastStream(self):
        # Multicast media uses UDP only; keep setup explicit without offering TCP.
        self.quality_window = Toplevel(self.master)
        self.quality_window.title("Multicast Stream")
        
        # Center the pop-up on the screen
        w, h = 360, 150
        ws = self.master.winfo_screenwidth()
        hs = self.master.winfo_screenheight()
        x = (ws/2) - (w/2)
        y = (hs/2) - (h/2)
        self.quality_window.geometry('%dx%d+%d+%d' % (w, h, x, y))
        self.quality_window.resizable(False, False)
        
        # Apply premium look/styling
        self.quality_window.configure(bg="#1E1E1E")
        
        title_label = Label(
            self.quality_window, 
            text="Start UDP Multicast Stream",
            fg="#FFFFFF", 
            bg="#1E1E1E", 
            font=("Helvetica", 12, "bold")
        )
        title_label.pack(pady=12)
        
        info_label = Label(
            self.quality_window,
            text="RTP media is received from the shared UDP multicast group.",
            fg="#E0E0E0",
            bg="#1E1E1E",
            font=("Helvetica", 10)
        )
        info_label.pack(pady=8)
        
        btn_ok = Button(
            self.quality_window,
            text="OK",
            width=12,
            command=self.confirmMulticastStream,
            fg="#FFFFFF",
            bg="#007ACC",
            activeforeground="#FFFFFF",
            activebackground="#005999",
            relief=FLAT,
            font=("Helvetica", 10, "bold")
        )
        btn_ok.pack(pady=12)
        
        # Make dialog modal
        self.quality_window.transient(self.master)
        self.quality_window.grab_set()
        self.master.wait_window(self.quality_window)

    def confirmMulticastStream(self):
        self.quality = "multicast"
        self.transport = "UDP"

        self.quality_window.destroy()
        self.setupInProgress = True
        self.sendRtspRequest(self.SETUP)
    
    def exitClient(self):
        """Teardown button handler."""
        self.closeStateListener()
        self.sendRtspRequest(self.TEARDOWN)
        self.master.destroy() # Close the gui window
        try:
            os.remove(CACHE_FILE_NAME + self.quality.lower() + "-" + str(self.sessionId) + CACHE_FILE_EXT) # Delete the cache image from video
        except:
            pass

    def pauseMovie(self):
        """Pause button handler."""
        if self.state == self.PLAYING and not self.pauseInProgress:
            self.pauseInProgress = True
            self.pause.config(state=DISABLED)
            self.sendRtspRequest(self.PAUSE)
    
    def playMovie(self):
        """Play button handler."""
        if self.state == self.READY:
            self.startPlaybackPipeline(sendRtsp=True)

    def startPlaybackPipeline(self, sendRtsp=False):
        """Start local RTP receive/render loops, optionally requesting PLAY first."""
        if not hasattr(self, 'rtpSocket') or not self.rtpSocket:
            return

        if self.state == self.PLAYING and hasattr(self, '_rtpThread') and self._rtpThread.is_alive():
            return

        if self.state in (self.READY, self.PLAYING):
            # Kill the old listen thread before starting a new one.
            if hasattr(self, 'playEvent'):
                self.playEvent.set()  # Signal old thread to stop
            if hasattr(self, '_rtpThread') and self._rtpThread.is_alive(): self._rtpThread.join(timeout=1.0)  # Wait for it to die
            
            # Now safe to create new event and thread
            self.playEvent = threading.Event()
            self.playEvent.clear()

            with self.bufferLock:
                hasBufferedFrames = len(self.frameBuffer) > 0
            self.isBuffering = not hasBufferedFrames

            self._rtpThread = threading.Thread(target=self.listenRtpWithUDP)

            self._rtpThread.start()
            if sendRtsp:
                self.sendRtspRequest(self.PLAY)
                self.state = self.PLAYING
            else:
                self.state = self.PLAYING

            # Start UI clock play loop to render frames from buffer
            self.master.after(120, self.renderClientBufferLoop)

    def renderClientBufferLoop(self):
        """ Render frames from buffer using clock """
        if self.state != self.PLAYING and not self.isDraining:
            return

        with self.bufferLock:
            if self.isBuffering and not self.isDraining:
                if len(self.frameBuffer) >= self.minBufferSize:
                    self.isBuffering = False
                else: 
                    self.master.after(40, self.renderClientBufferLoop)  # Check again after 40ms
                    return

            if len(self.frameBuffer) > 0:
                frame_bytes = self.frameBuffer.pop(0)
                self.updateMovie(self.writeFrame(frame_bytes))
            else:
                if self.isDraining:
                    # print("Buffer completely drained. Stopping playback.")
                    self.isDraining = False
                    self.state = self.INIT
                    self.frameNbr = -1
                    if self.pendingPause:
                        self.pendingPause = False
                        self.state = self.READY

                    elif self.pendingSetup:
                        self.pendingSetup = False
                        self.state = self.INIT
                        self.chooseMulticastStream()
                    return
                else:
                    self.isBuffering = True
                    self.master.after(40, self.renderClientBufferLoop)  
                    return
                
        self.master.after(40, self.renderClientBufferLoop)  # Schedule next frame render after 40ms (25fps)
                    
    def listenRtpWithUDP(self):        
        """Listen for RTP packets using UDP"""
        buffer = []
        while not self.playEvent.isSet():
            try:
                data = self.rtpSocket.recv(2000)
                if data:
                    rtpPacket = RtpPacket()
                    rtpPacket.decode(data)
                     
                    currSeqNbr = rtpPacket.seqNum()
                    print("Current Seq Num: " + str(currSeqNbr))
                    print("Size of packet: " + str(len(data)))

                    if currSeqNbr > self.frameNbr: # Discard the late packet
                        self.frameNbr = currSeqNbr
                        buffer.append(rtpPacket.getPayload())

                        if rtpPacket.marker() == 1:
                            fullFrame = b''.join(buffer)
                            buffer.clear()

                            with self.bufferLock:
                                self.frameBuffer.append(fullFrame)
                                if len(self.frameBuffer) > 100:
                                    self.frameBuffer.pop(0)  # Discard oldest frame if buffer exceeds size

            except:
                buffer.clear()
                # Stop listening upon requesting PAUSE or TEARDOWN
                if self.playEvent.isSet(): 
                    break
                
                # Upon receiving ACK for TEARDOWN request,
                # close the RTP socket
                if self.teardownAcked == 1:
                    try:
                        self.rtpSocket.shutdown(socket.SHUT_RDWR)
                        self.rtpSocket.close()
                    except:
                        pass
                    break
                           
    def writeFrame(self, data):
        """Write the received frame to a temp image file. Return the image file."""
        cachename = CACHE_FILE_NAME + self.quality.lower() + "-" + str(self.sessionId) + CACHE_FILE_EXT
        file = open(cachename, "wb")
        file.write(data)
        file.close()
        
        return cachename
    
    def updateMovie(self, imageFile):
        """Update the image file as video frame in the GUI."""
        photo = ImageTk.PhotoImage(Image.open(imageFile))
        self.label.configure(image = photo, height=288) 
        self.label.image = photo
        
    def connectToServer(self):
        """Connect to the Server. Start a new RTSP/TCP session."""
        self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.rtspSocket.connect((self.serverAddr, self.serverPort))
        except:
            tkMessageBox.showwarning('Connection Failed', 'Connection to \'%s\' failed.' %self.serverAddr)

    def startStateListener(self):
        """Join the state multicast group and log official server state updates."""
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
            print(f"Unable to join state multicast group {STATE_MULTICAST_GROUP}:{STATE_MULTICAST_PORT}: {e}")
            try:
                self.stateSocket.close()
            except:
                pass
            self.stateSocket = None
            return

        self._stateThread = threading.Thread(target=self.listenStateMulticast, daemon=True)
        self._stateThread.start()
        print(f"Listening for state multicast on {STATE_MULTICAST_GROUP}:{STATE_MULTICAST_PORT}")

    def listenStateMulticast(self):
        """Receive official state multicast packets and apply them on the UI thread."""
        while not self.stateEvent.isSet():
            try:
                data, address = self.stateSocket.recvfrom(1024)
                packet = decode_state_packet(data)
                if packet['is_server']:
                    print(f"State multicast received from {address[0]}:{address[1]}: {packet['state']} v{packet['version']}")
                    self.master.after(0, self.applyServerState, packet['state'], packet['version'])
                else:
                    print(f"Ignoring non-server state multicast from {address[0]}:{address[1]}")
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception as e:
                print(f"Ignoring invalid state multicast packet: {e}")

    def applyServerState(self, streamState, version):
        """Update local playback from the server's official multicast state."""
        if version <= self.lastStateVersion:
            return
        self.lastStateVersion = version
        self.serverStreamState = streamState

        if streamState == STREAM_READY:
            if self.state == self.INIT:
                if not self.setupInProgress:
                    print("Server stream is READY; auto-sending SETUP for this client")
                    self.setupInProgress = True
                    self.transport = "UDP"
                    self.sendRtspRequest(self.SETUP)
                return
            self.state = self.READY
            self.isDraining = False
            self.pendingPause = False
            self.pauseInProgress = False
            self.pause.config(state=NORMAL)
            if hasattr(self, 'playEvent'):
                self.playEvent.set()

        elif streamState == STREAM_PLAYING:
            if self.state == self.INIT:
                if not self.setupInProgress:
                    print("Server stream is PLAYING; auto-sending SETUP for this client")
                    self.setupInProgress = True
                    self.transport = "UDP"
                    self.sendRtspRequest(self.SETUP)
                return
            if self.state == self.READY:
                self.startPlaybackPipeline(sendRtsp=False)

        elif streamState == STREAM_PAUSED:
            if self.state == self.INIT:
                return
            self.state = self.READY
            self.isDraining = False
            self.pendingPause = False
            self.pauseInProgress = False
            self.isBuffering = False
            if hasattr(self, 'playEvent'):
                self.playEvent.set()
            self.pause.config(state=NORMAL)

        elif streamState == STREAM_STOPPED:
            self.state = self.INIT
            self.isDraining = False
            self.pendingSetup = False
            self.pendingPause = False
            self.pauseInProgress = False
            self.setupInProgress = False
            self.isBuffering = True
            self.frameNbr = -1
            if hasattr(self, 'playEvent'):
                self.playEvent.set()
            with self.bufferLock:
                self.frameBuffer.clear()
            self.pause.config(state=NORMAL)

    def closeStateListener(self):
        """Stop the state multicast listener."""
        self.stateEvent.set()
        if self.stateSocket:
            try:
                self.stateSocket.close()
            except:
                pass
    
    def sendRtspRequest(self, requestCode):
        """Send RTSP request to the server."""  
        # Setup request
        if requestCode == self.SETUP:
            threading.Thread(target=self.recvRtspReply).start()
            # Update RTSP sequence number.
            self.rtspSeq += 1
            
            # Write the RTSP request to be sent.
            request = 'SETUP ' + self.fileName + ' RTSP/1.0\nCSeq: ' + str(self.rtspSeq) + '\nTransport: RTP/' + self.transport + '; client_port= ' + str(self.rtpPort)
            
            # Keep track of the sent request.
            self.requestSent = self.SETUP
        
        # Play request
        elif requestCode == self.PLAY and self.state == self.READY:
            # Update RTSP sequence number.
            self.rtspSeq += 1
            
            # Write the RTSP request to be sent.
            request = 'PLAY ' + self.fileName + ' RTSP/1.0\nCSeq: ' + str(self.rtspSeq) + '\nSession: ' + str(self.sessionId)
            
            # Keep track of the sent request.
            self.requestSent = self.PLAY
        
        # Pause request
        elif requestCode == self.PAUSE and self.state == self.PLAYING:
            # Update RTSP sequence number.
            self.rtspSeq += 1
            
            # Write the RTSP request to be sent.
            request = 'PAUSE ' + self.fileName + ' RTSP/1.0\nCSeq: ' + str(self.rtspSeq) + '\nSession: ' + str(self.sessionId)
            
            # Keep track of the sent request.
            self.requestSent = self.PAUSE
            
        # Teardown request
        elif requestCode == self.TEARDOWN and not self.state == self.INIT:
            # Update RTSP sequence number.
            self.rtspSeq += 1
            
            # Write the RTSP request to be sent.
            request = 'TEARDOWN ' + self.fileName + ' RTSP/1.0\nCSeq: ' + str(self.rtspSeq) + '\nSession: ' + str(self.sessionId)
            
            # Keep track of the sent request.
            self.requestSent = self.TEARDOWN
        else:
            return
        
        # Send the RTSP request using rtspSocket.
        self.rtspSocket.send(request.encode())
        
        print('\nData sent:\n' + request)
    
    def recvRtspReply(self):
        """Receive RTSP reply from the server."""
        while True:
            reply = self.rtspSocket.recv(1024)
            
            if reply: 
                self.parseRtspReply(reply.decode("utf-8"))
            
            # Close the RTSP socket upon requesting Teardown
            if self.requestSent == self.TEARDOWN:
                self.rtspSocket.shutdown(socket.SHUT_RDWR)
                self.rtspSocket.close()
                break
    
    def parseRtspReply(self, data):
        """Parse the RTSP reply from the server."""
        lines = data.split('\n')
        seqNum = int(lines[1].split(' ')[1])
        print("Received RTSP reply: " + data)
        # Process only if the server reply's sequence number is the same as the request's
        if seqNum == self.rtspSeq:
            session = int(lines[2].split(' ')[1])
            # New RTSP session ID
            if self.sessionId == 0:
                self.sessionId = session
            
            # Process only if the session ID is the same
            if self.sessionId == session:
                if int(lines[0].split(' ')[1]) == 200: 
                    if self.requestSent == self.SETUP:
                        # Update RTSP state.
                        self.state = self.READY
                        self.setupInProgress = False

                        with self.bufferLock:
                            self.frameBuffer.clear()
                        self.frameNbr = -1
                        self.isBuffering = True

                        # Open RTP port.
                        self.openRtpPort()
                        if self.serverStreamState == STREAM_PLAYING:
                            self.startPlaybackPipeline(sendRtsp=False)
                    elif self.requestSent == self.PLAY:
                        self.state = self.PLAYING
                    elif self.requestSent == self.PAUSE:
                        self.state = self.READY
                        self.pauseInProgress = False
                        self.pause.config(state=NORMAL)
                        # The play thread exits. A new thread is created on resume.
                        if hasattr(self, 'playEvent'):
                            self.playEvent.set()
                    elif self.requestSent == self.TEARDOWN:
                        self.state = self.INIT
                        # Flag the teardownAcked to close the socket.
                        self.teardownAcked = 1 
    
    def openRtpPort(self):
        """Clean up port & Open RTP socket binded to a specified port."""
        if hasattr(self, 'rtpSocket') and self.rtpSocket:
            try: 
                self.rtpSocket.shutdown(socket.SHUT_RDWR)
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
            print(f"Joined RTP multicast group {RTP_MULTICAST_GROUP}:{RTP_MULTICAST_PORT}")
        except Exception as e:
            tkMessageBox.showwarning('Unable to Join Multicast', f'Unable to join RTP multicast group {RTP_MULTICAST_GROUP}:{RTP_MULTICAST_PORT}: {e}')

    def handler(self):
        """Handler on explicitly closing the GUI window."""
        self.pauseMovie()
        if tkMessageBox.askokcancel("Quit?", "Are you sure you want to quit?"):
            self.exitClient()
        else: # When the user presses cancel, resume playing.
            self.playMovie()
