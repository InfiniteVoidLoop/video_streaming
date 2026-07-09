import struct

class CustomPacket:
    MAGIC = 0x1234
    HEADER_FORMAT = "!HIIII"
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
    
    @staticmethod
    def encode(frame_num, payload, fragment_index=0, fragment_count=1):
        """
        Encode a frame fragment into a custom packet.
        Header:
        - 2 bytes: Magic number (0x1234)
        - 4 bytes: Frame number
        - 4 bytes: Fragment index
        - 4 bytes: Fragment count
        - 4 bytes: Payload length
        """
        header = struct.pack(
            CustomPacket.HEADER_FORMAT,
            CustomPacket.MAGIC,
            frame_num,
            fragment_index,
            fragment_count,
            len(payload),
        )
        return header + payload
        
    @staticmethod
    def decode(data):
        """
        Decode the custom packet.
        Returns (frame_num, fragment_index, fragment_count, payload) or
        (None, None, None, None) if invalid.
        """
        if len(data) < CustomPacket.HEADER_SIZE:
            return None, None, None, None
        
        header = data[:CustomPacket.HEADER_SIZE]
        magic, frame_num, fragment_index, fragment_count, length = struct.unpack(CustomPacket.HEADER_FORMAT, header)
        
        if magic != CustomPacket.MAGIC:
            return None, None, None, None
        if fragment_count == 0 or fragment_index >= fragment_count:
            return None, None, None, None
             
        payload = data[CustomPacket.HEADER_SIZE:CustomPacket.HEADER_SIZE+length]
        if len(payload) != length:
            return None, None, None, None

        return frame_num, fragment_index, fragment_count, payload
