"""
Chat server implementation using ZeroMQ
Handles login, channel listing, and channel creation
"""

import zmq
import sys
import os
import re
from datetime import datetime

# Add parent directory to path to import schemas
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas import (
    Message,
    MessageType,
    LoginResponseMessage,
    ListChannelsResponseMessage,
    CreateChannelResponseMessage,
    ServerData
)


class ChatServer:
    """ZeroMQ-based chat server"""
    
    def __init__(self, port: int = 5555, data_file: str = "server_data.json", users_file: str = "users.txt"):
        """
        Initialize the server
        
        Args:
            port: Port to listen on
            data_file: Path to JSON file for data persistence
            users_file: Path to file with allowed usernames
        """
        self.port = port
        self.data = ServerData(data_file)
        self.users_file = users_file
        self.allowed_users = self.load_allowed_users()
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REP)
        self.socket.bind(f"tcp://*:{port}")
        self.running = True
        
        print(f"✓ Servidor iniciado na porta {port}")
    
    def load_allowed_users(self) -> set:
        """Load allowed usernames from file"""
        try:
            if os.path.exists(self.users_file):
                with open(self.users_file, 'r') as f:
                    users = {line.strip().lower() for line in f if line.strip()}
                return users
            else:
                print(f"⚠ Arquivo de usuários não encontrado: {self.users_file}")
                return set()
        except Exception as e:
            print(f"✗ Erro ao carregar arquivo de usuários: {e}")
            return set()
    
    def is_valid_name(self, name: str) -> bool:
        """
        Validate name format - alphanumeric, underscore, and hyphen allowed
        """
        if not name or not isinstance(name, str):
            return False
        # Alphanumeric, underscore, and hyphen allowed
        return bool(re.match(r'^[a-zA-Z0-9_-]+$', name.strip()))
    
    def is_user_allowed(self, username: str) -> bool:
        """Check if username is in allowed users list"""
        return username.lower() in self.allowed_users
    
    def handle_login(self, message: Message) -> Message:
        """Handle login request"""
        username = message.payload.get("username", "").strip()
        
        # Validate username format
        if not self.is_valid_name(username):
            error_msg = "Formato de nome de usuário inválido."
            print(f"✗ Login falhou: {username} (formato inválido)")
            return LoginResponseMessage(success=False, error=error_msg)
        
        # Check if user is allowed
        if not self.is_user_allowed(username):
            error_msg = "Usuário não registrado."
            print(f"✗ Login falhou: {username} (não registrado)")
            return LoginResponseMessage(success=False, error=error_msg)
        
        # Check if already logged in
        if self.data.user_exists(username):
            error_msg = "Usuário já conectado."
            print(f"✗ Login falhou: {username} (já conectado)")
            return LoginResponseMessage(success=False, error=error_msg)
        
        # Add user and return success
        self.data.add_user(username)
        print(f"✓ {username} conectado")
        return LoginResponseMessage(success=True)
    
    def handle_list_channels(self, message: Message) -> Message:
        """Handle list channels request"""
        channels = self.data.get_channels()
        print(f"↓ Lista de canais solicitada ({len(channels)} canais)")
        return ListChannelsResponseMessage(channels)
    
    def handle_create_channel(self, message: Message) -> Message:
        """Handle create channel request"""
        channel_name = message.payload.get("channel_name", "").strip()
        
        # Validate channel name
        if not self.is_valid_name(channel_name):
            error_msg = "Formato de nome de canal inválido."
            print(f"✗ Canal não criado: {channel_name} (formato inválido)")
            return CreateChannelResponseMessage(success=False, error=error_msg)
        
        # Check if already exists
        if self.data.channel_exists(channel_name):
            error_msg = "Canal já existe."
            print(f"✗ Canal não criado: {channel_name} (já existe)")
            return CreateChannelResponseMessage(success=False, error=error_msg)
        
        # Create channel
        self.data.add_channel(channel_name)
        print(f"✓ Canal '{channel_name}' criado")
        return CreateChannelResponseMessage(success=True)
    
    def process_message(self, message: Message) -> Message:
        """Process incoming message and return response"""
        msg_type = message.message_type
        
        if msg_type == MessageType.LOGIN:
            return self.handle_login(message)
        elif msg_type == MessageType.LIST_CHANNELS:
            return self.handle_list_channels(message)
        elif msg_type == MessageType.CREATE_CHANNEL:
            return self.handle_create_channel(message)
        else:
            print(f"[ERROR] Unknown message type: {msg_type}")
            return Message(MessageType.LOGIN_RESPONSE, {"success": False, "error": "Unknown message type"})
    
    def run(self):
        """Main server loop"""
        try:
            print("Aguardando conexões...\n")
            while self.running:
                try:
                    # Receive message
                    raw_message = self.socket.recv()
                    message = Message.deserialize(raw_message)
                    
                    # Process and respond
                    response = self.process_message(message)
                    self.socket.send(response.serialize())
                    
                except Exception as e:
                    print(f"✗ Erro ao processar mensagem: {e}")
                    error_response = Message(MessageType.LOGIN_RESPONSE, {"success": False, "error": str(e)})
                    self.socket.send(error_response.serialize())
        
        except KeyboardInterrupt:
            print("\n")
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Graceful shutdown"""
        self.data.save_data()
        self.socket.close()
        self.context.term()
        print("✓ Servidor desligado")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Chat Server")
    parser.add_argument("--port", type=int, default=5555, help="Port to listen on (default: 5555)")
    parser.add_argument("--data-file", type=str, default="server_data.json", help="Data file path (default: server_data.json)")
    parser.add_argument("--users-file", type=str, default="users.txt", help="Users file path (default: users.txt)")
    
    args = parser.parse_args()
    
    server = ChatServer(port=args.port, data_file=args.data_file, users_file=args.users_file)
    server.run()
