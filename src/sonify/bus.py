"""A tiny thread-safe publish/subscribe bus.

The mapper and engine publish; the dashboard (and anything else) only
subscribes. Subscribers are plain callbacks, so they must return quickly.
Consumers that live on another thread or event loop should hand the event
off (e.g. ``loop.call_soon_threadsafe(queue.put_nowait, event)``).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Event:
    type: str
    data: Dict[str, Any]
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {"v": SCHEMA_VERSION, "type": self.type, "ts": self.ts, "data": self.data}


Callback = Callable[[Event], None]


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: Dict[int, Callback] = {}
        self._next_id = 0

    def subscribe(self, callback: Callback) -> Callable[[], None]:
        """Register ``callback``; returns a function that unsubscribes it."""
        with self._lock:
            sub_id = self._next_id
            self._next_id += 1
            self._subscribers[sub_id] = callback

        def unsubscribe() -> None:
            with self._lock:
                self._subscribers.pop(sub_id, None)

        return unsubscribe

    def publish(self, type: str, data: Optional[Dict[str, Any]] = None) -> Event:
        event = Event(type=type, data=data or {})
        with self._lock:
            callbacks = list(self._subscribers.values())
        for callback in callbacks:
            try:
                callback(event)
            except Exception:  # one bad subscriber must not affect the rest
                log.exception("event subscriber failed")
        return event
