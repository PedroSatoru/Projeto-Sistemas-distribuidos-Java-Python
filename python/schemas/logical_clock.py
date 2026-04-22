"""
Lamport logical clock implementation.

Rules:
1. Increment counter before every send; attach counter value to message.
2. On receive, update counter to max(local, received) + 1.
"""

import threading


class LogicalClock:
    """Thread-safe Lamport logical clock."""

    def __init__(self):
        self._counter = 0
        self._lock = threading.Lock()

    @property
    def value(self) -> int:
        """Current counter value (read-only)."""
        with self._lock:
            return self._counter

    def increment(self) -> int:
        """Increment before sending a message. Returns the new value."""
        with self._lock:
            self._counter += 1
            return self._counter

    def update(self, received: int) -> int:
        """Update on receiving a message. Returns the new value."""
        with self._lock:
            self._counter = max(self._counter, received) + 1
            return self._counter
