"""Shared fixtures for RHR tests."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

SCHEMA_SQL = Path(__file__).resolve().parent.parent / "data" / "schema.sql"


@pytest.fixture()
def db():
    """In-memory SQLite connection with the RHR schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    schema = SCHEMA_SQL.read_text(encoding="utf-8")
    conn.executescript(schema)
    yield conn
    conn.close()
