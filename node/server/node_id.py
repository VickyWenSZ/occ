import socket
import uuid

NODE_ID = f"{socket.gethostname()}-{str(uuid.uuid4())[:8]}"
