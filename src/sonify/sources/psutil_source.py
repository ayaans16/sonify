"""System metrics via psutil: CPU, memory, disk and network errors."""

from __future__ import annotations

import time
from typing import Callable, Dict, Iterable, List, Optional

import psutil

from ..models import Sample
from .base import PollingSource

ALL_SIGNALS = ("cpu_percent", "memory_percent", "disk_percent", "net_errors")


class PsutilSource(PollingSource):
    name = "psutil"

    def __init__(
        self,
        signals: Optional[Iterable[str]] = None,
        interval_s: float = 1.0,
        host: str = "local",
        disk_path: str = "/",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        wanted = list(signals) if signals is not None else list(ALL_SIGNALS)
        unknown = [s for s in wanted if s not in ALL_SIGNALS]
        if unknown:
            raise ValueError(f"psutil source cannot provide: {', '.join(unknown)}")
        self._wanted = wanted
        self.interval_s = interval_s
        self._host = host
        self._disk_path = disk_path
        self._clock = clock
        self._last_errors: Optional[int] = None
        self._last_errors_at = 0.0
        psutil.cpu_percent(interval=None)  # prime: the first call always returns 0.0

    def signals(self) -> List[str]:
        return list(self._wanted)

    def collect(self) -> List[Sample]:
        readers: Dict[str, Callable[[], Optional[Sample]]] = {
            "cpu_percent": lambda: self._sample("cpu_percent", psutil.cpu_percent(interval=None), "%"),
            "memory_percent": lambda: self._sample("memory_percent", psutil.virtual_memory().percent, "%"),
            "disk_percent": lambda: self._sample("disk_percent", psutil.disk_usage(self._disk_path).percent, "%"),
            "net_errors": self._net_errors,
        }
        samples = (readers[name]() for name in self._wanted)
        return [s for s in samples if s is not None]

    def _sample(self, signal: str, value: float, unit: str) -> Sample:
        return Sample(signal=signal, value=float(value), unit=unit, host=self._host)

    def _net_errors(self) -> Optional[Sample]:
        """Errors + drops per second since the previous reading."""
        counters = psutil.net_io_counters()
        if counters is None:
            return None
        total = counters.errin + counters.errout + counters.dropin + counters.dropout
        now = self._clock()
        previous, previous_at = self._last_errors, self._last_errors_at
        self._last_errors, self._last_errors_at = total, now
        if previous is None or now <= previous_at:
            return None  # need two readings to get a rate
        rate = max(0, total - previous) / (now - previous_at)
        return self._sample("net_errors", rate, "/s")
