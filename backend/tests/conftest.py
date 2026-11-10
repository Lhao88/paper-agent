import asyncio
from collections.abc import Callable

import pytest

from app.runtime import create_event_loop


def pytest_asyncio_loop_factories(
    config: pytest.Config, item: pytest.Item
) -> dict[str, Callable[[], asyncio.AbstractEventLoop]]:
    return {"project": create_event_loop}
