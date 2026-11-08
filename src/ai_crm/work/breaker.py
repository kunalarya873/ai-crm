import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class _State:
    failures: int = 0
    opened_at: float | None = None
    probe_started: float | None = None


class CircuitBreaker:
    """In-process breaker per key. Open after `threshold` consecutive failures; once the cooldown
    passes it is half-open and admits a single probe job: success closes it, failure re-opens it.

    State is not shared between processes, so each worker trips on its own."""

    def __init__(
        self,
        threshold: int,
        cooldown_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._states: dict[str, _State] = {}

    def is_open(self, key: str) -> bool:
        state = self._states.get(key)
        if state is None or state.opened_at is None:
            return False
        return self._clock() - state.opened_at < self.cooldown_seconds

    def blocked(self) -> bool:
        """True while any key is cooling down or has its probe in flight."""
        return any(self.is_open(key) or self._probing(state) for key, state in self._states.items())

    def _probing(self, state: _State) -> bool:
        # A probe that never reported back (crash between claim and outcome) expires after one
        # cooldown instead of blocking the provider forever.
        return (
            state.probe_started is not None
            and self._clock() - state.probe_started < self.cooldown_seconds
        )

    def start_probe(self, key: str) -> None:
        state = self._states.get(key)
        if state is not None and state.opened_at is not None and not self.is_open(key):
            state.probe_started = self._clock()

    def release(self, key: str) -> None:
        """A probe ended without a verdict (for example a permanent error); stay half-open."""
        state = self._states.get(key)
        if state is not None:
            state.probe_started = None

    def record_success(self, key: str) -> None:
        self._states.pop(key, None)

    def record_failure(self, key: str) -> None:
        state = self._states.setdefault(key, _State())
        state.failures += 1
        state.probe_started = None
        if state.failures >= self.threshold:
            state.opened_at = self._clock()

    def open_keys(self) -> list[str]:
        return sorted(key for key in self._states if self.is_open(key))
