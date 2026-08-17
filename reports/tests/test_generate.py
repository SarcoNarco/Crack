from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from ledger.init_db import initialize_database
from ledger.read_view import read_run
from reports.generate import ReportIntegrityError, _atomic_write, generate, main, markdown_text, render_html, render_markdown, report_paths, safe_text


def _fixture(path: Path, *, hostile: bool = False) -> Path:
    initialize_database(path)
    claim = '<img src=x onerror=alert(1)>\n# not-a-heading' if hostile else 'Account A can read Account B record'
    with sqlite3.connect(path) as db:
        db.executemany('INSERT INTO run VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', [
            ('old-verifier', 'v0', 'reset-old', 'verifier', 'GET only', 's0', 'e0', 1, 2, 'completed'),
            ('report-verifier:/unsafe', 'v1', 'reset-main', 'verifier', 'local GET-only', 's1', 'e1', 30, 60, 'completed'),
            ('newer-failed-verifier', 'v2', 'reset-failed', 'verifier', 'GET only', 's2', 'e2', 3, 4, 'failed'),
            ('newer-identity', 'v2', 'reset-new', 'identity', 'normal flow', 's2', 'e2', 3, 4, 'completed'),
        ])
        db.executemany('INSERT INTO hypothesis VALUES (?, ?, ?, ?, ?, ?, ?)', [
            ('verified', 'submitted', 'record owner must match authenticated account', claim, 'Account B ID then Account A 200', 'verified', 'report-verifier:/unsafe'),
            ('unverified', 'submitted', 'other rule', 'Not yet reproduced', 'Expected evidence', 'unverified', 'report-verifier:/unsafe'),
            ('inconclusive', 'submitted', 'third rule', 'Needs review', 'Expected evidence', 'inconclusive', 'report-verifier:/unsafe'),
        ])
        steps = '[{"verifier_role":"verifier_a","snapshot_id":"reset-a","steps":[{"account":"account_b","executed":true,"method":"GET","proposed_path":"/records/mine","resolved_path":"/records/mine","status_code":200},{"account":"account_a","executed":true,"method":"GET","proposed_path":"/records/{record_id}","resolved_path":"/records/note-b","status_code":200}]},{"verifier_role":"verifier_b","snapshot_id":"reset-b","steps":[{"account":"account_a","executed":true,"method":"GET","proposed_path":"/records/note-b","resolved_path":"/records/note-b","status_code":200}]}]'
        db.execute('INSERT INTO finding VALUES (?, ?, ?, ?, ?, ?)', ('finding-1', 'verified', 'cross-account disclosure', steps, '["ledger://event/1", "ledger://event/2"]', 'enforce ownership'))
        db.executemany('INSERT INTO event VALUES (?, ?, ?, ?, ?, ?, ?)', [
            ('report-verifier:/unsafe', 2, 'later', 'summary two', 'event://2', 'allowed', 't2'),
            ('report-verifier:/unsafe', 1, 'first', 'summary one', 'event://1', 'allowed', 't1'),
        ])
    return path


def test_latest_is_verifier_and_generates_both_formats(tmp_path: Path) -> None:
    db, output = _fixture(tmp_path / 'ledger.db'), tmp_path / 'output'
    assert main(['--latest'], database_path=db, output_path=output) == 0
    md, page = report_paths('report-verifier:/unsafe', output)
    assert md.is_file() and page.is_file()
    text = md.read_text()
    assert text.index('## Scope and limitations') < text.index('## Verified findings')
    assert 'Verified findings: 1' in text and 'Unverified hypotheses: 1' in text and 'Inconclusive hypotheses: 1' in text
    assert r'reset\-a' in text and r'reset\-b' in text and r'Synthetic account: account\_a' in text
    assert 'Not yet reproduced' in text and '### Hypothesis `unverified`' in text
    assert page.read_text().startswith('<!doctype html>')


def test_explicit_unknown_and_non_verifier_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = _fixture(tmp_path / 'ledger.db')
    assert main(['--run-id', 'unknown'], database_path=db, output_path=tmp_path / 'out') == 2
    assert 'not found' in capsys.readouterr().err
    assert main(['--run-id', 'newer-identity'], database_path=db, output_path=tmp_path / 'out') == 2
    assert 'not a verifier' in capsys.readouterr().err
    assert main(['--run-id', 'newer-failed-verifier'], database_path=db, output_path=tmp_path / 'out') == 2
    assert 'not completed' in capsys.readouterr().err


def test_integrity_rejects_inconsistent_finding_and_missing_finding(tmp_path: Path) -> None:
    db = _fixture(tmp_path / 'ledger.db')
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE hypothesis SET verification_status = 'unverified' WHERE id = 'verified'")
    with pytest.raises(ReportIntegrityError, match='not verified'):
        render_markdown(read_run('report-verifier:/unsafe', db))
    db = _fixture(tmp_path / 'missing.db')
    with sqlite3.connect(db) as connection:
        connection.execute('DELETE FROM finding')
    with pytest.raises(ReportIntegrityError, match='no finding'):
        render_markdown(read_run('report-verifier:/unsafe', db))


