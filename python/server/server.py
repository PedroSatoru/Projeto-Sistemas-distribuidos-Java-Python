"""
Chat server implementation using ZeroMQ
Handles login, channel listing, and channel creation
"""

import zmq
import sys
import os
import re
import time
from datetime import datetime

# Add parent directory to path to import schemas
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas import (
    Message,
    MessageType,
    LoginResponseMessage,
    ListChannelsResponseMessage,
    CreateChannelResponseMessage,
    PublishResponseMessage,
    ChatMessageBody,
    ServerData
)


class ChatServer:
    """ZeroMQ-based chat server"""
    
    def __init__(self, backend_endpoint: str = "tcp://localhost:5556", pub_endpoint: str = "tcp://localhost:5557", data_file: str = "server_data.json", users_file: str = "users.txt"):
        """
        Initialize the server
        
        Args:
            backend_endpoint: Broker backend endpoint
            pub_endpoint: Proxy XSUB endpoint for publishing
            data_file: Path to JSON file for data persistence
            users_file: Path to file with allowed usernames
        """
        self.backend_endpoint = backend_endpoint
        self.pub_endpoint = pub_endpoint
        self.data = ServerData(data_file)
        self.users_file = users_file
        self.allowed_users = self.load_allowed_users()
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REP)
        self.pub_socket = self.context.socket(zmq.PUB)
        self.running = True
        self.server_id = os.path.basename(data_file)
        
        # Connect with retry
        self._connect_with_retry()

    def _log(self, level: str, event: str, message: str, ts_ms: int | None = None):
        ts_ms = ts_ms if ts_ms is not None else int(time.time() * 1000)
        print(f"[ts={ts_ms}][PY-SERVER][{self.server_id}][{level}] {message}")
    
    def _connect_with_retry(self, max_retries: int = 5):
        """Connect with exponential backoff retry"""
        for attempt in range(max_retries):
            try:
                self.socket.connect(self.backend_endpoint)
                self.pub_socket.connect(self.pub_endpoint)
                self._log("INFO", "CONNECT", f"conectado ao broker backend {self.backend_endpoint} e proxy pub {self.pub_endpoint}")
                return True
            except zmq.error.ZMQError as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1, 2, 4, 8, 16 seconds
                    self._log("WARN", "RETRY", f"tentativa {attempt + 1}/{max_retries} falhou; aguardando {wait_time}s")
                    time.sleep(wait_time)
                else:
                    self._log("ERROR", "CONNECT", f"falha ao conectar apos {max_retries} tentativas: {e}")
                    raise
        return False
    
    def load_allowed_users(self) -> set:
        """Load allowed usernames from file"""
        try:
            if os.path.exists(self.users_file):
                with open(self.users_file, 'r') as f:
                    users = {line.strip().lower() for line in f if line.strip()}
                return users
            else:
                self._log("WARN", "USERS_FILE", f"arquivo de usuarios nao encontrado: {self.users_file}")
                return set()
        except Exception as e:
            self._log("ERROR", "USERS_FILE", f"erro ao carregar arquivo de usuarios: {e}")
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
            self._log("WARN", "LOGIN_FAIL", f"{username} formato invalido", ts_ms=message.timestamp_ms)
            return LoginResponseMessage(success=False, error=error_msg)
        
        # Check if user is allowed
        if not self.is_user_allowed(username):
            error_msg = "Usuário não registrado."
            self._log("WARN", "LOGIN_FAIL", f"{username} nao registrado", ts_ms=message.timestamp_ms)
            return LoginResponseMessage(success=False, error=error_msg)
        
        # Check if already logged in
        if self.data.user_exists(username):
            error_msg = "Usuário já conectado."
            self._log("WARN", "LOGIN_FAIL", f"{username} ja conectado", ts_ms=message.timestamp_ms)
            return LoginResponseMessage(success=False, error=error_msg)
        
        # Add user and return success
        self.data.add_user(username)
        self._log("INFO", "LOGIN_OK", f"{username} conectado", ts_ms=message.timestamp_ms)
        return LoginResponseMessage(success=True)
    
    def handle_list_channels(self, message: Message) -> Message:
        """Handle list channels request"""
        channels = self.data.get_channels()
        self._log("INFO", "LIST_CHANNELS", f"lista solicitada; total={len(channels)}", ts_ms=message.timestamp_ms)
        return ListChannelsResponseMessage(channels)
    
    def handle_create_channel(self, message: Message) -> Message:
        """Handle create channel request"""
        channel_name = message.payload.get("channel_name", "").strip()
        
        # Validate channel name
        if not self.is_valid_name(channel_name):
            error_msg = "Formato de nome de canal inválido."
            self._log("WARN", "CREATE_CHANNEL_FAIL", f"{channel_name} formato invalido", ts_ms=message.timestamp_ms)
            return CreateChannelResponseMessage(success=False, error=error_msg)
        
        # Check if already exists
        if self.data.channel_exists(channel_name):
            error_msg = "Canal já existe."
            self._log("WARN", "CREATE_CHANNEL_FAIL", f"{channel_name} ja existe", ts_ms=message.timestamp_ms)
            return CreateChannelResponseMessage(success=False, error=error_msg)
        
        # Create channel
        self.data.add_channel(channel_name)
        self._log("INFO", "CREATE_CHANNEL_OK", f"canal {channel_name} criado", ts_ms=message.timestamp_ms)
        return CreateChannelResponseMessage(success=True)

    def handle_publish(self, message: Message) -> Message:
        """Handle publish request by verifying and publishing to pub/sub proxy"""
        channel_name = message.payload.get("channel_name", "").strip()
        message_text = message.payload.get("message_text", "")
        
        # We don't have a direct username field in publish request natively without sender identity,
        # but the project requires a REQ. So since zeroMQ REP socket doesn't know sender unless we check frame,
        # we'll use a standard 'user' or pass it if you want. Wait, we won't know the user unless we put it in payload.
        # Enunciado só pediu "canal, mensagem", vamos registrar apenas a msg.
        
        if not self.data.channel_exists(channel_name):
            error_msg = f"Canal não existe: {channel_name}"
            self._log("WARN", "PUBLISH_FAIL", error_msg, ts_ms=message.timestamp_ms)
            return PublishResponseMessage(success=False, error=error_msg)
            
        # Register to data (disk)
        self.data.add_message(channel_name, message_text, message.timestamp_ms)
        
        # Route to PUB
        chat_msg = ChatMessageBody(channel_name, "server", message_text, message.timestamp_ms)
        pub_payload = chat_msg.serialize()
        
        # ZeroMQ PUB envelope format: topic + space + payload or multi-part depending on parser.
        # But here we send multi-part so topic filtering works well.
        self.pub_socket.send_multipart([channel_name.encode('utf-8'), pub_payload])
        self._log("INFO", "PUBLISH_OK", f"mensagem enviada para {channel_name}", ts_ms=message.timestamp_ms)
        
        return PublishResponseMessage(success=True)
    
    def process_message(self, message: Message) -> Message:
        """Process incoming message and return response"""
        msg_type = message.message_type
        
        if msg_type == MessageType.LOGIN:
            return self.handle_login(message)
        elif msg_type == MessageType.LIST_CHANNELS:
            return self.handle_list_channels(message)
        elif msg_type == MessageType.CREATE_CHANNEL:
            return self.handle_create_channel(message)
        elif msg_type == MessageType.PUBLISH_REQUEST:
            return self.handle_publish(message)
        else:
            self._log("ERROR", "UNKNOWN_MSG", f"tipo desconhecido: {msg_type}")
            return Message(MessageType.ERROR_RESPONSE, {"error": "Unknown message type"})
    
    def run(self):
        """Main server loop"""
        try:
            self._log("INFO", "READY", "aguardando conexoes")
            while self.running:
                try:
                    # Receive message
                    raw_message = self.socket.recv()
                    message = Message.deserialize_request(raw_message)
                    self._log("INFO", "RECV", f"recebido {message.message_type}", ts_ms=message.timestamp_ms)
                    
                    # Process and respond
                    response = self.process_message(message)
                    payload = response.serialize()
                    self._log("INFO", "SEND", f"enviado {response.message_type}", ts_ms=response.timestamp_ms)
                    self.socket.send(payload)
                    
                except Exception as e:
                    self._log("ERROR", "PROCESS", f"erro ao processar mensagem: {e}")
                    error_response = Message(MessageType.ERROR_RESPONSE, {"error": str(e)})
                    self.socket.send(error_response.serialize())
        
        except KeyboardInterrupt:
            self._log("WARN", "INTERRUPTED", "interrompido")
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Graceful shutdown"""
        self.data.save_data()
        self.socket.close()
        self.pub_socket.close()
        self.context.term()
        self._log("INFO", "SHUTDOWN", "servidor desligado")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Chat Server")
    parser.add_argument("--backend-endpoint", type=str, default="tcp://localhost:5556", help="Broker backend endpoint (default: tcp://localhost:5556)")
    parser.add_argument("--pub-endpoint", type=str, default="tcp://localhost:5557", help="Proxy Pub endpoint (default: tcp://localhost:5557)")
    parser.add_argument("--data-file", type=str, default="server_data.json", help="Data file path (default: server_data.json)")
    parser.add_argument("--users-file", type=str, default="users.txt", help="Users file path (default: users.txt)")
    
    args = parser.parse_args()
    
    server = ChatServer(backend_endpoint=args.backend_endpoint, pub_endpoint=args.pub_endpoint, data_file=args.data_file, users_file=args.users_file)
    server.run()
