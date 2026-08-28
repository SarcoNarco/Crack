from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

import pytest

from ledger.init_db import initialize_database
from ledger.read_view import read_run
from reports.generate import ReportIntegrityError, _atomic_write, generate, main, markdown_text, render_html, render_markdown, report_paths, safe_text


def _fixture(path: Path, *, hostile: bool = False) -> Path:
    initialize_database(path)
    claim = '<img src=x onerror=alert(1)>\n# not-a-heading' if hostile else 'Account A can read Account B record'
    state_hash = 'abcdef0123456789'
    reset_a = f'reset:fixture-a:state-sha256:{state_hash}'
    reset_b = f'reset:fixture-b:state-sha256:{state_hash}'
    with sqlite3.connect(path) as db:
        db.executemany('INSERT INTO run VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', [
            ('old-verifier', 'v0', 'reset-old', 'verifier', 'GET only', 's0', 'e0', 1, 2, 'completed'),
            ('report-verifier:/unsafe', 'v1', json.dumps([reset_a, reset_b]), 'verifier', 'local GET-only', 's1', 'e1', 30, 60, 'completed'),
            ('newer-failed-verifier', 'v2', 'reset-failed', 'verifier', 'GET only', 's2', 'e2', 3, 4, 'failed'),
            ('newer-identity', 'v2', 'reset-new', 'identity', 'normal flow', 's2', 'e2', 3, 4, 'completed'),
        ])
        db.executemany('INSERT INTO hypothesis VALUES (?, ?, ?, ?, ?, ?, ?)', [
            ('verified', 'submitted', 'record owner must match authenticated account', claim, 'Account B ID then Account A 200', 'verified', 'report-verifier:/unsafe'),
            ('unverified', 'submitted', 'other rule', 'Not yet reproduced', 'Expected evidence', 'unverified', 'report-verifier:/unsafe'),
            ('inconclusive', 'submitted', 'third rule', 'Needs review', 'Expected evidence', 'inconclusive', 'report-verifier:/unsafe'),
        ])
        attempts = [
            {'verifier_role': 'verifier_a', 'snapshot_id': reset_a, 'steps': [
                {'account': 'account_b', 'executed': True, 'method': 'GET', 'proposed_path': '/records/mine', 'resolved_path': '/records/mine', 'status_code': 200},
                {'account': 'account_a', 'executed': True, 'method': 'GET', 'proposed_path': '/records/{record_id}', 'resolved_path': '/records/note-b', 'status_code': 200},
            ]},
            {'verifier_role': 'verifier_b', 'snapshot_id': reset_b, 'steps': [
                {'account': 'account_b', 'executed': True, 'method': 'GET', 'proposed_path': '/records/mine', 'resolved_path': '/records/mine', 'status_code': 200},
                {'account': 'account_a', 'executed': True, 'method': 'GET', 'proposed_path': '/records/note-b', 'resolved_path': '/records/note-b', 'status_code': 200},
            ]},
        ]
        steps = json.dumps(attempts, separators=(',', ':'))
        db.execute('INSERT INTO finding VALUES (?, ?, ?, ?, ?, ?)', ('finding-1', 'verified', 'cross-account disclosure', steps, '["ledger://event/1", "ledger://event/2"]', 'enforce ownership'))
        events: list[tuple[object, ...]] = []
        sequence = 0
        for attempt in attempts:
            role, snapshot = attempt['verifier_role'], attempt['snapshot_id']
            reset_payload = {'snapshot_id': snapshot, 'verifier_role': role}
            events.append(('report-verifier:/unsafe', sequence, 'verifier_environment_reset', json.dumps(reset_payload), f'reset://{role}', 'allowed', f't{sequence}'))
            sequence += 1
            plan_steps = [
                {'account': step['account'], 'method': step['method'], 'path': step['proposed_path']}
                for step in attempt['steps']
            ]
            plan_payload = {'plan_sha256': f'plan-{role}', 'snapshot_id': snapshot, 'step_count': len(plan_steps), 'steps': plan_steps, 'verifier_role': role}
            events.append(('report-verifier:/unsafe', sequence, 'verifier_plan_proposed', json.dumps(plan_payload), f'plan://{role}', 'allowed', f't{sequence}'))
            sequence += 1
            for step_index, step in enumerate(attempt['steps'], 1):
                payload = dict(step)
                payload.update({'snapshot_id': snapshot, 'step_index': step_index, 'verifier_role': role, 'response': {'status_code': step['status_code']}})
                events.append(('report-verifier:/unsafe', sequence, 'verifier_call_result', json.dumps(payload), f'call://{role}/{step_index}', 'allowed', f't{sequence}'))
                sequence += 1
            check = {'reason': 'Account A received the exact record previously discovered as owned by Account B', 'satisfied': True, 'snapshot_id': snapshot, 'verifier_role': role}
            events.append(('report-verifier:/unsafe', sequence, 'verifier_deterministic_check', json.dumps(check), f'check://{role}', 'allowed', f't{sequence}'))
            sequence += 1
        verdict = {'hypothesis_id': 'verified', 'verdict': 'verified', 'verifier_a_satisfied': True, 'verifier_b_satisfied': True}
        events.extend([
            ('report-verifier:/unsafe', sequence, 'verifier_final_verdict', json.dumps(verdict), 'verdict://verified', 'allowed', f't{sequence}'),
            ('report-verifier:/unsafe', sequence + 2, 'later', 'summary two', 'event://2', 'allowed', 't-later'),
            ('report-verifier:/unsafe', sequence + 1, 'first', 'summary one', 'event://1', 'allowed', 't-first'),
        ])
        db.executemany('INSERT INTO event VALUES (?, ?, ?, ?, ?, ?, ?)', events)
    return path


