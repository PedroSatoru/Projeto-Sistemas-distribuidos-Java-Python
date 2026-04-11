"""Message schema definitions using Protobuf with binary serialization."""

import importlib
import time
from pathlib import Path
from typing import Any, Dict, Optional


def _load_chat_pb2():
    try:
        from . import chat_pb2 as module
        return module
    except ImportError:
        from grpc_tools import protoc

        base_dir = Path(__file__).resolve().parent.parent
        proto_dir = base_dir / "proto"
        out_dir = base_dir / "schemas"
        proto_file = proto_dir / "chat.proto"

        result = protoc.main([
            "grpc_tools.protoc",
            f"-I{proto_dir}",
            f"--python_out={out_dir}",
            str(proto_file),
        ])
        if result != 0:
            raise RuntimeError("Falha ao gerar chat_pb2.py a partir de chat.proto")

        return importlib.import_module("schemas.chat_pb2")


chat_pb2 = _load_chat_pb2()


class MessageType:
    """Message type constants"""
    LOGIN = "LOGIN"
    LOGIN_RESPONSE = "LOGIN_RESPONSE"
    LIST_CHANNELS = "LIST_CHANNELS"
    LIST_CHANNELS_RESPONSE = "LIST_CHANNELS_RESPONSE"
    CREATE_CHANNEL = "CREATE_CHANNEL"
    CREATE_CHANNEL_RESPONSE = "CREATE_CHANNEL_RESPONSE"
    PUBLISH_REQUEST = "PUBLISH_REQUEST"
    PUBLISH_RESPONSE = "PUBLISH_RESPONSE"
    CHAT_MESSAGE = "CHAT_MESSAGE"
    ERROR_RESPONSE = "ERROR_RESPONSE"


