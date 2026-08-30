from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path
from typing import Callable

import pytest

import targets.active as active_target
import targets.architecture as architecture
from targets.active import ActiveTargetError
from targets.architecture import ArchitectureMapError, build_architecture_map, main, write_architecture_map
from targets.inspection import inspect_target
from targets.registry import register_approved


ROOT = Path(__file__).resolve().parents[2]


def _registered_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    mutate: tuple[str, str, str] | None = None,
    rewrite: Callable[[Path], None] | None = None,
) -> tuple[Path, Path]:
    source = tmp_path / "source"
    shutil.copytree(ROOT / "app-under-test", source)
    if mutate is not None:
        relative_path, before, after = mutate
        path = source / relative_path
        content = path.read_text(encoding="utf-8")
        assert before in content
        path.write_text(content.replace(before, after, 1), encoding="utf-8")
    if rewrite is not None:
        rewrite(source)
    plan = inspect_target(source)
    registry = tmp_path / "registry"
    register_approved(source, plan.snapshot_sha256, registry_root=registry)
    monkeypatch.setattr(architecture, "DEFAULT_REGISTRY_ROOT", registry)
    monkeypatch.setattr(
        architecture,
        "ARCHITECTURE_OUTPUT",
        tmp_path / "targets" / "architecture-output" / "architecture.json",
    )
    return source, registry


def test_exact_deterministic_safe_graph_from_approved_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _ = _registered_target(tmp_path, monkeypatch)

    first = build_architecture_map()
    second = build_architecture_map()

    assert first == second
    assert first["schema_version"] == 1
    assert first["target"]["id"] == "crack-school-portal"
    assert [node["id"] for node in first["nodes"]] == [
        "browser-portal",
        "fastapi-api",
        "grade-lifecycle",
        "role-authentication",
        "sqlite-persistence",
        "submissions",
    ]
    assert len(first["edges"]) == 9
    assert [edge["id"] for edge in first["edges"]] == [
        "fastapi-api--serves--browser-portal",
        "fastapi-api--uses--grade-lifecycle",
        "fastapi-api--uses--role-authentication",
        "fastapi-api--uses--submissions",
        "grade-lifecycle--persists--sqlite-persistence",
        "role-authentication--authorizes--grade-lifecycle",
        "role-authentication--authorizes--submissions",
        "submissions--links--grade-lifecycle",
        "submissions--persists--sqlite-persistence",
    ]
    assert all(0.0 <= node["coordinates"][axis] <= 1.0 for node in first["nodes"] for axis in ("x", "y"))
    assert all(node["provenance"] == {"facts": "source-derived", "layout": "presentation-only"} for node in first["nodes"])
    assert all(edge["provenance"] == "source-derived" for edge in first["edges"])
    rendered = json.dumps(first, sort_keys=True)
    for forbidden in (str(source), "token-teacher-fixed", "Student A private reflection.", "Northstar"):
        assert forbidden not in rendered


