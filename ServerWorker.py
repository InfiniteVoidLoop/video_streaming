from random import randint
import sys, traceback, threading, socket
import io
from PIL import Image

from VideoStream import VideoStream

class ServerWorker:
    SETUP = 'SETUP'
    PLAY = 'PLAY'
    PAUSE = 'PAUSE'
    TEARDOWN = 'TEARDOWN'
    
    INIT = 0
    READY = 1
    PLAYING = 2
    state = INIT

    OK_200 = 0
    FILE_NOT_FOUND_404 = 1
    CON_ERR_500 = 2

    clientInfo = {}
    def __init__(self, clientInfo, streamManager):
        self.clientInfo = clientInfo
        self.streamManager = streamManager
        
    def run(self):
        threading.Thread(target=self.recvRtspRequest).start()
    
    def recvRtspRequest(self):
        """Receive RTSP request from the client."""
        connSocket = self.clientInfo['rtspSocket'][0]
        try:
            while True:            
                data = connSocket.recv(256)
                if data:
                    print("Data received:\n" + data.decode("utf-8"))
                    self.processRtspRequest(data.decode("utf-8"))
                else:
                    # Client disconnected
                    raise ConnectionError("Client disconnected")
        except BlockingIOError:
            pass
    
    def processRtspRequest(self, data):
        """Process RTSP request sent from the client."""
        # Get the request type
        request = data.split('\n')
        line1 = request[0].split(' ')
        requestType = line1[0]
        
        # Get the media file name
        filename = line1[1]
        
        # Get the RTSP sequence number 
        seq = request[1].split(' ')
        
        # Process SETUP request
        if requestType == self.SETUP:
            print("processing SETUP\n")

            previousTransport = self.clientInfo.get('transport')
            transport_line = request[2]
            self.clientInfo['transport'] = 'UDP'
            if 'TCP' in transport_line:
                self.clientInfo['transport'] = 'TCP'

            parts = transport_line.split(';')
            for part in parts:
                if 'client_port' in part:
                    self.clientInfo['rtpPort'] = part.split('=')[1].strip()
                    break

            if previousTransport == 'UDP' and self.clientInfo.get('transport') == 'TCP':
                self._unregisterMulticastClient()

            self._cleanupClientRtpResources()

            try:
                if self.clientInfo.get('transport', 'UDP') == 'TCP':
                    self.clientInfo['videoStream'] = VideoStream(filename)
                    self.clientInfo['rtpSeq'] = 0
                else:
                    self.streamManager.setup(filename)
                self.state = self.READY
                setupSucceeded = True
            except IOError:
                setupSucceeded = False
                self.replyRtsp(self.FILE_NOT_FOUND_404, seq[1])

            # Generate a randomized RTSP session ID
            if self.clientInfo.get('session') is None:
                self.clientInfo['session'] = randint(100000, 999999)

            # Send RTSP reply
            if setupSucceeded:
                if self.clientInfo.get('transport', 'UDP') != 'TCP':
                    self._registerMulticastClient()
                self.replyRtsp(self.OK_200, seq[1])

        # Process PLAY request      
        elif requestType == self.PLAY:
            if self.state == self.READY or self.clientInfo.get('multicastRegistered'):
                print("processing PLAY\n")
                try:
                    if self.clientInfo.get('transport', 'UDP') == 'TCP':
                        if self.state != self.READY:
                            return
                        self.clientInfo["rtpSocket"] = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        address = self.clientInfo['rtspSocket'][1][0]
                        port = int(self.clientInfo['rtpPort'])
                        print(f"Connecting RTP/TCP socket to {address}:{port}")
                        self.clientInfo["rtpSocket"].connect((address, port))
                        self.clientInfo['event'] = threading.Event()
                        self.clientInfo['worker']= threading.Thread(target=self.sendRtpWithTCP)
                        self.clientInfo['worker'].start()
                    else:
                        self.streamManager.play()

                    self.state = self.PLAYING
                    self.replyRtsp(self.OK_200, seq[1])
                except Exception:
                    self.replyRtsp(self.CON_ERR_500, seq[1])

        # Process PAUSE request
        elif requestType == self.PAUSE:
            if self.state == self.PLAYING or self.clientInfo.get('multicastRegistered'):
                print("processing PAUSE\n")
                self.state = self.READY

                if self.clientInfo.get('transport', 'UDP') == 'TCP':
                    if 'event' not in self.clientInfo or not self.clientInfo['event']:
                        return
                    self.clientInfo['event'].set()
                else:
                    self.streamManager.pause()

                self.replyRtsp(self.OK_200, seq[1])

        # Process TEARDOWN request
        elif requestType == self.TEARDOWN:
            print("processing TEARDOWN\n")

            if self.clientInfo.get('transport', 'UDP') == 'TCP':
                if 'event' in self.clientInfo and self.clientInfo['event']:
                    self.clientInfo['event'].set()
            else:
                self._unregisterMulticastClient()

            self.replyRtsp(self.OK_200, seq[1])
            self.state = self.INIT

            # Close the RTP socket
            if 'rtpSocket' in self.clientInfo and self.clientInfo['rtpSocket']:
                self.clientInfo['rtpSocket'].close()

    def close(self):
        """Release resources owned by this RTSP client session."""
        self._cleanupClientRtpResources()
        self._unregisterMulticastClient()

    def _registerMulticastClient(self):
        if self.clientInfo.get('multicastRegistered'):
            return

        session = self.clientInfo.get('session')
        if session is None:
            return

        self.streamManager.register_client(session)
        self.clientInfo['multicastRegistered'] = True

    def _unregisterMulticastClient(self):
        if not self.clientInfo.get('multicastRegistered'):
            return

        session = self.clientInfo.get('session')
        if session is not None:
            self.streamManager.unregister_client(session)

        self.clientInfo['multicastRegistered'] = False

    def _cleanupClientRtpResources(self):
        if 'event' in self.clientInfo and self.clientInfo['event']:
            try: self.clientInfo['event'].set()
            except: pass

        if 'worker' in self.clientInfo and self.clientInfo['worker']:
            try: self.clientInfo['worker'].join(timeout=0.2)
            except: pass

        if 'rtpSocket' in self.clientInfo and self.clientInfo['rtpSocket']:
            try: self.clientInfo['rtpSocket'].close()
            except: pass
            self.clientInfo['rtpSocket'] = None
    
    # NOTE: Implement fragmentation for frames exceeding the MTU
    def sendRtpWithTCP(self):
        """Send video frames over TCP frame-by-frame with a 5-byte ASCII size header."""
        while True:
            self.clientInfo['event'].wait(0.05) 
            
            # Stop sending if request is PAUSE or TEARDOWN
            if self.clientInfo['event'].isSet(): 
                break 
                
            data = self.clientInfo['videoStream'].nextFrame()
            if data: 
                try:
                    frameSize = len(data)
                    # Format size as a 5-byte ASCII string, padded with leading zeros (e.g. "06742")
                    sizeHeader = str(frameSize).zfill(5).encode()
                    # Send 5-byte size header followed by the raw frame data
                    self.clientInfo['rtpSocket'].sendall(sizeHeader + data)
                except Exception as e:
                    print(f"Sending video frame with TCP error: {e}")
                    break

    def replyRtsp(self, code, seq):
        """Send RTSP reply to the client."""
        if code == self.OK_200:
            #print("200 OK")
            reply = 'RTSP/1.0 200 OK\nCSeq: ' + seq + '\nSession: ' + str(self.clientInfo['session'])
            connSocket = self.clientInfo['rtspSocket'][0]
            connSocket.send(reply.encode())
        
        # Error messages
        elif code == self.FILE_NOT_FOUND_404:
            print("404 NOT FOUND")
        elif code == self.CON_ERR_500:
            print("500 CONNECTION ERROR")