def test_latest_is_verifier_and_generates_both_formats(tmp_path: Path) -> None:
    db, output = _fixture(tmp_path / 'ledger.db'), tmp_path / 'output'
    assert main(['--latest'], database_path=db, output_path=output) == 0
    md, page = report_paths('report-verifier:/unsafe', output)
    assert md.is_file() and page.is_file()
    text = md.read_text()
    assert text.index('## Scope and limitations') < text.index('## Verified findings')
    assert 'Verified findings: 1' in text and 'Unverified hypotheses: 1' in text and 'Inconclusive hypotheses: 1' in text
    assert r'reset:fixture\-a' in text and r'reset:fixture\-b' in text and r'Synthetic role: account\_a' in text
    assert 'Not yet reproduced' in text and '### Hypothesis `unverified`' in text
    assert page.read_text().startswith('<!doctype html>')
    assert main(['--run-id', 'old-verifier'], database_path=db, output_path=output) == 0
    explicit_markdown, explicit_page = report_paths('old-verifier', output)
    assert explicit_markdown.is_file() and explicit_page.is_file()


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


def test_authorization_only_report_rejects_workflow_evidence_without_misreporting(tmp_path: Path) -> None:
    db = _fixture(tmp_path / 'ledger.db')
    with sqlite3.connect(db) as connection:
        connection.execute(
            "UPDATE hypothesis SET affected_app_rule = 'WORKFLOW: approval is required before publishing a work item' "
            "WHERE id = 'verified'"
        )

    with pytest.raises(ReportIntegrityError, match='authorization-only report'):
        render_html(read_run('report-verifier:/unsafe', db))


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
    assert '<h1 id="outcome-heading" class="outcome-title">Account A could read Account B\'s record.</h1>' in page
    headings = ('Expected vs actual', 'How the failure happened', 'Why it matters and how to fix it', 'Why the evidence is trustworthy', 'Safe reproduction steps', 'Technical terms explained', 'Scope and limitations', 'Technical evidence timeline', 'Report integrity and run metadata')
    assert all(f'>{heading}<' in page for heading in headings)
    assert page.index('id="outcome-heading"') < page.index('id="story-heading"') < page.index('id="findings-heading"')
    assert page.count('id="verification-state"') == 1 and 'Evidence-backed finding' in page
    assert 'Account A must not be able to retrieve Account B\'s record.' in page
    assert 'Account A received Account B\'s exact record with HTTP 200.' in page
    assert page.count('class="reproduction-call"') == 4
    assert '>Independent check 1<' in page and '>Independent check 2<' in page
    assert 'Verifier A · sequential logical role' in page and 'Verifier B · sequential logical role' in page
    assert 'Fresh test environment' in page and 'Same starting data' in page
    assert 'Rule-based evidence check passed' in page and 'Final decision made by ordinary code' in page
    assert 'Why this is a real problem' in page and 'How to fix it' in page
    assert 'neither check receives the other\'s plan or result' in page
    assert 'not parallel services or spawned background processes' in page
    assert all(f'>{term}<' in page for term in ('Verifier', 'Fresh reset', 'Shared state hash', 'Deterministic / code-owned check', 'Verified finding'))
    assert all(f'>{label}<' in page for label in ('Finding ID', 'Hypothesis ID', 'Recorded claim', 'Intended rule', 'Expected evidence', 'Recorded impact'))
    for fact in ('report-verifier:/unsafe', 'finding-1', 'verified', 'reset:fixture-a', 'reset:fixture-b', 'abcdef0123456789', 'ledger://event/1', 'cross-account disclosure', 'enforce ownership'):
        assert markdown_text(fact) in markdown and fact in page


def test_html_is_static_accessible_printable_and_has_no_fabricated_score(tmp_path: Path) -> None:
    page = render_html(read_run('report-verifier:/unsafe', _fixture(tmp_path / 'ledger.db')))
    assert '<script' not in page.lower() and 'javascript:' not in page.lower()
    assert not re.search(r'(?:src|href)=["\'][^"\']+["\']', page, re.IGNORECASE)
    assert 'https://' not in page and 'http://' not in page and '@import' not in page
    assert 'CVSS' not in page and 'severity score' not in page.lower()
    assert 'summary:focus-visible' in page and 'prefers-reduced-motion' in page
    assert '@media print' in page and 'details > :not(summary)' in page
    assert 'meta name="viewport"' in page and 'overflow-x: auto' in page


