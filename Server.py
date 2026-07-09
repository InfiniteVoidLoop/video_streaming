import sys
import socket
import time
from CustomPacket import CustomPacket

MULTICAST_GROUP = '239.1.1.1'
MULTICAST_PORT = 5004
UDP_MTU = 1400
SOCKET_BUFFER_SIZE = 4 * 1024 * 1024
FRAGMENT_SEND_INTERVAL = 0.005

def get_default_interface_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((MULTICAST_GROUP, MULTICAST_PORT))
        return sock.getsockname()[0]
    finally:
        sock.close()

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
    if len(sys.argv) not in (2, 3):
        print("Usage: python Server.py <file MJPEG> [interface_ip]")
        sys.exit(1)

    filename = sys.argv[1]
    interface_ip = sys.argv[2] if len(sys.argv) == 3 else get_default_interface_ip()
    
    # Create UDP socket for multicast
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SOCKET_BUFFER_SIZE)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(interface_ip))
    
    video_stream = VideoStream(filename)
    
    print(f"Starting multicast streaming to {MULTICAST_GROUP}:{MULTICAST_PORT} via {interface_ip}...")
    
    while True:
        frame = video_stream.nextFrame()
        if frame is None:
            print("Reached end of video. Restarting...")
            video_stream.reset()
            continue
            
        # Split large frames so each UDP datagram stays under the target MTU.
        max_payload_size = UDP_MTU - CustomPacket.HEADER_SIZE
        fragment_count = (len(frame) + max_payload_size - 1) // max_payload_size

        for fragment_index in range(fragment_count):
            start = fragment_index * max_payload_size
            payload = frame[start:start + max_payload_size]
            packet = CustomPacket.encode(video_stream.frameNum, payload, fragment_index, fragment_count)

            try:
                sock.sendto(packet, (MULTICAST_GROUP, MULTICAST_PORT))
            except Exception as e:
                print(f"Failed to send packet: {e}")

            # Avoid dropping large FHD frames by blasting hundreds of UDP packets at once.
            if fragment_count > 1:
                time.sleep(FRAGMENT_SEND_INTERVAL)
        
        # Keep a baseline frame interval; large fragmented frames may run slower due to pacing.
        time.sleep(0.05)

if __name__ == "__main__":
    main()
