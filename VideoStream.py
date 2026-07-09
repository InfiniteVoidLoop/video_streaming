import sys

class VideoStream:
    def __init__(self, filename):
        self.filename = filename
        try:
            self.file = open(filename, 'rb')
        except IOError:
            print(f"Error: Could not open {filename}")
            sys.exit(1)
        self.frameNum = 0
        self.buffer = b''
        
        # Check if the file uses the custom 5-byte header format or is raw MJPEG
        peek = self.file.read(5)
        self.file.seek(0)
        self.use_custom_header = False
        try:
            int(peek)
            self.use_custom_header = True
        except ValueError:
            self.use_custom_header = False

    def nextFrame(self):
        if self.use_custom_header:
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
        else:
            # Raw MJPEG parsing (find SOI and EOI markers)
            while True:
                start = self.buffer.find(b'\xff\xd8')
                if start != -1:
                    end = self.buffer.find(b'\xff\xd9', start + 2)
                    if end != -1:
                        frame = self.buffer[start:end+2]
                        self.buffer = self.buffer[end+2:]
                        self.frameNum += 1
                        return frame
                
                chunk = self.file.read(65536)
                if not chunk:
                    return None
                self.buffer += chunk

    def reset(self):
        self.file.seek(0)
        self.frameNum = 0
        self.buffer = b''
