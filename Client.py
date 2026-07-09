import socket
import threading
import tkinter as tk
from PIL import Image, ImageTk
import io
import sys
from CustomPacket import CustomPacket

MULTICAST_GROUP = '239.1.1.1'
MULTICAST_PORT = 5004

def get_default_interface_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((MULTICAST_GROUP, MULTICAST_PORT))
        return sock.getsockname()[0]
    finally:
        sock.close()

class Client:
    def __init__(self, master, interface_ip=None):
        self.master = master
        self.master.title("Multicast Video Client")
        self.master.protocol("WM_DELETE_WINDOW", self.handler)
        self.interface_ip = interface_ip or get_default_interface_ip()
        
        # UI Elements
        self.label = tk.Label(self.master, text="Waiting for multicast stream...", bg="black", fg="white", width=60, height=20)
        self.label.pack(padx=10, pady=10)
        
        # Loss detection statistics
        self.stats_label = tk.Label(self.master, text="Packets Received: 0 | Lost: 0 | Loss Rate: 0.00%", font=("Helvetica", 10, "bold"))
        self.stats_label.pack(pady=5)
        
        self.running = True
        self.expected_frame = 0
        self.received_frames = 0
        self.lost_frames = 0
        self.fragment_buffers = {}
        
        self.setup_socket()
        
        self.receive_thread = threading.Thread(target=self.receive_loop)
        self.receive_thread.daemon = True
        self.receive_thread.start()

    def setup_socket(self):
        # Create UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        
        # Allow multiple clients on the same machine to bind to the same port
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, 'SO_REUSEPORT'):
            try:
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
                
        # Bind to the multicast port
        self.sock.bind(('', MULTICAST_PORT))
        
        # Join the multicast group
        mreq = socket.inet_aton(MULTICAST_GROUP) + socket.inet_aton(self.interface_ip)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        print(f"Joined multicast group {MULTICAST_GROUP}:{MULTICAST_PORT} via {self.interface_ip}")
        
    def receive_loop(self):
        while self.running:
            try:
                data, _ = self.sock.recvfrom(2048)
                if not data:
                    continue
                    
                # Decode received packets using our CustomPacket
                frame_num, fragment_index, fragment_count, payload = CustomPacket.decode(data)
                
                if frame_num is not None:
                    self.received_frames += 1

                    buffer = self.fragment_buffers.setdefault(frame_num, {
                        'count': fragment_count,
                        'fragments': {},
                    })

                    if buffer['count'] == fragment_count:
                        buffer['fragments'][fragment_index] = payload

                    if len(buffer['fragments']) == buffer['count']:
                        # Loss detection is frame-based; display only complete frames.
                        if self.expected_frame > 0 and frame_num > self.expected_frame:
                            self.lost_frames += (frame_num - self.expected_frame)

                        self.expected_frame = frame_num + 1
                        frame = b''.join(buffer['fragments'][index] for index in range(buffer['count']))
                        del self.fragment_buffers[frame_num]

                        # Drop stale incomplete frames to avoid unbounded growth.
                        for stale_frame in list(self.fragment_buffers):
                            if stale_frame < self.expected_frame:
                                del self.fragment_buffers[stale_frame]

                        # Schedule display update on the main GUI thread
                        self.master.after(0, self.update_display, frame)
                        self.master.after(0, self.update_stats)
            except Exception as e:
                if self.running:
                    print(f"Error receiving packet: {e}")

    def update_display(self, payload):
        # Display the video in real time
        try:
            image = Image.open(io.BytesIO(payload))
            photo = ImageTk.PhotoImage(image)
            self.label.configure(image=photo, text="", width=photo.width(), height=photo.height())
            self.label.image = photo
        except Exception as e:
            print(f"Error displaying frame: {e}")

    def update_stats(self):
        total = self.received_frames + self.lost_frames
        loss_rate = (self.lost_frames / total * 100) if total > 0 else 0
        self.stats_label.config(text=f"Packets Received: {self.received_frames} | Lost: {self.lost_frames} | Loss Rate: {loss_rate:.2f}%")

    def handler(self):
        """Clean up when exiting."""
        self.running = False
        try:
            # Leave the multicast group when exiting
            mreq = socket.inet_aton(MULTICAST_GROUP) + socket.inet_aton(self.interface_ip)
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
            self.sock.close()
            print("Left multicast group.")
        except Exception as e:
            print(f"Error leaving group: {e}")
            
        self.master.destroy()

if __name__ == "__main__":
    if len(sys.argv) > 2:
        print("Usage: python Client.py [interface_ip]")
        sys.exit(1)

    interface_ip = sys.argv[1] if len(sys.argv) == 2 else None
    root = tk.Tk()
    client = Client(root, interface_ip)
    root.mainloop()
