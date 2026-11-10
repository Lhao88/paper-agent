import asyncio
import sys

from app.runtime import run_async


def test_runtime_runs_coroutine_with_expected_windows_loop() -> None:
    async def inspect_loop() -> str:
        loop = asyncio.get_running_loop()
        if sys.platform == "win32":
            assert isinstance(loop, asyncio.SelectorEventLoop)
        return "executed"

    assert run_async(inspect_loop()) == "executed"


async def test_async_tests_use_same_windows_compatible_loop() -> None:
    if sys.platform == "win32":
        assert isinstance(asyncio.get_running_loop(), asyncio.SelectorEventLoop)