def test_cli_prints_json_only_and_fixed_write_is_atomic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _registered_target(tmp_path, monkeypatch)

    assert main([]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == build_architecture_map()
    assert main(["--write"]) == 0
    written = json.loads(capsys.readouterr().out)
    assert written == printed
    assert architecture.ARCHITECTURE_OUTPUT.read_bytes() == architecture._json_bytes(printed)
    assert not list(architecture.ARCHITECTURE_OUTPUT.parent.glob(".*.tmp"))


def test_cli_has_no_registry_or_output_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _registered_target(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as error:
        main(["--output", str(tmp_path / "outside.json")])

    assert error.value.code == 2


@pytest.mark.parametrize(
    "mutation",
    [
        ("app/main.py", '@app.get("/health")', '@portal.get("/health")'),
        ("app/database.py", "CREATE TABLE IF NOT EXISTS grades", "CREATE TABLE IF NOT EXISTS grade_records"),
    ],
)
def test_unsupported_ast_or_schema_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: tuple[str, str, str]
) -> None:
    _registered_target(tmp_path, monkeypatch, mutate=mutation)

    with pytest.raises(ArchitectureMapError) as error:
        build_architecture_map()

    assert "approved target" in str(error.value)
    assert mutation[1] not in str(error.value)


def test_swapped_protected_route_role_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _registered_target(
        tmp_path,
        monkeypatch,
        mutate=("app/main.py", '_require_role(person, "student")', '_require_role(person, "teacher")'),
    )

    with pytest.raises(ArchitectureMapError, match="authorization structure"):
        build_architecture_map()


def test_noop_role_helper_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _registered_target(
        tmp_path,
        monkeypatch,
        mutate=(
            "app/main.py",
            '    if person["role"] != role:\n        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Role is not allowed")',
            "    return None",
        ),
    )

    with pytest.raises(ArchitectureMapError, match="authorization structure"):
        build_architecture_map()


def test_dead_bearer_marker_does_not_count_as_authentication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _registered_target(
        tmp_path,
        monkeypatch,
        mutate=("app/main.py", 'if not authorization or not authorization.startswith("Bearer "):', "if False:"),
    )

    with pytest.raises(ArchitectureMapError, match="authorization structure"):
        build_architecture_map()


def test_disabled_review_guard_on_publish_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    guard = """    if grade[\"state\"] != \"reviewed\":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=\"Review required\")
"""
    _registered_target(
        tmp_path,
        monkeypatch,
        mutate=(
            "app/main.py",
            "    with connect() as connection:\n        connection.execute(\"UPDATE grades SET state = 'published' WHERE id = ?\", (grade_id,))",
            guard + "    with connect() as connection:\n        connection.execute(\"UPDATE grades SET state = 'published' WHERE id = ?\", (grade_id,))",
        ),
    )

    with pytest.raises(ArchitectureMapError, match="grade lifecycle"):
        build_architecture_map()


def test_non_conflict_reviewed_guard_on_publish_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    guard = """    if grade[\"state\"] != \"reviewed\":
        raise HTTPException(status_code=400, detail=\"Review required\")
"""
    _registered_target(
        tmp_path,
        monkeypatch,
        mutate=(
            "app/main.py",
            "    with connect() as connection:\n        connection.execute(\"UPDATE grades SET state = 'published' WHERE id = ?\", (grade_id,))",
            guard + "    with connect() as connection:\n        connection.execute(\"UPDATE grades SET state = 'published' WHERE id = ?\", (grade_id,))",
        ),
    )

    with pytest.raises(ArchitectureMapError, match="grade lifecycle"):
        build_architecture_map()


def test_disabled_draft_review_guard_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _registered_target(
        tmp_path,
        monkeypatch,
        mutate=('app/main.py', 'if grade["state"] != "draft":', "if False:"),
    )

    with pytest.raises(ArchitectureMapError, match="grade lifecycle"):
        build_architecture_map()


def test_review_guard_with_pass_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _registered_target(
        tmp_path,
        monkeypatch,
        mutate=(
            "app/main.py",
            '    if grade["state"] != "draft":\n        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft grades can be reviewed")',
            '    if grade["state"] != "draft":\n        pass',
        ),
    )

    with pytest.raises(ArchitectureMapError, match="grade lifecycle"):
        build_architecture_map()


def test_hollow_schema_with_only_references_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def hollow_schema(source: Path) -> None:
        (source / "app" / "database.py").write_text(
            '''import sqlite3
from pathlib import Path


def connect() -> sqlite3.Connection:
    return sqlite3.connect("ignored.db")


def initialize_database() -> None:
    with connect() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS people (teacher_id TEXT REFERENCES people(id));
            CREATE TABLE IF NOT EXISTS classes (teacher_id TEXT REFERENCES people(id));
            CREATE TABLE IF NOT EXISTS assignments (class_id TEXT REFERENCES classes(id));
            CREATE TABLE IF NOT EXISTS submissions (assignment_id TEXT REFERENCES assignments(id), student_id TEXT REFERENCES people(id));
            CREATE TABLE IF NOT EXISTS grades (submission_id TEXT REFERENCES submissions(id), teacher_id TEXT REFERENCES people(id));
        """)
''',
            encoding="utf-8",
        )

    _registered_target(tmp_path, monkeypatch, rewrite=hollow_schema)

    with pytest.raises(ArchitectureMapError, match="persistence structure"):
        build_architecture_map()


def test_active_snapshot_replacement_race_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, registry = _registered_target(tmp_path, monkeypatch)
    original_inspect = active_target.inspect_target

    def replace_after_inspection(snapshot_root: Path) -> object:
        plan = original_inspect(snapshot_root)
        snapshot_root.rename(snapshot_root.with_name("replaced-snapshot"))
        snapshot_root.mkdir()
        return plan

    monkeypatch.setattr(active_target, "inspect_target", replace_after_inspection)

    with pytest.raises(ActiveTargetError, match="changed during validation"):
        active_target.load_active_target(registry)


def test_active_metadata_and_snapshot_tamper_fail_without_leakage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, registry = _registered_target(tmp_path, monkeypatch)
    active_metadata = registry / "active-target.json"
    raw = json.loads(active_metadata.read_text(encoding="utf-8"))
    raw["target_id"] = "wrong-target"
    active_metadata.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ArchitectureMapError) as metadata_error:
        build_architecture_map()
    assert str(metadata_error.value) == "active approved target is unavailable"

    _, registry = _registered_target(tmp_path / "changed", monkeypatch)
    active = json.loads((registry / "active-target.json").read_text(encoding="utf-8"))
    snapshot_main = registry / active["snapshot_directory"] / "app" / "main.py"
    secret = "unapproved-source-change-not-for-output"
    snapshot_main.write_text(snapshot_main.read_text(encoding="utf-8") + f"\n# {secret}\n", encoding="utf-8")
    with pytest.raises(ArchitectureMapError) as snapshot_error:
        build_architecture_map()
    assert secret not in str(snapshot_error.value)


