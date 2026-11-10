from pathlib import Path
from secrets import token_urlsafe

import pytest
from psycopg.conninfo import conninfo_to_dict
from pydantic import ValidationError

from app.config import PROJECT_ROOT, Settings


def test_mock_mode_runs_without_provider_credentials() -> None:
    settings = Settings(_env_file=None)
    assert settings.llm_mode == "mock"
    assert settings.source_mode == "mock"


def test_live_mode_reports_missing_field_names_without_disclosing_secrets() -> None:
    secret_marker = token_urlsafe(24)
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None, llm_mode="live", db_password=secret_marker)
    assert "llm_api_key" in str(exc.value)
    assert secret_marker not in str(exc.value)


def test_storage_path_is_resolved_independently_of_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None, storage_root=Path(".local-data"))
    assert settings.storage_root == PROJECT_ROOT / ".local-data"


def test_special_characters_survive_both_database_connection_formats() -> None:
    special_value = "p@ss:% word'\\example"
    settings = Settings(_env_file=None, db_password=special_value)
    assert settings.database_url.password == special_value
    assert conninfo_to_dict(settings.checkpoint_dsn)["password"] == special_value
    assert special_value not in repr(settings)


def test_test_environment_cannot_point_to_business_database() -> None:
    with pytest.raises(ValidationError, match="_test"):
        Settings(_env_file=None, app_env="test", db_name="research")
    assert Settings(_env_file=None, app_env="test", db_name="research_test").db_name.endswith(
        "_test"
    )


@pytest.mark.parametrize("field", ["read_concurrency", "max_llm_calls", "max_download_mb"])
def test_resource_limits_cannot_be_zero(field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: 0})


def test_model_timeout_and_budget_are_separate_positive_values() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_timeout_seconds=-1)


def test_mcp_allowlists_are_parsed_as_json_arrays(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", '["localhost:8000"]')
    settings = Settings(_env_file=None)
    assert settings.mcp_allowed_hosts == ["localhost:8000"]


def test_live_mode_accepts_complete_provider_configuration() -> None:
    settings = Settings(
        _env_file=None,
        llm_mode="live",
        llm_api_key="fixture-only-key",
        llm_base_url="https://model.example.org/v1",
        llm_screen_model="screen-model",
        llm_research_model="research-model",
    )
    assert settings.llm_api_key.get_secret_value() == "fixture-only-key"
