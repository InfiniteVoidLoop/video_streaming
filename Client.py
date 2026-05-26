from tkinter import *
import tkinter.messagebox
from PIL import Image, ImageTk
import socket, threading, sys, traceback, os

tkMessageBox = tkinter.messagebox

from RtpPacket import RtpPacket

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
    def __init__(self, master, serveraddr, serverport, rtpport, filename):
        self.master = master
        self.master.protocol("WM_DELETE_WINDOW", self.handler)
        self.createWidgets()
        self.serverAddr = serveraddr
        self.serverPort = int(serverport)
        self.rtpPort = int(rtpport)
        self.fileName = filename
        self.rtspSeq = 0
        self.sessionId = 0
        self.requestSent = -1
        self.teardownAcked = 0
        self.connectToServer()
        self.frameNbr = -1
        self.transport = "UDP"
        self.rtpConnection = None
        
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
        """Setup button handler."""
        if self.state == self.INIT:
            self.chooseTransport()

    def chooseTransport(self):
        # Create a beautiful modal window to choose transport
        self.transport_window = Toplevel(self.master)
        self.transport_window.title("Transport Protocol")
        
        # Center the pop-up on the screen
        w, h = 320, 160
        ws = self.master.winfo_screenwidth()
        hs = self.master.winfo_screenheight()
        x = (ws/2) - (w/2)
        y = (hs/2) - (h/2)
        self.transport_window.geometry('%dx%d+%d+%d' % (w, h, x, y))
        self.transport_window.resizable(False, False)
        
        # Apply premium look/styling
        self.transport_window.configure(bg="#1E1E1E")
        
        title_label = Label(
            self.transport_window, 
            text="Choose Transport Protocol", 
            fg="#FFFFFF", 
            bg="#1E1E1E", 
            font=("Helvetica", 12, "bold")
        )
        title_label.pack(pady=12)
        
        self.transport_var = StringVar(value="UDP")
        
        frame = Frame(self.transport_window, bg="#1E1E1E")
        frame.pack()
        
        rb_udp = Radiobutton(
            frame, 
            text="UDP (Standard)", 
            variable=self.transport_var, 
            value="UDP", 
            fg="#E0E0E0", 
            bg="#1E1E1E", 
            selectcolor="#2C2C2C",
            activeforeground="#FFFFFF",
            activebackground="#1E1E1E",
            font=("Helvetica", 10)
        )
        rb_udp.pack(anchor=W, pady=2)
        
        rb_tcp = Radiobutton(
            frame, 
            text="TCP (Reliable)", 
            variable=self.transport_var, 
            value="TCP", 
            fg="#E0E0E0", 
            bg="#1E1E1E", 
            selectcolor="#2C2C2C",
            activeforeground="#FFFFFF",
            activebackground="#1E1E1E",
            font=("Helvetica", 10)
        )
        rb_tcp.pack(anchor=W, pady=2)
        
        btn_ok = Button(
            self.transport_window, 
            text="OK", 
            width=12, 
            command=self.confirmTransport,
            fg="#FFFFFF",
            bg="#007ACC",
            activeforeground="#FFFFFF",
            activebackground="#005999",
            relief=FLAT,
            font=("Helvetica", 10, "bold")
        )
        btn_ok.pack(pady=12)
        
        # Make dialog modal
        self.transport_window.transient(self.master)
        self.transport_window.grab_set()
        self.master.wait_window(self.transport_window)

    def confirmTransport(self):
        self.transport = self.transport_var.get()
        self.transport_window.destroy()
        self.sendRtspRequest(self.SETUP)
    
    def exitClient(self):
        """Teardown button handler."""
        self.sendRtspRequest(self.TEARDOWN)     
        self.master.destroy() # Close the gui window
        try:
            os.remove(CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT) # Delete the cache image from video
        except:
            pass

    def pauseMovie(self):
        """Pause button handler."""
        if self.state == self.PLAYING:
            self.sendRtspRequest(self.PAUSE)
    
    def playMovie(self):
        """Play button handler."""
        if self.state == self.READY:
            # Kill the old listen thread before starting a new one.
            if hasattr(self, 'playEvent'):
                self.playEvent.set()  # Signal old thread to stop
            if hasattr(self, '_rtpThread') and self._rtpThread.is_alive(): self._rtpThread.join(timeout=1.0)  # Wait for it to die
            
            # Now safe to create new event and thread
            self.playEvent = threading.Event()
            self.playEvent.clear()
            
            if self.transport == 'UDP':
                self._rtpThread = threading.Thread(target=self.listenRtpWithUDP)
            else:
                self._rtpThread = threading.Thread(target=self.listenRtpWithTCP)
                
            self._rtpThread.start()
            self.sendRtspRequest(self.PLAY)
            
    def listenRtpWithUDP(self):        
        """Listen for RTP packets using UDP"""
        buffer = []
        while True:
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
                            self.updateMovie(self.writeFrame(fullFrame))
                            buffer.clear()
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
                           
    def listenRtpWithTCP(self):        
        """Listen for video frames using TCP frame-by-frame"""
        try:
            # Accept connection from server with a timeout of 5 seconds
            self.rtpSocket.settimeout(5.0)
            self.rtpConnection, addr = self.rtpSocket.accept()
            self.rtpConnection.settimeout(0.5)
            print("RTP/TCP connection established with server")
        except Exception as e:
            print(f"RTP/TCP accept failed or timed out: {e}")
            return

        while True:
            try:
                # Read 5-byte length prefix (ASCII string)
                length_bytes = self.recv_all(self.rtpConnection, 5)
                if not length_bytes:
                    break
                length = int(length_bytes.decode())
                data = self.recv_all(self.rtpConnection, length)
                if not data:
                    break

                if data:
                    print("Received Frame over TCP")
                    print("Size of packet: " + str(len(data)))
                    self.updateMovie(self.writeFrame(data))
            except:
                # Stop listening upon requesting PAUSE or TEARDOWN
                if self.playEvent.isSet(): 
                    break
                
                # Upon receiving ACK for TEARDOWN request,
                # close the RTP socket and connection
                if self.teardownAcked == 1:
                    if hasattr(self, 'rtpConnection') and self.rtpConnection:
                        try:
                            self.rtpConnection.shutdown(socket.SHUT_RDWR)
                            self.rtpConnection.close()
                        except:
                            pass
                    try:
                        self.rtpSocket.shutdown(socket.SHUT_RDWR)
                        self.rtpSocket.close()
                    except:
                        pass
                    break

        if hasattr(self, 'rtpConnection') and self.rtpConnection:
            try:
                self.rtpConnection.close()
            except:
                pass

    def recv_all(self, sock, n):
        """Helper to receive exactly n bytes from a TCP socket."""
        data = b''
        while len(data) < n:
            try:
                packet = sock.recv(n - len(data))
                if not packet:
                    return None
                data += packet
            except socket.timeout:
                if len(data) > 0:
                    continue
                else:
                    raise
        return data
                    
    def writeFrame(self, data):
        """Write the received frame to a temp image file. Return the image file."""
        cachename = CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT
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
    
    def sendRtspRequest(self, requestCode):
        """Send RTSP request to the server."""  
        # Setup request
        if requestCode == self.SETUP and self.state == self.INIT:
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
                        
                        # Open RTP port.
                        self.openRtpPort() 
                    elif self.requestSent == self.PLAY:
                        self.state = self.PLAYING
                    elif self.requestSent == self.PAUSE:
                        self.state = self.READY
                        # The play thread exits. A new thread is created on resume.
                        self.playEvent.set()
                    elif self.requestSent == self.TEARDOWN:
                        self.state = self.INIT
                        # Flag the teardownAcked to close the socket.
                        self.teardownAcked = 1 
    
    def openRtpPort(self):
        """Open RTP socket binded to a specified port."""
        if self.transport == 'UDP':
            self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.rtpSocket.settimeout(0.5)
            try:
                self.rtpSocket.bind(('', self.rtpPort))
            except:
                tkMessageBox.showwarning('Unable to Bind', 'Unable to bind PORT=%d' %self.rtpPort)
        else: # TCP
            self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.rtpSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                self.rtpSocket.bind(('', self.rtpPort))
                self.rtpSocket.listen(1)
                print(f"RTP/TCP socket listening on port {self.rtpPort}")
            except:
                tkMessageBox.showwarning('Unable to Bind', 'Unable to bind PORT=%d' %self.rtpPort)

    def handler(self):
        """Handler on explicitly closing the GUI window."""
        self.pauseMovie()
        if tkMessageBox.askokcancel("Quit?", "Are you sure you want to quit?"):
            self.exitClient()
        else: # When the user presses cancel, resume playing.
            self.playMovie()
