import asyncio
import time


class IntervalGate:
    """One shared gate per provider/worker, including all reading instances."""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def wait(self) -> None:
        async with self._lock:
            delay = max(0.0, self._next_at - time.monotonic())
            if delay:
                await asyncio.sleep(delay)
            self._next_at = time.monotonic() + self.interval


ARXIV_GATE = IntervalGate(3.0)
OPENALEX_GATE = IntervalGate(0.25)
