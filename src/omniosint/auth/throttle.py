"""In-process attempt throttling.

Used for sign-in and first-run setup attempts. State is kept in memory by the
API process. OmniOSINT runs one API process, so the throttle sees every
attempt; it starts empty after a restart, which is why account lockout (stored
in the database) backs it up. Sharing it through Redis would only matter with
several API processes, which the architecture does not use.
"""

from __future__ import annotations

import time
from collections import OrderedDict, deque
from collections.abc import Callable


class SlidingWindowLimiter:
    """Allow at most ``limit`` hits per key in any ``window_seconds`` window."""

    def __init__(
        self,
        limit: int,
        window_seconds: float = 60.0,
        *,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        self._limit = limit
        self._window = window_seconds
        self._max_keys = max_keys
        self._clock = clock
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()

    def hit(self, key: str) -> float | None:
        """Record an attempt.

        Returns ``None`` when the attempt is allowed, otherwise the number of
        seconds until the next attempt will be allowed. Refused attempts are not
        recorded, so a blocked client is released as soon as the window passes.
        """
        now = self._clock()
        window = self._hits.get(key)
        if window is None:
            window = deque()
            self._hits[key] = window
            if len(self._hits) > self._max_keys:
                self._hits.popitem(last=False)
        else:
            self._hits.move_to_end(key)

        cutoff = now - self._window
        while window and window[0] <= cutoff:
            window.popleft()

        if len(window) >= self._limit:
            return max(0.0, window[0] + self._window - now)
        window.append(now)
        return None

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def clear(self) -> None:
        self._hits.clear()