def test_symlinked_active_metadata_and_output_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, registry = _registered_target(tmp_path, monkeypatch)
    active = registry / "active-target.json"
    saved = registry / "saved-active.json"
    active.rename(saved)
    active.symlink_to(saved)

    with pytest.raises(ArchitectureMapError, match="active approved target is unavailable"):
        build_architecture_map()

    _, registry = _registered_target(tmp_path / "snapshot", monkeypatch)
    metadata = json.loads((registry / "active-target.json").read_text(encoding="utf-8"))
    snapshot = registry / metadata["snapshot_directory"]
    saved_snapshot = registry / "saved-snapshot"
    snapshot.rename(saved_snapshot)
    snapshot.symlink_to(saved_snapshot, target_is_directory=True)
    with pytest.raises(ArchitectureMapError, match="active approved target is unavailable"):
        build_architecture_map()

    _registered_target(tmp_path / "output", monkeypatch)
    architecture.ARCHITECTURE_OUTPUT.parent.mkdir(parents=True)
    replacement = tmp_path / "replacement.json"
    replacement.write_text("outside", encoding="utf-8")
    architecture.ARCHITECTURE_OUTPUT.symlink_to(replacement)
    with pytest.raises(ArchitectureMapError, match="output path is unsafe"):
        write_architecture_map()
    assert replacement.read_text(encoding="utf-8") == "outside"


def test_atomic_write_preserves_complete_previous_file_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _registered_target(tmp_path, monkeypatch)
    output = architecture.ARCHITECTURE_OUTPUT
    output.parent.mkdir(parents=True)
    output.write_bytes(b"complete-previous-map\n")
    monkeypatch.setattr(
        architecture.os,
        "replace",
        lambda *_, **__: (_ for _ in ()).throw(OSError("replace failed")),
    )

    with pytest.raises(ArchitectureMapError, match="output cannot be written"):
        write_architecture_map()

    assert output.read_bytes() == b"complete-previous-map\n"
    assert not list(output.parent.glob(".*.tmp"))


def test_architecture_module_has_no_execution_network_provider_or_ledger_boundary() -> None:
    source = (ROOT / "targets" / "architecture.py").read_text(encoding="utf-8")
    parsed = ast.parse(source)
    imports: set[str] = set()
    for node in ast.walk(parsed):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])

    assert not imports & {"subprocess", "socket", "http", "requests", "httpx", "urllib", "docker", "openai", "sqlite3"}
    assert "targets.runtime" not in source
    assert "scope_controller" not in source
    assert "ledger" not in source
    assert "architecture" not in (ROOT / "targets" / "runtime.py").read_text(encoding="utf-8")


def test_output_directory_is_ignored() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "/targets/architecture-output/" in ignored
