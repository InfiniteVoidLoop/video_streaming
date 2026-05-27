from random import randint
import sys, traceback, threading, socket
import io
from PIL import Image

from VideoStream import VideoStream
from RtpPacket import RtpPacket

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
    rtpSeq = 0 
    def __init__(self, clientInfo):
        self.clientInfo = clientInfo
        
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
            if 'event' in self.clientInfo and self.clientInfo['event']:
                try: self.clientInfo['event'].set()
                except: pass
                
            if 'worker' in self.clientInfo and self.clientInfo['worker']:
                try: self.clientInfo['worker'].join(timeout=0.2)
                except: pass
                
            if 'rtpSocket' in self.clientInfo and self.clientInfo['rtpSocket']:
                try: self.clientInfo['rtpSocket'].close()
                except: pass            
            print("Cleaned up previous session resources")
            
            try:
                self.clientInfo['videoStream'] = VideoStream(filename)
                self.state = self.READY
            except IOError:
                self.replyRtsp(self.FILE_NOT_FOUND_404, seq[1])

            self.rtpSeq = 0
            # Generate a randomized RTSP session ID
            if self.clientInfo.get('session') is None:
                self.clientInfo['session'] = randint(100000, 999999)
                
            # Send RTSP reply
            self.replyRtsp(self.OK_200, seq[1])
                
            # Parse Transport header
            transport_line = request[2]
            self.clientInfo['transport'] = 'UDP'
            if 'TCP' in transport_line:
                self.clientInfo['transport'] = 'TCP'
                
                # Extract client_port robustly
            parts = transport_line.split(';')
            for part in parts:
                if 'client_port' in part:
                    self.clientInfo['rtpPort'] = part.split('=')[1].strip()
                    print("Successfully parsed client_port: " + self.clientInfo['rtpPort'])
                    break
                        
        # Process PLAY request      
        elif requestType == self.PLAY:
            if self.state == self.READY:
                print("processing PLAY\n")
                self.state = self.PLAYING
                
                # Create a new socket for RTP
                if self.clientInfo.get('transport', 'UDP') == 'TCP':
                    self.clientInfo["rtpSocket"] = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    address = self.clientInfo['rtspSocket'][1][0]
                    port = int(self.clientInfo['rtpPort'])
                    print(f"Connecting RTP/TCP socket to {address}:{port}")
                    self.clientInfo["rtpSocket"].connect((address, port))
                else:
                    self.clientInfo["rtpSocket"] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                
                self.replyRtsp(self.OK_200, seq[1])
                
                # Create a new thread and start sending RTP packets
                self.clientInfo['event'] = threading.Event()
                self.clientInfo['worker']= threading.Thread(target=self.sendRtp) 
                self.clientInfo['worker'].start()
        
        # Process PAUSE request
        elif requestType == self.PAUSE:
            if self.state == self.PLAYING:
                print("processing PAUSE\n")
                self.state = self.READY
                
                self.clientInfo['event'].set()
            
                self.replyRtsp(self.OK_200, seq[1])
        
        # Process TEARDOWN request
        elif requestType == self.TEARDOWN:
            print("processing TEARDOWN\n")

            self.clientInfo['event'].set()
            
            self.replyRtsp(self.OK_200, seq[1])
            
            # Close the RTP socket
            self.clientInfo['rtpSocket'].close()
    
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

    def sendRtpWithUDP(self):
        """Send RTP packets using UDP"""
        MAX_RTP_PAYLOAD_SIZE = 1400 # MTU - RTP header size
        while True:
            self.clientInfo['event'].wait(0.05) 
            
            # Stop sending if request is PAUSE or TEARDOWN
            if self.clientInfo['event'].isSet(): 
                break 
                
            data = self.clientInfo['videoStream'].nextFrame()
            if data: 
                frameSize = len(data)
                bytesSent = 0
                while bytesSent < frameSize:
                    chunkSize = min(MAX_RTP_PAYLOAD_SIZE, frameSize - bytesSent)
                    chunkData = data[bytesSent:bytesSent + chunkSize]
                    markerBit = (bytesSent + chunkSize) == frameSize
                    try:
                        address = self.clientInfo['rtspSocket'][1][0]
                        port = int(self.clientInfo['rtpPort'])
                        packet = self.makeRtp(chunkData, self.rtpSeq, markerBit)
                        self.clientInfo['rtpSocket'].sendto(packet, (address, port))
                            
                        self.rtpSeq += 1
                        bytesSent += chunkSize
                    except Exception as e:
                        print(f"Sending RTP with UDP error: {e}")
                        break

    def sendRtp(self):
        """Send RTP packets."""
        if self.clientInfo.get('transport', 'UDP') == 'TCP':
            return self.sendRtpWithTCP()
        else:
            return self.sendRtpWithUDP()

    def makeRtp(self, payload, frameNbr, markerBit):
        """RTP-packetize the video data."""
        version = 2
        padding = 0
        extension = 0
        cc = 0
        marker = markerBit
        pt = 26 # MJPEG type
        seqnum = frameNbr
        ssrc = 0 
        
        rtpPacket = RtpPacket()
        
        rtpPacket.encode(version, padding, extension, cc, seqnum, marker, pt, ssrc, payload)
        
        return rtpPacket.getPacket()
        
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
