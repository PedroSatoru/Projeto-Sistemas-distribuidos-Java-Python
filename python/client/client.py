"""
Chat client implementation using ZeroMQ (Bot)
Automatically performs login, lists channels, creates new channels, and publishes.
Part 3: logical clock on all messages.
"""

import zmq
import sys
import os
import time
import threading
import random
import uuid

# Add parent directory to path to import schemas
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas import (
    Message,
    MessageType,
    LoginMessage,
    ListChannelsMessage,
    CreateChannelMessage,
    PublishRequestMessage,
    ChatMessageBody,
    LogicalClock
)


class ChatClient:
    """ZeroMQ-based chat client (Bot)"""
    
    def __init__(self, server_host: str = "localhost", server_port: int = 5555,
                 sub_host: str = "localhost", sub_port: int = 5558,
                 username: str = "bot_user", timeout: int = 5000):
        self.server_host = server_host
        self.server_port = server_port
        self.sub_host = sub_host
        self.sub_port = sub_port
        self.username = username
        self.timeout = timeout
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REQ)
        self.socket.setsockopt(zmq.RCVTIMEO, timeout)
        
        self.sub_socket = self.context.socket(zmq.SUB)
        self.listening = False
        self.subscribed_channels = []

        # Logical clock (Part 3)
        self.lc = LogicalClock()
        
        # Connect with retry
        self._connect_with_retry()

    def _log(self, level: str, event: str, message: str, ts_ms: int | None = None):
        ts_ms = ts_ms if ts_ms is not None else int(time.time() * 1000)
        lc_val = self.lc.value
        print(
            f"[ts={ts_ms}][lc={lc_val}][lang=PY][role=CLIENT][id={self.username}]"
            f"[lvl={level}][evt={event}] {message}",
            flush=True,
        )

    def _connect_with_retry(self, max_retries: int = 5):
        """Connect with exponential backoff retry"""
        for attempt in range(max_retries):
            try:
                endpoint = f"tcp://{self.server_host}:{self.server_port}"
                sub_endpoint = f"tcp://{self.sub_host}:{self.sub_port}"
                self.socket.connect(endpoint)
                self.sub_socket.connect(sub_endpoint)
                self._log("INFO", "CONNECT", f"conectado ao broker em {self.server_host}:{self.server_port} e proxy {self.sub_host}:{self.sub_port}")
                return True
            except zmq.error.ZMQError as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    self._log("WARN", "RETRY", f"tentativa {attempt + 1}/{max_retries} falhou; aguardando {wait_time}s")
                    time.sleep(wait_time)
                else:
                    self._log("ERROR", "CONNECT", f"falha ao conectar apos {max_retries} tentativas: {e}")
                    raise
        return False
    
    def send_request(self, message: Message) -> Message:
        """Send request and receive response (with logical clock)."""
        try:
            # Increment logical clock before sending
            send_lc = self.lc.increment()
            message.logical_clock = send_lc

            payload = message.serialize()
            self._log("INFO", "SEND", f"enviando {message.message_type}", ts_ms=message.timestamp_ms)
            self.socket.send(payload)

            raw_response = self.socket.recv()
            response = Message.deserialize_response(raw_response)

            # Update logical clock on receive
            self.lc.update(response.logical_clock)
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
    
    def get_channels_list(self) -> list:
        """Request channel list from server"""
        self._log("INFO", "LIST_CHANNELS_START", "listando canais")
        
        message = ListChannelsMessage()
        response = self.send_request(message)
        
        if response is None:
            return []
        
        channels = response.payload.get("channels", [])
        if channels:
            self._log("INFO", "LIST_CHANNELS_OK", f"{len(channels)} canal(is): {', '.join(channels)}")
        else:
            self._log("INFO", "LIST_CHANNELS_OK", "nenhum canal disponivel")
        return channels
    
    def _listen_sub(self):
        """Background thread to listen to subscribed channels"""
        while self.listening:
            try:
                parts = self.sub_socket.recv_multipart(flags=zmq.NOBLOCK)
                if len(parts) == 2:
                    channel_name_b, payload = parts
                    try:
                        chat_msg = ChatMessageBody.deserialize_chat_message(payload)
                        recv_ts_ms = int(time.time() * 1000)
                        send_ts_ms = chat_msg.timestamp_ms
                        
                        # Update logical clock from pub/sub message
                        self.lc.update(chat_msg.logical_clock)
                        
                        channel_str = chat_msg.payload.get("channel_name", "")
                        message_txt = chat_msg.payload.get("message_text", "")
                        
                        self._log("INFO", "RECV_SUB",
                                  f"Canal: {channel_str} | Msg: {message_txt} "
                                  f"| TS envio: {send_ts_ms} | TS recv: {recv_ts_ms} "
                                  f"| LC msg: {chat_msg.logical_clock}")
                    except Exception as parse_e:
                        self._log("WARN", "SUB_PARSE_ERR", f"Erro ao decodificar msg PUB: {parse_e}")
            except zmq.Again:
                time.sleep(0.1)
            except Exception as e:
                if self.listening:
                    self._log("ERROR", "SUB_ERR", f"Erro no subscriber: {e}")
                    
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
    
    def run_bot(self):
        """Run the bot workflow as defined in part 2"""
        try:
            self._log("INFO", "BOT_START", "iniciando fluxo do bot")
            
            # Step 1: Login
            if not self.login():
                self._log("ERROR", "BOT_STOP", "login falhou; encerrando")
                return False
            
            time.sleep(0.5)
            
            # Start sub thread
            self.listening = True
            threading.Thread(target=self._listen_sub, daemon=True).start()
            
            # Parte 2: bot constraints
            channels = self.get_channels_list()
            
            # Se existirem menos do que 5 canais, criar um novo
            if len(channels) < 5:
                num_to_create = 5 - len(channels)
                new_channels = [f"bot_ch_{str(uuid.uuid4())[:6]}" for _ in range(num_to_create)]
                self._log("INFO", "BOT_ACTION", f"criando {num_to_create} canais para atingir 5 canais")
                self.create_channels(new_channels)
                time.sleep(0.5)
                channels = self.get_channels_list()
                
            # Se o bot estiver inscrito em menos do que 3 canais, ele deverá se inscrever em mais um
            while len(self.subscribed_channels) < 3 and len(channels) > 0:
                channel_to_sub = random.choice(channels)
                if channel_to_sub not in self.subscribed_channels:
                    self.sub_socket.setsockopt_string(zmq.SUBSCRIBE, channel_to_sub)
                    self.subscribed_channels.append(channel_to_sub)
                    self._log("INFO", "SUB_OK", f"inscrito ao canal {channel_to_sub}")
                    
            # Publicar no maximo 10 mensagens totais
            self._log("INFO", "BOT_LOOP", "iniciando publicacao com limite total de 10 mensagens")
            msg_counter = 0
            max_publishes = 10
            while msg_counter < max_publishes:
                if not channels:
                    time.sleep(1)
                    channels = self.get_channels_list()
                    continue
                
                target_channel = random.choice(channels)
                
                msg_counter += 1
                msg_text = f"Hello pub/sub {msg_counter} from {self.username} [{str(uuid.uuid4())[:4]}]"
                publish_req = PublishRequestMessage(target_channel, msg_text, self.username)
                self.send_request(publish_req)
                time.sleep(1)

            self._log("INFO", "BOT_DONE", "limite de 10 publicacoes totais atingido")
            
            return True
        
        except KeyboardInterrupt:
            self._log("WARN", "INTERRUPTED", "interrompido pelo usuario")
            return False
        finally:
            self.listening = False
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
    parser.add_argument("--sub-host", type=str, default="localhost", help="Proxy sub host (default: localhost)")
    parser.add_argument("--sub-port", type=int, default=5558, help="Server sub proxy port (default: 5558)")
    parser.add_argument("--username", type=str, default="bot_user", help="Username (default: bot_user)")
    parser.add_argument("--timeout", type=int, default=5000, help="Request timeout in ms (default: 5000)")
    
    args = parser.parse_args()
    
    client = ChatClient(
        server_host=args.host,
        server_port=args.port,
        sub_host=args.sub_host,
        sub_port=args.sub_port,
        username=args.username,
        timeout=args.timeout
    )
    client.run_bot()
