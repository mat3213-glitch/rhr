"""Shared config + DB plumbing for the pipeline.

Everything in pipeline/ imports from here so we have one place for:
* resolving paths (repo root, data dir, config dir)
* loading config/keywords yaml
* opening the SQLite connection
"""
from __future__ import annotations

import json
import sqlite3
from functools import lru_cache
from pathlib import Path

import yaml

# rhr/ is the repo root.
ROOT = Path(__file__).resolve().parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "rhr.db"


def db() -> sqlite3.Connection:
    """Open a SQLite connection with sane defaults. Schema must be applied
    separately via ``data/schema.sql`` (see run.py init)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@lru_cache(maxsize=None)
def load_yaml(name: str) -> dict:
    p = CONFIG_DIR / name
    if not p.exists():
        return {}
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_sources() -> dict:
    return load_yaml("sources.yaml")


def load_keywords() -> dict[str, list[str]]:
    return load_yaml("keywords.yaml")


def flattened_keywords() -> list[str]:
    """All trigger phrases from keywords.yaml as a flat lowercase list."""
    groups = load_keywords()
    out: list[str] = []
    for phrases in groups.values():
        out.extend(p.lower() for p in phrases)
    return out


def log_run(
    conn: sqlite3.Connection,
    command: str,
    *,
    source: str | None = None,
    status: str = "ok",
    inserted: int = 0,
    updated: int = 0,
    message: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO run_log(command, source, started_at, finished_at,
                                status, rows_inserted, rows_updated, message)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            command,
            source,
            _utcnow(),
            _utcnow(),
            status,
            inserted,
            updated,
            message,
        ),
    )
    conn.commit()


def _utcnow() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def as_json(value) -> str:
    """Serialise a list/dict for a JSON-typed TEXT column."""
    return json.dumps(value, ensure_ascii=False)
