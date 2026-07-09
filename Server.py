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
        self.lengthPrefixed = self._is_length_prefixed()

    def _is_length_prefixed(self):
        """Detect the original sample format: 5 ASCII digits before each frame."""
        prefix = self.file.read(5)
        self.file.seek(0)
        return len(prefix) == 5 and prefix.isdigit()
        
    def nextFrame(self):
        if not self.lengthPrefixed:
            return self._next_jpeg_frame()

        data = self.file.read(5)
        if not data:
            return None

        framelength = int(data)
        frame = self.file.read(framelength)
        if len(frame) != framelength:
            return None

        self.frameNum += 1
        return frame

    def _next_jpeg_frame(self):
        """Read one JPEG image from a standard concatenated MJPEG stream."""
        frame = bytearray()
        prev = None

        while True:
            byte = self.file.read(1)
            if not byte:
                return None

            value = byte[0]
            if prev == 0xFF and value == 0xD8:
                frame.extend((0xFF, 0xD8))
                break
            prev = value

        prev = None
        while True:
            byte = self.file.read(1)
            if not byte:
                return None

            value = byte[0]
            frame.append(value)
            if prev == 0xFF and value == 0xD9:
                self.frameNum += 1
                return bytes(frame)
            prev = value

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
