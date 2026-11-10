"""Start an isolated project-owned development cluster; never use existing server data."""

import argparse
import secrets
import subprocess
from pathlib import Path

import psycopg
from psycopg import sql


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", type=Path, required=True)
    parser.add_argument("--port", type=int, default=54329)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    data = root / ".tools" / "postgres-data"
    data.parent.mkdir(exist_ok=True)
    env_file = root / ".env"
    if not env_file.exists():
        credential = secrets.token_urlsafe(32)
        template = (root / ".env.example").read_text(encoding="utf-8")
        template = template.replace("DB_PORT=5432", f"DB_PORT={args.port}")
        template = template.replace("DB_PASSWORD=\n", f"DB_PASSWORD={credential}\n")
        env_file.write_text(template, encoding="utf-8")
    from dotenv import dotenv_values

    config = dotenv_values(env_file)
    if config.get("DB_HOST") != "127.0.0.1" or config.get("DB_PORT") != str(args.port):
        raise SystemExit("Existing .env does not target this isolated cluster; no files changed.")
    credential = config.get("DB_PASSWORD")
    if not credential:
        raise SystemExit("Set a nonempty DB_PASSWORD in .env before initializing the cluster.")
    password_file = root / ".tools" / "db-bootstrap-password"
    if not (data / "PG_VERSION").exists():
        password_file.write_text(credential, encoding="utf-8")
        subprocess.run(
            [
                str(args.pg_bin / "initdb.exe"), "-D", str(data), "-U", "research",
                "--auth=scram-sha-256", "--encoding=UTF8", "--locale=C",
                f"--pwfile={password_file}",
            ],
            check=True,
        )
    ctl = str(args.pg_bin / "pg_ctl.exe")
    status = subprocess.run([ctl, "-D", str(data), "status"], capture_output=True)
    if status.returncode != 0:
        subprocess.run(
            [
                ctl, "-D", str(data), "-l", str(root / ".tools" / "postgres.log"),
                "-w", "start", "-o", f"-h 127.0.0.1 -p {args.port}",
            ],
            check=True,
        )
    with psycopg.connect(
        host="127.0.0.1", port=args.port, dbname="postgres", user="research",
        password=credential, autocommit=True,
    ) as connection:
        for name in ("research", "research_test"):
            exists = connection.execute(
                "select 1 from pg_database where datname=%s", (name,)
            ).fetchone()
            if not exists:
                connection.execute(sql.SQL("CREATE DATABASE {} OWNER research").format(
                    sql.Identifier(name)
                ))
    print(f"Project development databases ready on 127.0.0.1:{args.port}; credentials not printed.")


if __name__ == "__main__":
    main()
