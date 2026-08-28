"""SQLite helpers for Crack's disposable synthetic school portal."""

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
            CREATE TABLE IF NOT EXISTS people (
                id TEXT PRIMARY KEY,
                role TEXT NOT NULL CHECK (role IN ('teacher', 'student')),
                token TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS classes (
                id TEXT PRIMARY KEY,
                teacher_id TEXT NOT NULL REFERENCES people(id),
                title TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS assignments (
                id TEXT PRIMARY KEY,
                class_id TEXT NOT NULL REFERENCES classes(id),
                title TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS submissions (
                id TEXT PRIMARY KEY,
                assignment_id TEXT NOT NULL REFERENCES assignments(id),
                student_id TEXT NOT NULL REFERENCES people(id),
                body TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS grades (
                id TEXT PRIMARY KEY,
                submission_id TEXT NOT NULL UNIQUE REFERENCES submissions(id),
                teacher_id TEXT NOT NULL REFERENCES people(id),
                feedback TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('draft', 'reviewed', 'published'))
            );
            """
        )
