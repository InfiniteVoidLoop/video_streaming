import sys
from tkinter import Tk
from Client import Client
from Config import DEFAULT_MEDIA_FILE

if __name__ == "__main__":
    try:
        serverAddr = sys.argv[1]
        serverPort = sys.argv[2]
        fileName = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_MEDIA_FILE
    except:
        print("[Usage: ClientLauncher.py Server_name Server_port [Server_media_file]]\n")
        sys.exit(1)
    
    root = Tk()
    
    # Create a new client
    app = Client(root, serverAddr, serverPort, fileName)
    app.master.title("RTPClient")   
    root.mainloop()
    
