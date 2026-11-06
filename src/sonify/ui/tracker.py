"""Bus subscriber that remembers recent history so new dashboards can catch up."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Tuple

from ..bus import Event, EventBus

HISTORY_WINDOW_S = 60.0
RECENT_SOUNDS = 200


class StateTracker:
    def __init__(self, bus: EventBus) -> None:
        self._lock = threading.Lock()
        self._metrics: Dict[str, Dict[str, Any]] = {}
        self._history: Dict[str, Deque[Tuple[float, float]]] = {}
        self._last_sound: Dict[str, Dict[str, Any]] = {}
        self._recent: Deque[Dict[str, Any]] = deque(maxlen=RECENT_SOUNDS)
        self._unsubscribe = bus.subscribe(self._on_event)

    def close(self) -> None:
        self._unsubscribe()

    def _on_event(self, event: Event) -> None:
        with self._lock:
            if event.type == "metric":
                signal = event.data["signal"]
                self._metrics[signal] = {"value": event.data["value"], "unit": event.data.get("unit", "")}
                history = self._history.setdefault(signal, deque())
                history.append((event.ts, event.data["value"]))
                while history and event.ts - history[0][0] > HISTORY_WINDOW_S:
                    history.popleft()
            elif event.type == "sound":
                entry = dict(event.data, ts=event.ts)
                self._recent.append(entry)
                if not event.data.get("suppressed"):
                    self._last_sound[event.data["signal"]] = entry

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            return {
                "metrics": {k: dict(v) for k, v in self._metrics.items()},
                "history": {
                    k: [[ts, v] for ts, v in h if now - ts <= HISTORY_WINDOW_S]
                    for k, h in self._history.items()
                },
                "last_sound": dict(self._last_sound),
                "recent_sounds": list(self._recent),
            }
