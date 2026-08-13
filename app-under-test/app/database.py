"""SQLite helpers for the disposable demo notes app."""

import os
import sqlite3
from pathlib import Path


def database_path() -> str:
    return os.getenv("APP_DB_PATH", "data/demo_app.db")


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(database_path())
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    path = Path(database_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                token TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS records (
                id TEXT PRIMARY KEY,
                owner_account_id TEXT NOT NULL REFERENCES accounts(id),
                title TEXT NOT NULL,
                body TEXT NOT NULL
            );
            """
        )
