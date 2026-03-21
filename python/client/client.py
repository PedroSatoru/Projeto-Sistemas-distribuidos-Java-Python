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
        self.socket.setsockopt(zmq.RCVTIMEO, timeout)
        
        # Connect with retry
        self._connect_with_retry()

    def _log(self, level: str, event: str, message: str, ts_ms: int | None = None):
        ts_ms = ts_ms if ts_ms is not None else int(time.time() * 1000)
        print(f"[ts={ts_ms}][PY-CLIENT][{self.username}][{level}] {message}")

    def _connect_with_retry(self, max_retries: int = 5):
        """Connect with exponential backoff retry"""
        for attempt in range(max_retries):
            try:
                endpoint = f"tcp://{self.server_host}:{self.server_port}"
                self.socket.connect(endpoint)
                self._log("INFO", "CONNECT", f"conectado ao broker em {self.server_host}:{self.server_port}")
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
    
    def send_request(self, message: Message) -> Message:
        """Send request and receive response"""
        try:
            payload = message.serialize()
            self._log("INFO", "SEND", f"enviando {message.message_type}", ts_ms=message.timestamp_ms)
            self.socket.send(payload)
            raw_response = self.socket.recv()
            response = Message.deserialize_response(raw_response)
            self._log("INFO", "RECV", f"recebido {response.message_type}", ts_ms=response.timestamp_ms)
            return response
        
        except zmq.Again:
            self._log("ERROR", "TIMEOUT", "sem resposta do servidor")
            return None
        except Exception as e:
            self._log("ERROR", "SEND_RECV", f"erro de comunicacao: {e}")
            return None
    
    def login(self) -> bool:
        """Attempt login to server"""
        self._log("INFO", "LOGIN_START", f"iniciando login para usuario {self.username}")
        
        message = LoginMessage(self.username)
        response = self.send_request(message)
        
        if response is None:
            return False
        
        if response.payload.get("success"):
            self._log("INFO", "LOGIN_OK", "login realizado com sucesso")
            return True
        else:
            error = response.payload.get("error", "Erro desconhecido")
            self._log("ERROR", "LOGIN_FAIL", error)
            return False
    
    def list_channels(self) -> bool:
        """Request channel list from server"""
        self._log("INFO", "LIST_CHANNELS_START", "listando canais")
        
        message = ListChannelsMessage()
        response = self.send_request(message)
        
        if response is None:
            return False
        
        channels = response.payload.get("channels", [])
        if channels:
            self._log("INFO", "LIST_CHANNELS_OK", f"{len(channels)} canal(is): {', '.join(channels)}")
        else:
            self._log("INFO", "LIST_CHANNELS_OK", "nenhum canal disponivel")
        return True
    
    def create_channels(self, channel_names: list) -> bool:
        """Create multiple channels"""
        self._log("INFO", "CREATE_CHANNELS_START", "criando canais")
        
        all_success = True
        for channel_name in channel_names:
            message = CreateChannelMessage(channel_name)
            response = self.send_request(message)
            
            if response is None:
                all_success = False
                continue
            
            if response.payload.get("success"):
                self._log("INFO", "CREATE_CHANNEL_OK", channel_name)
            else:
                error = response.payload.get("error", "Erro desconhecido")
                self._log("ERROR", "CREATE_CHANNEL_FAIL", f"{channel_name}: {error}")
                all_success = False
        
        return all_success
    
    def run_bot(self, channels_to_create: list = None):
        """Run the bot workflow"""
        if channels_to_create is None:
            channels_to_create = ["general", "random", "announcements"]
        
        try:
            self._log("INFO", "BOT_START", "iniciando fluxo do bot")
            
            # Step 1: Login
            if not self.login():
                self._log("ERROR", "BOT_STOP", "login falhou; encerrando")
                return False
            
            time.sleep(0.5)
            
            # Step 2: List channels
            if not self.list_channels():
                self._log("WARN", "LIST_CHANNELS_WARN", "falha ao listar canais; continuando")
            
            time.sleep(0.5)
            
            # Step 3: Create channels
            if not self.create_channels(channels_to_create):
                self._log("WARN", "CREATE_CHANNELS_WARN", "alguns canais falharam")
            
            time.sleep(0.5)
            
            # Step 4: List channels again to verify
            self._log("INFO", "VERIFY", "listando canais novamente")
            self.list_channels()

            self._log("INFO", "BOT_DONE", "bot concluido")
            return True
        
        except KeyboardInterrupt:
            self._log("WARN", "INTERRUPTED", "interrompido pelo usuario")
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