def test_malformed_reproduction_and_deterministic_output(tmp_path: Path) -> None:
    db, output = _fixture(tmp_path / 'ledger.db'), tmp_path / 'output'
    view = read_run('report-verifier:/unsafe', db)
    first = generate(view, output)
    first_bytes = tuple(path.read_bytes() for path in first)
    assert first == generate(view, output)
    assert first_bytes == tuple(path.read_bytes() for path in first)
    assert render_markdown(view).index('first') < render_markdown(view).index('later')
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE finding SET reproduction_steps = 'not json'")
    with pytest.raises(ReportIntegrityError, match='malformed reproduction JSON'):
        render_markdown(read_run('report-verifier:/unsafe', db))


def test_safe_markdown_html_and_unicode_controls(tmp_path: Path) -> None:
    db = _fixture(tmp_path / 'ledger.db', hostile=True)
    markdown, page = render_markdown(read_run('report-verifier:/unsafe', db)), render_html(read_run('report-verifier:/unsafe', db))
    assert '\\<img' in markdown and '\\<' in markdown and '\\#' in markdown
    assert '&lt;img' in page and '<img src=x' not in page and '<pre>' not in page and 'onerror=' in page
    value = 'café 雪 🚀\u009b\u202e\n# title'
    assert 'café 雪 🚀' in safe_text(value) and '\u009b' not in safe_text(value) and '\u202e' not in safe_text(value)
    assert '\\#' in markdown_text(value)


def test_missing_empty_unchanged_ledger_and_portable_names(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / 'missing.db'
    assert main(['--latest'], database_path=missing, output_path=tmp_path / 'out') == 2
    assert 'does not exist' in capsys.readouterr().err
    empty = tmp_path / 'empty.db'
    initialize_database(empty)
    assert main(['--latest'], database_path=empty, output_path=tmp_path / 'out') == 2
    assert 'no completed verifier runs' in capsys.readouterr().err
    db = _fixture(tmp_path / 'ledger.db')
    before = hashlib.sha256(db.read_bytes()).digest()
    with sqlite3.connect(db) as connection:
        counts_before = [connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in ('run', 'event', 'hypothesis', 'finding')]
    generate(read_run('report-verifier:/unsafe', db), tmp_path / 'out')
    assert before == hashlib.sha256(db.read_bytes()).digest()
    with sqlite3.connect(db) as connection:
        counts_after = [connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in ('run', 'event', 'hypothesis', 'finding')]
    assert counts_before == counts_after
    first, second = report_paths('a/b:c*?<>|', tmp_path)
    assert first.suffix == '.md' and second.suffix == '.html' and all(char not in first.name for char in '/:*?<>|')


def test_atomic_write_leaves_no_partial_target_when_replace_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / 'report.md'
    monkeypatch.setattr('reports.generate.os.replace', lambda *_: (_ for _ in ()).throw(OSError('replace failed')))
    with pytest.raises(OSError, match='replace failed'):
        _atomic_write(target, 'complete report')
    assert not target.exists()
    assert not list(tmp_path.glob('.report.md.*'))


def test_semantic_html_has_matching_report_facts(tmp_path: Path) -> None:
    db = _fixture(tmp_path / 'ledger.db')
    markdown, page = render_markdown(read_run('report-verifier:/unsafe', db)), render_html(read_run('report-verifier:/unsafe', db))
    assert '<h1>Crack Contained Verification Report</h1>' in page
    assert page.count('<section>') == 5 and '<article>' in page and '<table>' in page
    assert page.index('<h2>Scope and limitations</h2>') < page.index('<h2>Verified findings</h2>')
    for fact in ('report-verifier:/unsafe', 'finding-1', 'verified', 'reset-a', 'reset-b', 'account_a', 'ledger://event/1', 'cross-account disclosure', 'enforce ownership'):
        assert markdown_text(fact) in markdown and fact in page


@pytest.mark.parametrize('column, value, message', [
    ('reproduction_steps', '[]', 'non-empty list'),
    ('reproduction_steps', '[{"verifier_role":"","snapshot_id":"reset","steps":[{}]}]', 'invalid verifier_role'),
    ('reproduction_steps', '[{"verifier_role":"v","snapshot_id":"reset","steps":[{"account":"a","executed":"yes","method":"GET","proposed_path":"/a","resolved_path":"/a","status_code":200}]}]', 'invalid executed'),
    ('reproduction_steps', '[{"verifier_role":"v","snapshot_id":"reset","steps":[{"account":"a","executed":false,"method":"GET","proposed_path":"/a","resolved_path":"/a","status_code":200}]}]', 'unexecuted step'),
    ('reproduction_steps', '[{"verifier_role":"v","snapshot_id":"reset","steps":[{"account":"a","executed":true,"method":"GET","proposed_path":"/a","resolved_path":"/a","status_code":200},{"account":"b","executed":false,"method":"GET","proposed_path":"/b","resolved_path":"/b","status_code":200}]}]', 'unexecuted step'),
    ('evidence_references', '[]', 'non-empty list of strings'),
    ('evidence_references', '[1]', 'non-empty list of strings'),
])
def test_incomplete_evidence_fails_closed(tmp_path: Path, column: str, value: str, message: str) -> None:
    db = _fixture(tmp_path / 'ledger.db')
    with sqlite3.connect(db) as connection:
        connection.execute(f'UPDATE finding SET {column} = ?', (value,))
    with pytest.raises(ReportIntegrityError, match=message):
        render_markdown(read_run('report-verifier:/unsafe', db))
