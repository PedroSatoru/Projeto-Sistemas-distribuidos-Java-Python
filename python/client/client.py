"""
Chat client implementation using ZeroMQ (Bot)
Automatically performs login, lists channels, and creates new channels
"""

import zmq
import sys
import os
import time
from datetime import datetime

# Add parent directory to path to import schemas
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas import (
    Message,
    MessageType,
    LoginMessage,
    ListChannelsMessage,
    CreateChannelMessage
)


class ChatClient:
    """ZeroMQ-based chat client (Bot)"""
    
    def __init__(self, server_host: str = "localhost", server_port: int = 5555, username: str = "bot_user", timeout: int = 5000):
        """
        Initialize the client
        
        Args:
            server_host: Server hostname
            server_port: Server port
            username: Username for this bot
            timeout: Request timeout in milliseconds
        """
        self.server_host = server_host
        self.server_port = server_port
        self.username = username
        self.timeout = timeout
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REQ)
        self.socket.connect(f"tcp://{server_host}:{server_port}")
        self.socket.setsockopt(zmq.RCVTIMEO, timeout)
        
        print(f"✓ Cliente conectado ao servidor ({server_host}:{server_port})")
    
    def send_request(self, message: Message) -> Message:
        """Send request and receive response"""
        try:
            self.socket.send(message.serialize())
            raw_response = self.socket.recv()
            response = Message.deserialize(raw_response)
            return response
        
        except zmq.Again:
            print("✗ Timeout - sem resposta do servidor")
            return None
        except Exception as e:
            print(f"✗ Erro na comunicação: {e}")
            return None
    
    def login(self) -> bool:
        """Attempt login to server"""
        print(f"\n[1/3] Login com usuário '{self.username}'")
        
        message = LoginMessage(self.username)
        response = self.send_request(message)
        
        if response is None:
            return False
        
        if response.payload.get("success"):
            print(f"      ✓ Login realizado com sucesso")
            return True
        else:
            error = response.payload.get("error", "Erro desconhecido")
            print(f"      ✗ {error}")
            return False
    
    def list_channels(self) -> bool:
        """Request channel list from server"""
        print(f"\n[2/3] Listando canais")
        
        message = ListChannelsMessage()
        response = self.send_request(message)
        
        if response is None:
            return False
        
        channels = response.payload.get("channels", [])
        if channels:
            print(f"      ✓ {len(channels)} canal(is): {', '.join(channels)}")
        else:
            print(f"      ✓ Nenhum canal disponível")
        return True
    
    def create_channels(self, channel_names: list) -> bool:
        """Create multiple channels"""
        print(f"\n[3/3] Criando canais")
        
        all_success = True
        for channel_name in channel_names:
            message = CreateChannelMessage(channel_name)
            response = self.send_request(message)
            
            if response is None:
                all_success = False
                continue
            
            if response.payload.get("success"):
                print(f"      ✓ '{channel_name}'")
            else:
                error = response.payload.get("error", "Erro desconhecido")
                print(f"      ✗ '{channel_name}': {error}")
                all_success = False
        
        return all_success
    
    def run_bot(self, channels_to_create: list = None):
        """Run the bot workflow"""
        if channels_to_create is None:
            channels_to_create = ["general", "random", "announcements"]
        
        try:
            print(f"{'#'*50}")
            print(f"  BOT - {self.username}")
            print(f"{'#'*50}")
            
            # Step 1: Login
            if not self.login():
                print("\n✗ Login falhou. Encerrando.")
                return False
            
            time.sleep(0.5)
            
            # Step 2: List channels
            if not self.list_channels():
                print("(continuando...)")
            
            time.sleep(0.5)
            
            # Step 3: Create channels
            if not self.create_channels(channels_to_create):
                print("(alguns canais falharam)")
            
            time.sleep(0.5)
            
            # Step 4: List channels again to verify
            print(f"\n[Verificação] Listando canais novamente")
            self.list_channels()
            
            print(f"\n{'#'*50}")
            print(f"  ✓ BOT CONCLUÍDO")
            print(f"{'#'*50}\n")
            return True
        
        except KeyboardInterrupt:
            print("\n✗ Interrompido pelo usuário")
            return False
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Graceful shutdown"""
        self.socket.close()
        self.context.term()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Chat Client Bot")
    parser.add_argument("--host", type=str, default="localhost", help="Server host (default: localhost)")
    parser.add_argument("--port", type=int, default=5555, help="Server port (default: 5555)")
    parser.add_argument("--username", type=str, default="bot_user", help="Username (default: bot_user)")
    parser.add_argument("--channels", type=str, default="general,random,announcements", help="Channels to create (comma-separated)")
    parser.add_argument("--timeout", type=int, default=5000, help="Request timeout in ms (default: 5000)")
    
    args = parser.parse_args()
    channels = [c.strip() for c in args.channels.split(",")]
    
    client = ChatClient(
        server_host=args.host,
        server_port=args.port,
        username=args.username,
        timeout=args.timeout
    )
    client.run_bot(channels_to_create=channels)
