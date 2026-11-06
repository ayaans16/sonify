from __future__ import annotations

import threading
from typing import List

from sonify.bus import Event, EventBus


def test_fan_out_to_every_subscriber() -> None:
    bus = EventBus()
    a: List[Event] = []
    b: List[Event] = []
    bus.subscribe(a.append)
    bus.subscribe(b.append)
    bus.publish("metric", {"signal": "cpu", "value": 1})
    assert [e.type for e in a] == ["metric"] == [e.type for e in b]
    assert a[0] is b[0]


def test_unsubscribe_stops_delivery() -> None:
    bus, seen = EventBus(), []
    unsubscribe = bus.subscribe(seen.append)
    bus.publish("a")
    unsubscribe()
    unsubscribe()  # idempotent
    bus.publish("b")
    assert [e.type for e in seen] == ["a"]


def test_failing_subscriber_does_not_block_others() -> None:
    bus, seen = EventBus(), []

    def boom(_event: Event) -> None:
        raise RuntimeError("bad subscriber")

    bus.subscribe(boom)
    bus.subscribe(seen.append)
    bus.publish("x")
    assert len(seen) == 1


def test_envelope_shape() -> None:
    event = EventBus().publish("sound", {"sound": "bell"})
    assert event.to_dict() == {"v": 1, "type": "sound", "ts": event.ts, "data": {"sound": "bell"}}


def test_concurrent_publishers_all_delivered() -> None:
    bus, seen, lock = EventBus(), [], threading.Lock()

    def collect(event: Event) -> None:
        with lock:
            seen.append(event)

    bus.subscribe(collect)
    threads = [threading.Thread(target=lambda: [bus.publish("t") for _ in range(100)]) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(seen) == 800
