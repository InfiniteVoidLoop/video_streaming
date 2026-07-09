class VideoStream:
	def __init__(self, filename):
		self.filename = filename
		try:
			self.file = open(filename, 'rb')
		except:
			raise IOError
		self.frameNum = 0
		self.lengthPrefixed = self._is_length_prefixed()

	def _is_length_prefixed(self):
		"""Detect the course sample format: 5 ASCII digits before each JPEG."""
		prefix = self.file.read(5)
		self.file.seek(0)
		return len(prefix) == 5 and prefix.isdigit()
		
	def nextFrame(self):
		"""Get next frame."""
		if self.lengthPrefixed:
			data = self.file.read(5) # Get the framelength from the first 5 bytes
			if data:
				framelength = int(data)
				data = self.file.read(framelength)
				self.frameNum += 1
			return data

		return self._next_jpeg_frame()

	def _next_jpeg_frame(self):
		"""Read one JPEG image from a standard concatenated MJPEG file."""
		data = bytearray()
		prev = None

		while True:
			byte = self.file.read(1)
			if not byte:
				return None
			value = byte[0]
			if prev == 0xFF and value == 0xD8:
				data.extend((0xFF, 0xD8))
				break
			prev = value

		prev = None
		while True:
			byte = self.file.read(1)
			if not byte:
				return None
			value = byte[0]
			data.append(value)
			if prev == 0xFF and value == 0xD9:
				self.frameNum += 1
				return bytes(data)
			prev = value
		
	def frameNbr(self):
		"""Get frame number."""
		return self.frameNum
	
	
