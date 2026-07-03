import sys
import socket
import time
from CustomPacket import CustomPacket

MULTICAST_GROUP = '239.1.1.1'
MULTICAST_PORT = 5004

class VideoStream:
    def __init__(self, filename):
        self.filename = filename
        try:
            self.file = open(filename, 'rb')
        except IOError:
            print(f"Error: Could not open {filename}")
            sys.exit(1)
        self.frameNum = 0
        
    def nextFrame(self):
        # The first 5 bytes represent the frame length
        data = self.file.read(5)
        if data:
            try:
                framelength = int(data)
                frame = self.file.read(framelength)
                self.frameNum += 1
                return frame
            except ValueError:
                return None
        return None

    def reset(self):
        self.file.seek(0)
        self.frameNum = 0

def main():
    if len(sys.argv) != 2:
        print("Usage: python Server.py <file MJPEG>")
        sys.exit(1)
        
    filename = sys.argv[1]
    
    # Create UDP socket for multicast
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    
    video_stream = VideoStream(filename)
    
    print(f"Starting multicast streaming to {MULTICAST_GROUP}:{MULTICAST_PORT}...")
    
    while True:
        frame = video_stream.nextFrame()
        if frame is None:
            print("Reached end of video. Restarting...")
            video_stream.reset()
            continue
            
        # Packetize the frame using our custom format
        packet = CustomPacket.encode(video_stream.frameNum, frame)
        
        # Send every frame to the multicast IP address
        try:
            sock.sendto(packet, (MULTICAST_GROUP, MULTICAST_PORT))
        except Exception as e:
            print(f"Failed to send packet: {e}")
        
        # Broadcast frames at approximately 20 FPS (50 ms/frame)
        time.sleep(0.05)

if __name__ == "__main__":
    main()
