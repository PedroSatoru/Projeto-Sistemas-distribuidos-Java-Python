"""
Data storage models for the server.
Data is persisted as JSON.
"""

import json
from datetime import datetime
from typing import List, Set, Optional
import os


class UserLogin:
    """Represents a user login record"""
    def __init__(self, username: str, timestamp: float):
        self.username = username
        self.timestamp = timestamp
    
    def to_dict(self):
        return {
            "username": self.username,
            "timestamp": self.timestamp,
            "datetime": datetime.fromtimestamp(self.timestamp).isoformat()
        }


class ServerData:
    """Manages server data persistence"""
    
    def __init__(self, data_file: str = "server_data.json"):
        self.data_file = data_file
        self.users: Set[str] = set()  # Logged in users
        self.channels: Set[str] = set()  # Available channels
        self.login_history: List[UserLogin] = []  # Login history with timestamps
        self.load_data()
    
    def load_data(self):
        """Load data from JSON file"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                    # IMPORTANTE: usuários logados NÃO são persistidos entre restarts
                    # Apenas o histórico de logins é mantido
                    self.users = set()  # Sempre vazio ao iniciar
                    self.channels = set(c.lower() for c in data.get("channels", []))  # case-insensitive
                    self.login_history = [
                        UserLogin(log["username"], log["timestamp"])
                        for log in data.get("login_history", [])
                    ]
            except Exception as e:
                print(f"✗ Erro ao carregar dados: {e}")
        else:
            self.users = set()
            self.channels = set()
            self.login_history = []
    
    def save_data(self):
        """Save data to JSON file"""
        try:
            data = {
                "users": list(self.users),
                "channels": list(self.channels),
                "login_history": [log.to_dict() for log in self.login_history]
            }
            with open(self.data_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving data: {e}")
    
    def add_user(self, username: str) -> bool:
        """Add a logged in user"""
        if username not in self.users:
            self.users.add(username)
            self.login_history.append(UserLogin(username, datetime.now().timestamp()))
            self.save_data()
            return True
        return False
    
    def add_channel(self, channel_name: str) -> bool:
        """Add a new channel (case-insensitive)"""
        channel_lower = channel_name.lower()
        if channel_lower not in self.channels:
            self.channels.add(channel_lower)
            self.save_data()
            return True
        return False
    
    def get_channels(self) -> List[str]:
        """Get all channels sorted"""
        return sorted(list(self.channels))
    
    def channel_exists(self, channel_name: str) -> bool:
        """Check if channel exists (case-insensitive)"""
        return channel_name.lower() in self.channels
    
    def user_exists(self, username: str) -> bool:
        """Check if user is logged in"""
        return username in self.users
