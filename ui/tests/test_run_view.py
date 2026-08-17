from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from ledger.init_db import initialize_database
from ledger.read_view import LedgerReadError, read_latest_run, read_run
from ui.run_view import format_run, main, safe_text


def _fixture(path: Path) -> Path:
    initialize_database(path)
    with sqlite3.connect(path) as db:
        db.executemany("INSERT INTO run VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            ("run-old", "v1", "env-old", "mapper", "source-only", "2026-01-01", "2026-01-01", 1, 2, "completed"),
            ("run-view", "v2", "env-view", "verifier", "GET-only", "2026-01-02", "2026-01-03", 30, 60, "verified"),
        ])
        db.executemany("INSERT INTO event VALUES (?, ?, ?, ?, ?, ?, ?)", [
            ("run-view", 2, "later", "second", "artifact-2", "allowed", "t2"),
            ("run-view", 2, "same-first", "same one", "artifact-same-1", "allowed", "t-same-1"),
            ("run-view", 2, "same-second", "same two", "artifact-same-2", "allowed", "t-same-2"),
            ("run-view", 1, "first", "one", "artifact-1", "blocked", "t1"),
        ])
        db.executemany("INSERT INTO hypothesis VALUES (?, ?, ?, ?, ?, ?, ?)", [
            ("hyp-submit", "run-view", "old-rule", "old claim", "e", "unverified", None),
            ("hyp-submit", "run-view", "new-rule", "latest claim", "e", "verified", "run-verifier"),
            ("hyp-verify", "run-other", "verify-rule", "verifier claim", "e", "verified", "run-view"),
        ])
        db.execute("INSERT INTO finding VALUES (?, ?, ?, ?, ?, ?)", ("finding-1", "hyp-submit", "high severity", "steps", "event://1", "enforce ownership"))
    return path


def test_explicit_and_latest_selection_and_event_order(tmp_path: Path) -> None:
    path = _fixture(tmp_path / "ledger.db")
    explicit = read_run("run-view", path)
    assert explicit == read_latest_run(path)
    assert [event.sequence_number for event in explicit.events] == [1, 2, 2, 2]
    assert [event.action_type for event in explicit.events] == ["first", "later", "same-first", "same-second"]
    rendered = format_run(explicit)
    assert rendered.index("same-first") < rendered.index("same-second")
    assert [hypothesis.id for hypothesis in explicit.hypotheses] == ["hyp-submit", "hyp-verify"]
    assert explicit.hypotheses[0].concise_claim == "latest claim"
    assert explicit.findings[0].id == "finding-1"


def test_no_events_hypotheses_or_findings_are_distinguished(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    initialize_database(path)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO run VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ("empty", "v", "e", "role", "scope", "s", "t", 0, 0, "empty"))
    output = format_run(read_run("empty", path))
    assert "No events recorded" in output
    assert "No hypotheses associated" in output
    assert "No findings linked" in output


def test_expected_errors_and_mutually_exclusive_arguments(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing.db"
    assert main(["--latest"], database_path=missing) != 0
    assert "does not exist" in capsys.readouterr().err
    path = _fixture(tmp_path / "ledger.db")
    assert main(["--run-id", "unknown"], database_path=path) != 0
    assert "not found" in capsys.readouterr().err
    assert main(["--latest", "--run-id", "run-view"], database_path=path) != 0
    assert "invalid arguments" in capsys.readouterr().err
    assert main([], database_path=path) != 0
    assert "invalid arguments" in capsys.readouterr().err
    empty = tmp_path / "empty.db"
    initialize_database(empty)
    assert main(["--latest"], database_path=empty) != 0
    assert "no runs" in capsys.readouterr().err


def test_terminal_text_is_neutralized_and_truncated() -> None:
    rendered = safe_text("hello\x1b[31m\nworld\r" + ("x" * 300), limit=40)
    assert "\x1b" not in rendered
    assert "\\n" in rendered and "\\r" in rendered
    assert rendered.endswith("...")
    assert len(rendered) == 40


def test_unicode_terminal_controls_are_neutralized_but_printable_unicode_survives() -> None:
    value = "café 雪 🚀\u009b\u202a\u202ehidden\u202c"
    rendered = safe_text(value)
    assert "café 雪 🚀" in rendered
    assert "\u009b" not in rendered
    assert "\u202a" not in rendered
    assert "\u202e" not in rendered
    assert "\u202c" not in rendered


def test_reading_does_not_modify_database(tmp_path: Path) -> None:
    path = _fixture(tmp_path / "ledger.db")
    before = hashlib.sha256(path.read_bytes()).digest()
    with sqlite3.connect(path) as db:
        counts_before = [db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("run", "event", "hypothesis", "finding")]
    read_run("run-view", path)
    after = hashlib.sha256(path.read_bytes()).digest()
    with sqlite3.connect(path) as db:
        counts_after = [db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("run", "event", "hypothesis", "finding")]
    assert before == after
    assert counts_before == counts_after


def test_unreadable_or_corrupt_ledger_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.db"
    path.write_text("not sqlite", encoding="utf-8")
    with pytest.raises(LedgerReadError, match="unreadable"):
        read_latest_run(path)
