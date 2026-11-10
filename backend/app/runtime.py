import asyncio
import sys
from collections.abc import Coroutine
from typing import Any


def create_event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.SelectorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    with asyncio.Runner(loop_factory=create_event_loop) as runner:
        return runner.run(coro)
