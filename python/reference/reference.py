"""
Reference Service for server registry and heartbeat.

Responsibilities:
  1. Assign a unique rank to each server on first contact.
  2. Maintain the list of registered servers (no duplicate names).
  3. Return the list of available servers with ranks and election endpoints.
  4. Accept heartbeats from servers and remove stale ones.
  Part 4: No longer returns reference time in heartbeat (clock sync is via coordinator).
"""

import argparse
import time
import threading
import sys
import os

# Add parent directory to path to import schemas
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import zmq
from schemas.messages import chat_pb2


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
HEARTBEAT_TIMEOUT_S = 60   # remove server after this many seconds without heartbeat
CLEANUP_INTERVAL_S = 30    # how often the cleanup thread runs


def _now_ms() -> int:
    return int(time.time() * 1000)


def _log(level: str, event: str, message: str):
    ts = _now_ms()
    print(
        f"[ts={ts}][lang=PY][role=REFERENCE][id=reference]"
        f"[lvl={level}][evt={event}] {message}",
        flush=True,
    )


class ReferenceService:
    """ZeroMQ REP service for server rank / heartbeat / clock sync."""

    def __init__(self, endpoint: str = "tcp://*:5559"):
        self.endpoint = endpoint
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REP)
        self.socket.bind(endpoint)

        # Server registry: name -> {"rank": int, "last_heartbeat": float}
        self._servers: dict[str, dict] = {}
        self._next_rank = 1
        self._lock = threading.Lock()

        # Start background cleanup thread
        self._running = True
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

        _log("INFO", "BIND", f"servico de referencia ouvindo em {endpoint}")

    # ------------------------------------------------------------------
    # Request handlers
    # ------------------------------------------------------------------

    def _handle_rank(self, server_name: str, election_endpoint: str = "") -> chat_pb2.ReferenceResponse:
        """Register server and return its rank."""
        with self._lock:
            if server_name in self._servers:
                rank = self._servers[server_name]["rank"]
                self._servers[server_name]["last_heartbeat"] = time.time()
                if election_endpoint:
                    self._servers[server_name]["election_endpoint"] = election_endpoint
                _log("INFO", "RANK_EXISTING", f"{server_name} -> rank={rank} (ja registrado)")
            else:
                rank = self._next_rank
                self._next_rank += 1
                self._servers[server_name] = {
                    "rank": rank,
                    "last_heartbeat": time.time(),
                    "election_endpoint": election_endpoint,
                }
                _log("INFO", "RANK_NEW", f"{server_name} -> rank={rank}, election={election_endpoint}")

        return chat_pb2.ReferenceResponse(
            timestamp_ms=_now_ms(),
            action="rank",
            rank=rank,
            reference_time_ms=_now_ms(),
        )

    def _handle_list(self) -> chat_pb2.ReferenceResponse:
        """Return list of available servers with election endpoints."""
        with self._lock:
            infos = [
                chat_pb2.ServerInfo(
                    name=name,
                    rank=data["rank"],
                    election_endpoint=data.get("election_endpoint", ""),
                )
                for name, data in self._servers.items()
            ]
        _log("INFO", "LIST", f"retornando {len(infos)} servidor(es)")
        return chat_pb2.ReferenceResponse(
            timestamp_ms=_now_ms(),
            action="list",
            servers=infos,
        )

    def _handle_heartbeat(self, server_name: str, election_endpoint: str = "") -> chat_pb2.ReferenceResponse:
        """Update heartbeat timestamp. Part 4: no longer returns reference time."""
        with self._lock:
            if server_name in self._servers:
                self._servers[server_name]["last_heartbeat"] = time.time()
                if election_endpoint:
                    self._servers[server_name]["election_endpoint"] = election_endpoint
                _log("INFO", "HEARTBEAT", f"{server_name} heartbeat recebido")
            else:
                # Server not registered yet – register it on the fly
                rank = self._next_rank
                self._next_rank += 1
                self._servers[server_name] = {
                    "rank": rank,
                    "last_heartbeat": time.time(),
                    "election_endpoint": election_endpoint,
                }
                _log("WARN", "HEARTBEAT_NEW", f"{server_name} registrado via heartbeat, rank={rank}")

        return chat_pb2.ReferenceResponse(
            timestamp_ms=_now_ms(),
            action="heartbeat",
            status="OK",
            # Part 4: reference_time_ms removed – clock sync is now via coordinator
        )

    # ------------------------------------------------------------------
    # Background cleanup
    # ------------------------------------------------------------------

    def _cleanup_loop(self):
        while self._running:
            time.sleep(CLEANUP_INTERVAL_S)
            now = time.time()
            with self._lock:
                stale = [
                    name for name, data in self._servers.items()
                    if now - data["last_heartbeat"] > HEARTBEAT_TIMEOUT_S
                ]
                for name in stale:
                    del self._servers[name]
                    _log("WARN", "STALE_REMOVE", f"{name} removido por inatividade")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self):
        _log("INFO", "READY", "aguardando requisicoes de servidores")
        try:
            while True:
                raw = self.socket.recv()
                req = chat_pb2.ReferenceRequest()
                req.ParseFromString(raw)

                action = req.action.lower().strip()
                server_name = req.server_name.strip()
                election_endpoint = req.election_endpoint.strip()

                if action == "rank":
                    resp = self._handle_rank(server_name, election_endpoint)
                elif action == "list":
                    resp = self._handle_list()
                elif action == "heartbeat":
                    resp = self._handle_heartbeat(server_name, election_endpoint)
                else:
                    _log("WARN", "UNKNOWN_ACTION", f"acao desconhecida: {action}")
                    resp = chat_pb2.ReferenceResponse(
                        timestamp_ms=_now_ms(),
                        action=action,
                        status="UNKNOWN_ACTION",
                    )

                self.socket.send(resp.SerializeToString())
        except KeyboardInterrupt:
            _log("WARN", "INTERRUPTED", "interrompido")
        finally:
            self._running = False
            self.socket.close()
            self.context.term()
            _log("INFO", "SHUTDOWN", "servico encerrado")


def main():
    parser = argparse.ArgumentParser(description="Reference Service")
    parser.add_argument(
        "--endpoint", default="tcp://*:5559",
        help="ZMQ REP bind endpoint (default: tcp://*:5559)",
    )
    args = parser.parse_args()
    svc = ReferenceService(endpoint=args.endpoint)
    svc.run()


if __name__ == "__main__":
    main()