def test_html_fails_closed_when_verification_overview_is_incomplete(tmp_path: Path) -> None:
    db = _fixture(tmp_path / 'ledger.db')
    with sqlite3.connect(db) as connection:
        connection.execute("DELETE FROM event WHERE action_type = 'verifier_deterministic_check' AND request_response_summary LIKE '%verifier_b%'")
    with pytest.raises(ReportIntegrityError, match='deterministic check'):
        render_html(read_run('report-verifier:/unsafe', db))


def test_outcome_status_is_derived_and_ownership_rule_is_required(tmp_path: Path) -> None:
    db = _fixture(tmp_path / 'ledger.db')
    with sqlite3.connect(db) as connection:
        raw_steps = connection.execute("SELECT reproduction_steps FROM finding WHERE id = 'finding-1'").fetchone()[0]
        attempts = json.loads(raw_steps)
        for attempt in attempts:
            attempt['steps'][-1]['status_code'] = 201
        connection.execute("UPDATE finding SET reproduction_steps = ? WHERE id = 'finding-1'", (json.dumps(attempts),))
        call_rows = connection.execute("SELECT rowid, request_response_summary FROM event WHERE action_type = 'verifier_call_result'").fetchall()
        for rowid, raw_payload in call_rows:
            payload = json.loads(raw_payload)
            if payload['account'] == 'account_a':
                payload['response']['status_code'] = 201
                connection.execute("UPDATE event SET request_response_summary = ? WHERE rowid = ?", (json.dumps(payload), rowid))
    page = render_html(read_run('report-verifier:/unsafe', db))
    assert "Account A received Account B's exact record with HTTP 201." in page

    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE hypothesis SET affected_app_rule = 'GET route should return a record' WHERE id = 'verified'")
    with pytest.raises(ReportIntegrityError, match='ownership rule'):
        render_html(read_run('report-verifier:/unsafe', db))


def test_html_fails_closed_without_separate_plan_evidence(tmp_path: Path) -> None:
    db = _fixture(tmp_path / 'ledger.db')
    with sqlite3.connect(db) as connection:
        connection.execute("DELETE FROM event WHERE action_type = 'verifier_plan_proposed' AND request_response_summary LIKE '%verifier_b%'")
    with pytest.raises(ReportIntegrityError, match='isolated-plan evidence'):
        render_html(read_run('report-verifier:/unsafe', db))


def test_school_portal_role_evidence_renders_the_cross_student_narrative(tmp_path: Path) -> None:
    db = _fixture(tmp_path / 'ledger.db')

    def school_path(value: str) -> str:
        if value == '/records/mine':
            return '/submissions/mine'
        if value == '/records/{record_id}':
            return '/submissions/{submission_id}/grade'
        return '/submissions/submission-student-b-001/grade'

    with sqlite3.connect(db) as connection:
        connection.execute(
            "UPDATE hypothesis SET affected_app_rule = ?, concise_claim = ? WHERE id = 'verified'",
            ('GET /submissions/{submission_id}/grade must enforce student ownership', 'Student A can read Student B submission detail'),
        )
        raw = connection.execute("SELECT reproduction_steps FROM finding WHERE id = 'finding-1'").fetchone()[0]
        attempts = json.loads(raw)
        for attempt in attempts:
            for step in attempt['steps']:
                step['role'] = 'student_b' if step.pop('account') == 'account_b' else 'student_a'
                step['proposed_path'] = school_path(step['proposed_path'])
                step['resolved_path'] = school_path(step['resolved_path'])
        connection.execute("UPDATE finding SET reproduction_steps = ? WHERE id = 'finding-1'", (json.dumps(attempts),))
        rows = connection.execute("SELECT rowid, action_type, request_response_summary FROM event").fetchall()
        for rowid, action_type, raw_payload in rows:
            if action_type not in {'verifier_plan_proposed', 'verifier_call_result'}:
                continue
            payload = json.loads(raw_payload)
            if action_type == 'verifier_plan_proposed':
                for step in payload['steps']:
                    step['role'] = 'student_b' if step.pop('account') == 'account_b' else 'student_a'
                    step['path'] = school_path(step['path'])
            else:
                payload['role'] = 'student_b' if payload.pop('account') == 'account_b' else 'student_a'
                payload['proposed_path'] = school_path(payload['proposed_path'])
                payload['resolved_path'] = school_path(payload['resolved_path'])
            connection.execute("UPDATE event SET request_response_summary = ? WHERE rowid = ?", (json.dumps(payload), rowid))

    page = render_html(read_run('report-verifier:/unsafe', db))
    assert "Student A could read Student B's submission and grade detail." in page
    assert 'Student B discovers their own submission' in page
    assert 'submission-student-b-001' in page


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