class Message:
    """Base message class with timestamp and type"""
    
    def __init__(self, message_type: str, payload: Dict[str, Any], timestamp_ms: Optional[int] = None):
        self.message_type = message_type
        self.timestamp = time.time()
        self.timestamp_ms = timestamp_ms
        self.payload = payload
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary for serialization"""
        return {
            "type": self.message_type,
            "timestamp": self.timestamp,
            "payload": self.payload
        }
    
    def serialize(self) -> bytes:
        """Serialize message to Protobuf bytes"""
        now_ms = self.timestamp_ms if self.timestamp_ms is not None else int(time.time() * 1000)
        self.timestamp_ms = now_ms

        if self.message_type == MessageType.LOGIN:
            msg = chat_pb2.ClientRequest(
                timestamp_ms=now_ms,
                login_request=chat_pb2.LoginRequest(
                    timestamp_ms=now_ms,
                    username=self.payload.get("username", "")
                )
            )
            return msg.SerializeToString()

        if self.message_type == MessageType.LIST_CHANNELS:
            msg = chat_pb2.ClientRequest(
                timestamp_ms=now_ms,
                list_channels_request=chat_pb2.ListChannelsRequest(timestamp_ms=now_ms)
            )
            return msg.SerializeToString()

        if self.message_type == MessageType.CREATE_CHANNEL:
            msg = chat_pb2.ClientRequest(
                timestamp_ms=now_ms,
                create_channel_request=chat_pb2.CreateChannelRequest(
                    timestamp_ms=now_ms,
                    channel_name=self.payload.get("channel_name", "")
                )
            )
            return msg.SerializeToString()

        if self.message_type == MessageType.LOGIN_RESPONSE:
            msg = chat_pb2.ServerResponse(
                timestamp_ms=now_ms,
                login_response=chat_pb2.LoginResponse(
                    timestamp_ms=now_ms,
                    success=bool(self.payload.get("success", False)),
                    error=self.payload.get("error", "")
                )
            )
            return msg.SerializeToString()

        if self.message_type == MessageType.LIST_CHANNELS_RESPONSE:
            msg = chat_pb2.ServerResponse(
                timestamp_ms=now_ms,
                list_channels_response=chat_pb2.ListChannelsResponse(
                    timestamp_ms=now_ms,
                    channels=self.payload.get("channels", [])
                )
            )
            return msg.SerializeToString()

        if self.message_type == MessageType.CREATE_CHANNEL_RESPONSE:
            msg = chat_pb2.ServerResponse(
                timestamp_ms=now_ms,
                create_channel_response=chat_pb2.CreateChannelResponse(
                    timestamp_ms=now_ms,
                    success=bool(self.payload.get("success", False)),
                    error=self.payload.get("error", "")
                )
            )
            return msg.SerializeToString()

        if self.message_type == MessageType.PUBLISH_REQUEST:
            msg = chat_pb2.ClientRequest(
                timestamp_ms=now_ms,
                publish_request=chat_pb2.PublishRequest(
                    timestamp_ms=now_ms,
                    channel_name=self.payload.get("channel_name", ""),
                    message_text=self.payload.get("message_text", ""),
                    username=self.payload.get("username", "")
                )
            )
            return msg.SerializeToString()

        if self.message_type == MessageType.PUBLISH_RESPONSE:
            msg = chat_pb2.ServerResponse(
                timestamp_ms=now_ms,
                publish_response=chat_pb2.PublishResponse(
                    timestamp_ms=now_ms,
                    success=bool(self.payload.get("success", False)),
                    error=self.payload.get("error", "")
                )
            )
            return msg.SerializeToString()
            
        if self.message_type == MessageType.CHAT_MESSAGE:
            msg = chat_pb2.ChatMessage(
                timestamp_ms=now_ms,
                channel_name=self.payload.get("channel_name", ""),
                username=self.payload.get("username", ""),
                message_text=self.payload.get("message_text", "")
            )
            return msg.SerializeToString()

        if self.message_type == MessageType.ERROR_RESPONSE:
            msg = chat_pb2.ServerResponse(
                timestamp_ms=now_ms,
                error_response=chat_pb2.ErrorResponse(
                    timestamp_ms=now_ms,
                    error=self.payload.get("error", "Unknown error")
                )
            )
            return msg.SerializeToString()

        msg = chat_pb2.ServerResponse(
            timestamp_ms=now_ms,
            error_response=chat_pb2.ErrorResponse(
                timestamp_ms=now_ms,
                error="Unknown message type"
            )
        )
        return msg.SerializeToString()
    
    @staticmethod
    def deserialize_request(data: bytes) -> 'Message':
        """Deserialize ClientRequest bytes into Message"""
        req = chat_pb2.ClientRequest()
        req.ParseFromString(data)
        req_action = req.WhichOneof("action")

        if req_action == "login_request":
            return Message(MessageType.LOGIN, {"username": req.login_request.username}, timestamp_ms=req.timestamp_ms)

        if req_action == "list_channels_request":
            return Message(MessageType.LIST_CHANNELS, {}, timestamp_ms=req.timestamp_ms)

        if req_action == "create_channel_request":
            return Message(MessageType.CREATE_CHANNEL, {"channel_name": req.create_channel_request.channel_name}, timestamp_ms=req.timestamp_ms)

        if req_action == "publish_request":
            return Message(MessageType.PUBLISH_REQUEST, {
                "channel_name": req.publish_request.channel_name,
                "message_text": req.publish_request.message_text,
                "username": req.publish_request.username
            }, timestamp_ms=req.timestamp_ms)

        raise ValueError("ClientRequest sem acao valida")

    @staticmethod
    def deserialize_response(data: bytes) -> 'Message':
        """Deserialize ServerResponse bytes into Message"""
        resp = chat_pb2.ServerResponse()
        resp.ParseFromString(data)
        resp_action = resp.WhichOneof("action")

        if resp_action == "login_response":
            return Message(
                MessageType.LOGIN_RESPONSE,
                {
                    "success": resp.login_response.success,
                    "error": resp.login_response.error,
                },
                timestamp_ms=resp.timestamp_ms,
            )

        if resp_action == "list_channels_response":
            return Message(
                MessageType.LIST_CHANNELS_RESPONSE,
                {"channels": list(resp.list_channels_response.channels)},
                timestamp_ms=resp.timestamp_ms,
            )

        if resp_action == "create_channel_response":
            return Message(
                MessageType.CREATE_CHANNEL_RESPONSE,
                {
                    "success": resp.create_channel_response.success,
                    "error": resp.create_channel_response.error,
                },
                timestamp_ms=resp.timestamp_ms,
            )

        if resp_action == "publish_response":
            return Message(
                MessageType.PUBLISH_RESPONSE,
                {
                    "success": resp.publish_response.success,
                    "error": resp.publish_response.error,
                },
                timestamp_ms=resp.timestamp_ms,
            )

        if resp_action == "error_response":
            return Message(
                MessageType.ERROR_RESPONSE,
                {"error": resp.error_response.error},
                timestamp_ms=resp.timestamp_ms,
            )

        return Message(MessageType.ERROR_RESPONSE, {"error": "Invalid payload"})

    @staticmethod
    def deserialize(data: bytes) -> 'Message':
        """Backward-compatible auto-deserialize (defaults to response first)."""
        response = Message.deserialize_response(data)
        if response.message_type != MessageType.ERROR_RESPONSE or response.payload.get("error") != "Invalid payload":
            return response
        return Message.deserialize_request(data)


class LoginMessage(Message):
    """Client sends username to login"""
    def __init__(self, username: str):
        super().__init__(MessageType.LOGIN, {"username": username})


class LoginResponseMessage(Message):
    """Server responds to login request"""
    def __init__(self, success: bool, error: Optional[str] = None):
        payload = {"success": success}
        if error:
            payload["error"] = error
        super().__init__(MessageType.LOGIN_RESPONSE, payload)


class ListChannelsMessage(Message):
    """Client requests list of channels"""
    def __init__(self):
        super().__init__(MessageType.LIST_CHANNELS, {})


class ListChannelsResponseMessage(Message):
    """Server responds with list of channels"""
    def __init__(self, channels: list):
        super().__init__(MessageType.LIST_CHANNELS_RESPONSE, {"channels": channels})


class CreateChannelMessage(Message):
    """Client requests to create a new channel"""
    def __init__(self, channel_name: str):
        super().__init__(MessageType.CREATE_CHANNEL, {"channel_name": channel_name})


class CreateChannelResponseMessage(Message):
    """Server responds to channel creation request"""
    def __init__(self, success: bool, error: Optional[str] = None):
        payload = {"success": success}
        if error:
            payload["error"] = error
        super().__init__(MessageType.CREATE_CHANNEL_RESPONSE, payload)


class PublishRequestMessage(Message):
    """Client requests to publish a message"""
    def __init__(self, channel_name: str, message_text: str, username: str = ""):
        super().__init__(MessageType.PUBLISH_REQUEST, {
            "channel_name": channel_name,
            "message_text": message_text,
            "username": username
        })


class PublishResponseMessage(Message):
    """Server responds to publish request"""
    def __init__(self, success: bool, error: Optional[str] = None):
        payload = {"success": success}
        if error:
            payload["error"] = error
        super().__init__(MessageType.PUBLISH_RESPONSE, payload)


class ChatMessageBody(Message):
    """Message distributed via Pub/Sub"""
    def __init__(self, channel_name: str, username: str, message_text: str, timestamp_ms: Optional[int] = None):
        super().__init__(MessageType.CHAT_MESSAGE, {
            "channel_name": channel_name,
            "username": username,
            "message_text": message_text
        }, timestamp_ms=timestamp_ms)
    
    @staticmethod
    def deserialize_chat_message(data: bytes) -> 'ChatMessageBody':
        msg = chat_pb2.ChatMessage()
        msg.ParseFromString(data)
        return ChatMessageBody(
            channel_name=msg.channel_name,
            username=msg.username,
            message_text=msg.message_text,
            timestamp_ms=msg.timestamp_ms
        )
