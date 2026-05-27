import sys, socket
import selectors

from ServerWorker import ServerWorker

class Server:   
    def __init__(self):
        self.serverWorkers = {}
        self.selectors = selectors.DefaultSelector()
    
    def accept_client(self, rtspSocket):
        try: 
            clientSocket, clientAddress = rtspSocket.accept()
            clientSocket.setblocking(False)
            clientInfo = {'rtspSocket': (clientSocket, clientAddress)}

            worker = ServerWorker(clientInfo)
            self.serverWorkers[clientSocket] = worker
            self.selectors.register(clientSocket, selectors.EVENT_READ, self.handle_client_request)
        except Exception as e:
            print(f"Error accepting client: {e}")

    def handle_client_request(self, clientSocket):
        worker = self.serverWorkers.get(clientSocket)
        if worker:
            try:
                worker.recvRtspRequest()
                    
            except Exception as e:
                print(f"Cleaning up disconnected client: {e}")
                try:
                    self.selectors.unregister(clientSocket)
                except:
                    pass
                clientSocket.close()
                if clientSocket in self.serverWorkers:
                    del self.serverWorkers[clientSocket]
                    
    def main(self):
        try:
            SERVER_PORT = int(sys.argv[1])
        except:
            print("[Usage: Server.py Server_port]\n")
        rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        rtspSocket.bind(('', SERVER_PORT))
        rtspSocket.listen(5)        
        rtspSocket.setblocking(False)
        self.selectors.register(rtspSocket, selectors.EVENT_READ, self.accept_client)

        # Receive client info (address,port) through RTSP/TCP session
        while True:
            events = self.selectors.select()
            for key, mask in events:
                callback = key.data
                callback(key.fileobj)

if __name__ == "__main__":
    (Server()).main()


