import os

import pytest

from app.config import Settings
from app.db.session import get_test_settings
from app.llm.probe import probe_model

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE_TESTS") != "1", reason="explicit live cost opt-in required"
    ),
]


async def test_actual_model_protocol_probe():
    settings = get_test_settings(Settings())
    if settings.llm_mode != "live":
        pytest.skip("LLM_MODE=live and actual credentials are required")
    response = await probe_model(settings, "screen")
    assert response["mode"] == "live" and response["run_id"]
