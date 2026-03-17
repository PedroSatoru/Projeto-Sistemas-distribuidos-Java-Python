"""
Message schema definitions for the distributed chat system.
All messages are serialized using MessagePack and include a timestamp.
"""

import msgpack
import time
from typing import Any, Dict, Optional


class MessageType:
    """Message type constants"""
    LOGIN = "LOGIN"
    LOGIN_RESPONSE = "LOGIN_RESPONSE"
    LIST_CHANNELS = "LIST_CHANNELS"
    LIST_CHANNELS_RESPONSE = "LIST_CHANNELS_RESPONSE"
    CREATE_CHANNEL = "CREATE_CHANNEL"
    CREATE_CHANNEL_RESPONSE = "CREATE_CHANNEL_RESPONSE"


class Message:
    """Base message class with timestamp and type"""
    
    def __init__(self, message_type: str, payload: Dict[str, Any]):
        self.message_type = message_type
        self.timestamp = time.time()
        self.payload = payload
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary for serialization"""
        return {
            "type": self.message_type,
            "timestamp": self.timestamp,
            "payload": self.payload
        }
    
    def serialize(self) -> bytes:
        """Serialize message to MessagePack bytes"""
        return msgpack.packb(self.to_dict(), use_bin_type=True)
    
    @staticmethod
    def deserialize(data: bytes) -> 'Message':
        """Deserialize message from MessagePack bytes"""
        dict_data = msgpack.unpackb(data, raw=False)
        return Message(
            message_type=dict_data["type"],
            payload=dict_data["payload"]
        )


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
