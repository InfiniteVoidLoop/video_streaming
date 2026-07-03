import struct

class CustomPacket:
    MAGIC = 0x1234
    HEADER_FORMAT = "!HII"
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
    
    @staticmethod
    def encode(frame_num, payload):
        """
        Encode the frame into a custom packet.
        Header:
        - 2 bytes: Magic number (0x1234)
        - 4 bytes: Frame number
        - 4 bytes: Payload length
        """
        header = struct.pack(CustomPacket.HEADER_FORMAT, CustomPacket.MAGIC, frame_num, len(payload))
        return header + payload
        
    @staticmethod
    def decode(data):
        """
        Decode the custom packet.
        Returns (frame_num, payload) or (None, None) if invalid.
        """
        if len(data) < CustomPacket.HEADER_SIZE:
            return None, None
        
        header = data[:CustomPacket.HEADER_SIZE]
        magic, frame_num, length = struct.unpack(CustomPacket.HEADER_FORMAT, header)
        
        if magic != CustomPacket.MAGIC:
            return None, None
            
        payload = data[CustomPacket.HEADER_SIZE:CustomPacket.HEADER_SIZE+length]
        return frame_num, payload
