"""Keep a peer process alive: restart it when it is gone while a session is active."""

import time
from collections.abc import Callable


class Supervisor:
    def __init__(
        self,
        is_active: Callable[[], bool],
        is_alive: Callable[[], bool],
        start: Callable[[], object],
        interval: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._is_active, self._is_alive, self._start = is_active, is_alive, start
        self._interval, self._clock = interval, clock
        self._last: float | None = None

    def tick(self) -> bool:
        now = self._clock()
        if self._last is not None and now - self._last < self._interval:
            return False
        self._last = now
        if self._is_active() and not self._is_alive():
            self._start()
            return True
        return False
