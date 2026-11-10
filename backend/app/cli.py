import argparse
import json
from pathlib import Path
from typing import Literal

from alembic import command
from alembic.config import Config
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import text

from app.config import PROJECT_ROOT, Settings, get_settings
from app.db.session import create_engine, get_test_settings
from app.llm.probe import probe_model
from app.runtime import run_async


def migration_config(settings: Settings) -> Config:
    config = Config(str(PROJECT_ROOT / "backend" / "alembic.ini"))
    config.attributes["settings"] = settings
    return config


async def init_checkpoints(settings: Settings) -> None:
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_dsn) as saver:
        await saver.setup()


async def diagnose(settings: Settings) -> dict[str, object]:
    engine = create_engine(settings)
    try:
        async with engine.connect() as connection:
            db = await connection.scalar(text("select current_database()"))
            version = await connection.scalar(text("show server_version"))
        for subdirectory in ("documents", "parsed", "exports"):
            (settings.storage_root / subdirectory).mkdir(parents=True, exist_ok=True)
        return {
            "database": {"status": "ok", "name": db, "server_version": version},
            "storage": {"status": "ok"},
            "llm_mode": settings.llm_mode,
            "source_mode": settings.source_mode,
            "model_key_present": bool(settings.llm_api_key.get_secret_value()),
        }
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Academic workbench maintenance")
    parser.add_argument(
        "command",
        choices=[
            "doctor",
            "init-checkpoints",
            "prepare-test-db",
            "probe-model",
            "demo-seed",
            "run-demo",
            "evaluate",
            "score-evaluation",
            "export-openapi",
        ],
    )
    parser.add_argument("--profile", choices=["screen", "research"], default="screen")
    parser.add_argument("--approve-fixture-plan", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--human", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    try:
        if args.command == "export-openapi":
            from app.main import create_app

            destination = args.output or (PROJECT_ROOT / "frontend" / "openapi.json")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(
                json.dumps(create_app(settings).openapi(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print("Actual API schema exported.")
        elif args.command == "evaluate":
            from app.evaluation.runner import evaluate

            if args.config is None or args.output is None:
                parser.error("evaluate requires --config and a new --output directory")
            print(
                json.dumps(
                    run_async(evaluate(args.config, args.output, settings)), ensure_ascii=False
                )
            )
        elif args.command == "score-evaluation":
            from app.evaluation.runner import score_existing

            if args.input is None or args.human is None or args.output is None:
                parser.error("score-evaluation requires --input, --human and a new --output")
            print(
                json.dumps(score_existing(args.input, args.human, args.output), ensure_ascii=False)
            )
        elif args.command == "doctor":
            print(json.dumps(run_async(diagnose(settings)), ensure_ascii=False))
        elif args.command in {"demo-seed", "run-demo"}:
            from app.demo import demo_seed, run_demo

            result = (
                run_async(demo_seed(settings))
                if args.command == "demo-seed"
                else run_async(run_demo(settings, args.approve_fixture_plan))
            )
            print(json.dumps(result, ensure_ascii=False))
        elif args.command == "init-checkpoints":
            run_async(init_checkpoints(settings))
            print("Checkpoint schema ready.")
        elif args.command == "probe-model":
            profile: Literal["screen", "research"] = (
                "research" if args.profile == "research" else "screen"
            )
            print(json.dumps(run_async(probe_model(settings, profile)), ensure_ascii=False))
        else:
            testing = get_test_settings(settings)
            command.upgrade(migration_config(testing), "head")
            run_async(init_checkpoints(testing))
            print(f"Test schema ready: {testing.db_name}")
    except Exception as exc:
        # Maintenance logs name the error class; connection strings may contain secrets.
        parser.exit(
            1, f"Operation failed ({type(exc).__name__}); check configuration and DB access.\n"
        )


if __name__ == "__main__":
    main()
