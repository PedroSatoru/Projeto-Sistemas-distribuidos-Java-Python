"""
Chat server implementation using ZeroMQ
Handles login, channel listing, channel creation, and publishing.
Part 3: logical clock, rank from reference service.
Part 4: Bully election, Berkeley clock sync every 15 msgs, coordinator via PUB/SUB.
"""

import zmq
import sys
import os
import re
import time
import threading

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
    ServerData,
    LogicalClock
)
from schemas.messages import chat_pb2


class ChatServer:
    """ZeroMQ-based chat server"""
    
    def __init__(
        self,
        backend_endpoint: str = "tcp://localhost:5556",
        pub_endpoint: str = "tcp://localhost:5557",
        sub_endpoint: str = "tcp://localhost:5558",
        reference_endpoint: str = "tcp://localhost:5559",
        data_file: str = "server_data.json",
        users_file: str = "users.txt",
        server_name: str | None = None,
        election_port: int = 6001,
    ):
        self.backend_endpoint = backend_endpoint
        self.pub_endpoint = pub_endpoint
        self.sub_endpoint = sub_endpoint
        self.reference_endpoint = reference_endpoint
        self.data = ServerData(data_file)
        self.users_file = users_file
        self.allowed_users = self.load_allowed_users()
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REP)
        self.pub_socket = self.context.socket(zmq.PUB)
        self.running = True

        # Server identity
        self.server_name = server_name or os.path.basename(data_file)
        self.server_id = self.server_name

        # Logical clock (Part 3)
        self.lc = LogicalClock()

        # Physical clock offset — adjusted via coordinator (Part 4)
        self.time_offset_ms: int = 0

        # Client message counter for clock sync (every 15 messages - Part 4)
        self._client_msg_count = 0

        # Rank from reference service
        self.rank: int = 0

        # Part 4: Election port and endpoint
        self.election_port = election_port
        self.election_endpoint = f"tcp://{self.server_name}:{election_port}"

        # Part 4: Coordinator tracking
        self.coordinator_name: str | None = None
        self._coordinator_lock = threading.Lock()
        
        # Connect with retry
        self._connect_with_retry()

        # Reference service socket (REQ pattern on a separate socket)
        self.ref_socket = self.context.socket(zmq.REQ)
        self.ref_socket.setsockopt(zmq.RCVTIMEO, 5000)
        self.ref_socket.connect(self.reference_endpoint)

        # Request rank from reference service
        self._request_rank()

        # Part 4: Election REP socket (bind)
        self.election_socket = self.context.socket(zmq.REP)
        self.election_socket.bind(f"tcp://*:{self.election_port}")
        self._log("INFO", "ELECTION_BIND", f"election socket em porta {self.election_port}")

        # Part 4: SUB socket for coordinator announcements on "servers" topic
        self.servers_sub_socket = self.context.socket(zmq.SUB)
        self.servers_sub_socket.connect(self.sub_endpoint)
        self.servers_sub_socket.setsockopt_string(zmq.SUBSCRIBE, "servers")
        self._log("INFO", "SUB_SERVERS", f"inscrito no topico 'servers' via {self.sub_endpoint}")

        # Start coordinator announcement listener thread
        self._coordinator_thread = threading.Thread(target=self._coordinator_listener, daemon=True)
        self._coordinator_thread.start()

        # Part 4: Initial election after short delay
        threading.Timer(5.0, self._start_election).start()

    def _adjusted_time_ms(self) -> int:
        """Return current time in ms adjusted by the physical clock offset."""
        return int(time.time() * 1000) + self.time_offset_ms

    def _log(self, level: str, event: str, message: str, ts_ms: int | None = None):
        ts_ms = ts_ms if ts_ms is not None else self._adjusted_time_ms()
        lc_val = self.lc.value
        coord = self.coordinator_name or "NONE"
        print(
            f"[ts={ts_ms}][lc={lc_val}][lang=PY][role=SERVER][id={self.server_id}]"
            f"[rank={self.rank}][coord={coord}][lvl={level}][evt={event}] {message}",
            flush=True,
        )
    
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
                    wait_time = 2 ** attempt
                    self._log("WARN", "RETRY", f"tentativa {attempt + 1}/{max_retries} falhou; aguardando {wait_time}s")
                    time.sleep(wait_time)
                else:
                    self._log("ERROR", "CONNECT", f"falha ao conectar apos {max_retries} tentativas: {e}")
                    raise
        return False

    # ------------------------------------------------------------------
    # Reference service interaction
    # ------------------------------------------------------------------

    def _request_rank(self):
        """Request rank from reference service on startup."""
        try:
            req = chat_pb2.ReferenceRequest(
                timestamp_ms=self._adjusted_time_ms(),
                action="rank",
                server_name=self.server_name,
                election_endpoint=self.election_endpoint,
            )
            self.ref_socket.send(req.SerializeToString())
            raw = self.ref_socket.recv()
            resp = chat_pb2.ReferenceResponse()
            resp.ParseFromString(raw)
            self.rank = resp.rank
            # Sync physical clock on first contact
            if resp.reference_time_ms:
                local_now = int(time.time() * 1000)
                self.time_offset_ms = resp.reference_time_ms - local_now
            self._log("INFO", "RANK_OK", f"rank recebido: {self.rank}, offset={self.time_offset_ms}ms")
        except Exception as e:
            self._log("ERROR", "RANK_FAIL", f"falha ao obter rank: {e}")

    def _send_heartbeat(self):
        """Send heartbeat to reference service. Part 4: no clock sync here."""
        try:
            req = chat_pb2.ReferenceRequest(
                timestamp_ms=self._adjusted_time_ms(),
                action="heartbeat",
                server_name=self.server_name,
                election_endpoint=self.election_endpoint,
            )
            self.ref_socket.send(req.SerializeToString())
            raw = self.ref_socket.recv()
            resp = chat_pb2.ReferenceResponse()
            resp.ParseFromString(raw)
            self._log("INFO", "HEARTBEAT_OK", f"heartbeat enviado, status={resp.status}")
        except Exception as e:
            self._log("ERROR", "HEARTBEAT_FAIL", f"falha no heartbeat: {e}")
    
    # ------------------------------------------------------------------
    # User file
    # ------------------------------------------------------------------

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
        if not name or not isinstance(name, str):
            return False
        return bool(re.match(r'^[a-zA-Z0-9_-]+$', name.strip()))
    
    def is_user_allowed(self, username: str) -> bool:
        return username.lower() in self.allowed_users

    # ------------------------------------------------------------------
    # Request handlers
    # ------------------------------------------------------------------
    
    def handle_login(self, message: Message) -> Message:
        username = message.payload.get("username", "").strip()
        
        if not self.is_valid_name(username):
            error_msg = "Formato de nome de usuário inválido."
            self._log("WARN", "LOGIN_FAIL", f"{username} formato invalido", ts_ms=message.timestamp_ms)
            return LoginResponseMessage(success=False, error=error_msg)
        
        if not self.is_user_allowed(username):
            error_msg = "Usuário não registrado."
            self._log("WARN", "LOGIN_FAIL", f"{username} nao registrado", ts_ms=message.timestamp_ms)
            return LoginResponseMessage(success=False, error=error_msg)
        
        if self.data.user_exists(username):
            error_msg = "Usuário já conectado."
            self._log("WARN", "LOGIN_FAIL", f"{username} ja conectado", ts_ms=message.timestamp_ms)
            return LoginResponseMessage(success=False, error=error_msg)
        
        self.data.add_user(username)
        self._log("INFO", "LOGIN_OK", f"{username} conectado", ts_ms=message.timestamp_ms)
        return LoginResponseMessage(success=True)
    
    def handle_list_channels(self, message: Message) -> Message:
        channels = self.data.get_channels()
        self._log("INFO", "LIST_CHANNELS", f"lista solicitada; total={len(channels)}", ts_ms=message.timestamp_ms)
        return ListChannelsResponseMessage(channels)
    
    def handle_create_channel(self, message: Message) -> Message:
        channel_name = message.payload.get("channel_name", "").strip()
        
        if not self.is_valid_name(channel_name):
            error_msg = "Formato de nome de canal inválido."
            self._log("WARN", "CREATE_CHANNEL_FAIL", f"{channel_name} formato invalido", ts_ms=message.timestamp_ms)
            return CreateChannelResponseMessage(success=False, error=error_msg)
        
        if self.data.channel_exists(channel_name):
            error_msg = "Canal já existe."
            self._log("WARN", "CREATE_CHANNEL_FAIL", f"{channel_name} ja existe", ts_ms=message.timestamp_ms)
            return CreateChannelResponseMessage(success=False, error=error_msg)
        
        self.data.add_channel(channel_name)
        self._log("INFO", "CREATE_CHANNEL_OK", f"canal {channel_name} criado", ts_ms=message.timestamp_ms)
        return CreateChannelResponseMessage(success=True)

    def handle_publish(self, message: Message) -> Message:
        channel_name = message.payload.get("channel_name", "").strip()
        message_text = message.payload.get("message_text", "")
        username = message.payload.get("username", "").strip() or "server"
        
        if not self.data.channel_exists(channel_name):
            error_msg = f"Canal não existe: {channel_name}"
            self._log("WARN", "PUBLISH_FAIL", error_msg, ts_ms=message.timestamp_ms)
            return PublishResponseMessage(success=False, error=error_msg)
            
        self.data.add_message(channel_name, message_text, message.timestamp_ms)
        
        # Increment logical clock for the pub/sub publish
        pub_lc = self.lc.increment()
        chat_msg = ChatMessageBody(
            channel_name, username, message_text,
            timestamp_ms=self._adjusted_time_ms(),
            logical_clock=pub_lc,
        )
        pub_payload = chat_msg.serialize()
        
        self.pub_socket.send_multipart([channel_name.encode('utf-8'), pub_payload])
        self._log("INFO", "PUBLISH_OK", f"mensagem enviada para {channel_name}", ts_ms=message.timestamp_ms)
        
        return PublishResponseMessage(success=True)
    
    def process_message(self, message: Message) -> Message:
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
    # ------------------------------------------------------------------
    # Part 4: Bully Election + Berkeley Clock Sync
    # ------------------------------------------------------------------

    def _get_server_list(self) -> list:
        """Get list of servers from reference service."""
        try:
            req = chat_pb2.ReferenceRequest(
                timestamp_ms=self._adjusted_time_ms(),
                action="list",
                server_name=self.server_name,
            )
            self.ref_socket.send(req.SerializeToString())
            raw = self.ref_socket.recv()
            resp = chat_pb2.ReferenceResponse()
            resp.ParseFromString(raw)
            return [
                {"name": s.name, "rank": s.rank, "election_endpoint": s.election_endpoint}
                for s in resp.servers
            ]
        except Exception as e:
            self._log("ERROR", "LIST_FAIL", f"falha ao obter lista: {e}")
            return []

    def _coordinator_listener(self):
        """Thread that listens for coordinator announcements on 'servers' topic."""
        poller = zmq.Poller()
        poller.register(self.servers_sub_socket, zmq.POLLIN)
        while self.running:
            try:
                socks = dict(poller.poll(1000))
                if self.servers_sub_socket in socks:
                    parts = self.servers_sub_socket.recv_multipart()
                    if len(parts) == 2:
                        payload = parts[1]
                        ann = chat_pb2.CoordinatorAnnouncement()
                        ann.ParseFromString(payload)
                        with self._coordinator_lock:
                            self.coordinator_name = ann.coordinator_name
                        self._log("INFO", "COORDINATOR_UPDATE", f"novo coordenador: {ann.coordinator_name}")
            except Exception as e:
                if self.running:
                    self._log("ERROR", "COORD_LISTENER_ERR", str(e))

    def _start_election(self):
        """Bully election: contact servers with higher rank."""
        self._log("INFO", "ELECTION_START", f"iniciando eleicao (meu rank={self.rank})")
        servers = self._get_server_list()
        higher_servers = [s for s in servers if s["rank"] > self.rank and s["name"] != self.server_name]

        if not higher_servers:
            self._declare_coordinator()
            return

        got_ok = False
        for server in higher_servers:
            ep = server["election_endpoint"]
            if not ep:
                continue
            try:
                sock = self.context.socket(zmq.REQ)
                sock.setsockopt(zmq.RCVTIMEO, 3000)
                sock.setsockopt(zmq.LINGER, 0)
                sock.connect(ep)
                req = chat_pb2.ElectionRequest(
                    timestamp_ms=self._adjusted_time_ms(),
                    server_name=self.server_name,
                    rank=self.rank,
                )
                sock.send(req.SerializeToString())
                raw = sock.recv()
                resp = chat_pb2.ElectionResponse()
                resp.ParseFromString(raw)
                if resp.ok:
                    self._log("INFO", "ELECTION_OK_RECV", f"{server['name']} respondeu OK")
                    got_ok = True
                sock.close()
            except Exception:
                self._log("WARN", "ELECTION_NO_RESP", f"{server['name']} nao respondeu")
                try:
                    sock.close()
                except Exception:
                    pass

        if not got_ok:
            self._declare_coordinator()
        else:
            self._log("INFO", "ELECTION_WAIT", "aguardando anuncio de coordenador")

    def _declare_coordinator(self):
        """Announce self as coordinator via PUB on 'servers' topic."""
        with self._coordinator_lock:
            self.coordinator_name = self.server_name
        self._log("INFO", "COORDINATOR_SELF", f"EU sou o coordenador (rank={self.rank})")
        ann = chat_pb2.CoordinatorAnnouncement(
            timestamp_ms=self._adjusted_time_ms(),
            coordinator_name=self.server_name,
        )
        self.pub_socket.send_multipart([b"servers", ann.SerializeToString()])
        self._log("INFO", "COORDINATOR_PUB", "anuncio publicado no topico 'servers'")

    def _sync_clock_with_coordinator(self):
        """Request correct time from coordinator (Berkeley algorithm)."""
        with self._coordinator_lock:
            coord = self.coordinator_name

        if not coord:
            self._log("WARN", "CLOCK_SYNC_SKIP", "sem coordenador definido")
            self._start_election()
            return

        if coord == self.server_name:
            self._log("INFO", "CLOCK_SYNC_SELF", "eu sou o coordenador, sem necessidade de sync")
            return

        servers = self._get_server_list()
        coord_ep = None
        for s in servers:
            if s["name"] == coord:
                coord_ep = s["election_endpoint"]
                break

        if not coord_ep:
            self._log("WARN", "CLOCK_SYNC_NO_EP", f"endpoint do coordenador {coord} nao encontrado")
            self._start_election()
            return

        try:
            sock = self.context.socket(zmq.REQ)
            sock.setsockopt(zmq.RCVTIMEO, 3000)
            sock.setsockopt(zmq.LINGER, 0)
            sock.connect(coord_ep)
            req = chat_pb2.ClockSyncRequest(
                timestamp_ms=self._adjusted_time_ms(),
                server_name=self.server_name,
                local_time_ms=self._adjusted_time_ms(),
            )
            sock.send(req.SerializeToString())
            raw = sock.recv()
            resp = chat_pb2.ClockSyncResponse()
            resp.ParseFromString(raw)
            if resp.correct_time_ms > 0:
                local_now = int(time.time() * 1000)
                self.time_offset_ms = resp.correct_time_ms - local_now
                self._log("INFO", "CLOCK_SYNC_OK", f"relogio sincronizado com {coord}, offset={self.time_offset_ms}ms")
            sock.close()
        except Exception as e:
            self._log("WARN", "CLOCK_SYNC_FAIL", f"coordenador {coord} nao respondeu: {e}")
            try:
                sock.close()
            except Exception:
                pass
            self._start_election()

    def _handle_election_or_clock_on_election_socket(self, raw: bytes):
        """Handle incoming message on the election socket (election or clock sync)."""
        # Try ClockSyncRequest first (local_time_ms is a real timestamp > 1 trillion)
        try:
            csreq = chat_pb2.ClockSyncRequest()
            csreq.ParseFromString(raw)
            if csreq.server_name and csreq.local_time_ms > 1_000_000_000_000:
                resp = chat_pb2.ClockSyncResponse(
                    timestamp_ms=self._adjusted_time_ms(),
                    correct_time_ms=self._adjusted_time_ms(),
                )
                self.election_socket.send(resp.SerializeToString())
                self._log("INFO", "CLOCK_SYNC_RESP", f"hora enviada para {csreq.server_name}")
                return
        except Exception:
            pass

        # Otherwise handle as election request
        try:
            req = chat_pb2.ElectionRequest()
            req.ParseFromString(raw)
            self._log("INFO", "ELECTION_RECV", f"pedido de eleicao de {req.server_name} (rank={req.rank})")
            resp = chat_pb2.ElectionResponse(
                timestamp_ms=self._adjusted_time_ms(),
                server_name=self.server_name,
                ok=True,
            )
            self.election_socket.send(resp.SerializeToString())
            if self.rank > req.rank:
                threading.Thread(target=self._start_election, daemon=True).start()
        except Exception as e:
            self._log("ERROR", "ELECTION_PARSE_ERR", str(e))
            try:
                resp = chat_pb2.ElectionResponse(
                    timestamp_ms=self._adjusted_time_ms(),
                    server_name=self.server_name,
                    ok=True,
                )
                self.election_socket.send(resp.SerializeToString())
            except Exception:
                pass

    def run(self):
        """Main server loop"""
        try:
            self._log("INFO", "READY", "aguardando conexoes")

            poller = zmq.Poller()
            poller.register(self.socket, zmq.POLLIN)
            poller.register(self.election_socket, zmq.POLLIN)

            while self.running:
                try:
                    socks = dict(poller.poll(1000))

                    # Handle election/clock sync requests
                    if self.election_socket in socks:
                        raw = self.election_socket.recv()
                        self._handle_election_or_clock_on_election_socket(raw)

                    # Handle client requests
                    if self.socket in socks:
                        raw_message = self.socket.recv()
                        message = Message.deserialize_request(raw_message)

                        # Update logical clock on receive
                        self.lc.update(message.logical_clock)
                        self._log("INFO", "RECV", f"recebido {message.message_type}", ts_ms=message.timestamp_ms)

                        # Process and respond
                        response = self.process_message(message)

                        # Increment logical clock before send
                        send_lc = self.lc.increment()
                        response.logical_clock = send_lc
                        response.timestamp_ms = self._adjusted_time_ms()

                        payload = response.serialize()
                        self._log("INFO", "SEND", f"enviado {response.message_type}", ts_ms=response.timestamp_ms)
                        self.socket.send(payload)

                        # Part 4: Count client messages (every 15 -> heartbeat + clock sync)
                        self._client_msg_count += 1
                        if self._client_msg_count >= 15:
                            self._client_msg_count = 0
                            self._send_heartbeat()
                            self._sync_clock_with_coordinator()

                except Exception as e:
                    self._log("ERROR", "PROCESS", f"erro ao processar mensagem: {e}")
                    try:
                        error_response = Message(MessageType.ERROR_RESPONSE, {"error": str(e)})
                        error_response.logical_clock = self.lc.increment()
                        self.socket.send(error_response.serialize())
                    except Exception:
                        pass

        except KeyboardInterrupt:
            self._log("WARN", "INTERRUPTED", "interrompido")
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Graceful shutdown"""
        self.running = False
        self.data.save_data()
        self.socket.close()
        self.pub_socket.close()
        self.ref_socket.close()
        self.election_socket.close()
        self.servers_sub_socket.close()
        self.context.term()
        self._log("INFO", "SHUTDOWN", "servidor desligado")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Chat Server")
    parser.add_argument("--backend-endpoint", type=str, default="tcp://localhost:5556",
                        help="Broker backend endpoint (default: tcp://localhost:5556)")
    parser.add_argument("--pub-endpoint", type=str, default="tcp://localhost:5557",
                        help="Proxy Pub endpoint (default: tcp://localhost:5557)")
    parser.add_argument("--sub-endpoint", type=str, default="tcp://localhost:5558",
                        help="Proxy Sub endpoint (default: tcp://localhost:5558)")
    parser.add_argument("--reference-endpoint", type=str, default="tcp://localhost:5559",
                        help="Reference service endpoint (default: tcp://localhost:5559)")
    parser.add_argument("--data-file", type=str, default="server_data.json",
                        help="Data file path (default: server_data.json)")
    parser.add_argument("--users-file", type=str, default="users.txt",
                        help="Users file path (default: users.txt)")
    parser.add_argument("--server-name", type=str, default=None,
                        help="Server name for reference service (default: data-file basename)")
    parser.add_argument("--election-port", type=int, default=6001,
                        help="Port for election REP socket (default: 6001)")
    
    args = parser.parse_args()
    
    server = ChatServer(
        backend_endpoint=args.backend_endpoint,
        pub_endpoint=args.pub_endpoint,
        sub_endpoint=args.sub_endpoint,
        reference_endpoint=args.reference_endpoint,
        data_file=args.data_file,
        users_file=args.users_file,
        server_name=args.server_name,
        election_port=args.election_port,
    )
    server.run()
