from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import stat

import pytest

from targets.add import main
from targets.inspection import ImportLimits, TargetImportError, inspect_target
from targets.manifest import FIXED_COMPOSE_CONTENT
from targets.registry import Registration, register_approved
import targets.registry as registry_module


ROOT = Path(__file__).resolve().parents[2]


def _manifest(**changes: object) -> dict[str, object]:
    manifest: dict[str, object] = {
        "schema_version": 1,
        "target_id": "crack-school-portal",
        "runtime": "docker-compose",
        "compose_file": "docker-compose.yml",
        "service": "app-under-test",
        "internal_port": 8100,
        "health_path": "/health",
        "reset_profile": "school-portal-v1",
    }
    manifest.update(changes)
    return manifest


def _target(tmp_path: Path, **manifest_changes: object) -> Path:
    source = tmp_path / "target"
    source.mkdir(parents=True)
    (source / "crack-target.json").write_text(
        json.dumps(_manifest(**manifest_changes)), encoding="utf-8"
    )
    (source / "docker-compose.yml").write_bytes(FIXED_COMPOSE_CONTENT)
    (source / "app.py").write_text("print('synthetic')\n", encoding="utf-8")
    return source


def test_canonical_app_plan_and_hash_bound_registration(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = ROOT / "app-under-test"
    plan = inspect_target(source)

    assert main([str(source)]) == 0
    plan_output = capsys.readouterr().out
    assert f"snapshot_sha256={plan.snapshot_sha256}" in plan_output
    assert "token-student" not in plan_output

    registry = tmp_path / "registry"
    result = register_approved(source, plan.snapshot_sha256, registry_root=registry)

    assert result.snapshot_sha256 == plan.snapshot_sha256
    assert (registry / "snapshots" / plan.snapshot_sha256 / "app" / "main.py").is_file()
    active = json.loads((registry / "active-target.json").read_text(encoding="utf-8"))
    assert active["snapshot_sha256"] == plan.snapshot_sha256
    assert str(source) not in json.dumps(active)


def test_cli_approval_uses_fixed_registry_and_safe_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _target(tmp_path)
    planned = inspect_target(source)
    registered: dict[str, object] = {}

    def register_at_fixed_root(actual_source: Path, approved_sha256: str) -> Registration:
        registered["source"] = actual_source
        registered["sha256"] = approved_sha256
        return Registration(
            snapshot_sha256=approved_sha256,
            target_id="crack-school-portal",
            file_count=planned.file_count,
            total_bytes=planned.total_bytes,
            reused_snapshot=False,
        )

    monkeypatch.setattr("targets.add.register_approved", register_at_fixed_root)
    assert main([str(source), "--approve-sha256", planned.snapshot_sha256]) == 0

    output = capsys.readouterr().out
    assert registered == {"source": source, "sha256": planned.snapshot_sha256}
    assert f"snapshot_sha256={planned.snapshot_sha256}" in output
    assert str(source) not in output
    assert "synthetic" not in output


def test_cli_has_no_generic_yes_bypass(tmp_path: Path) -> None:
    source = _target(tmp_path)

    with pytest.raises(SystemExit) as error:
        main([str(source), "--yes"])

    assert error.value.code == 2


def test_cli_rejects_registry_root_override(tmp_path: Path) -> None:
    source = _target(tmp_path)

    with pytest.raises(SystemExit) as error:
        main([str(source), "--registry-root", str(tmp_path / "registry")])

    assert error.value.code == 2


def test_hash_is_deterministic_and_reregistration_is_idempotent(tmp_path: Path) -> None:
    source = _target(tmp_path)
    first_plan = inspect_target(source)
    second_plan = inspect_target(source)
    registry = tmp_path / "registry"

    first = register_approved(source, first_plan.snapshot_sha256, registry_root=registry)
    first_metadata = (registry / "active-target.json").read_bytes()
    second = register_approved(source, second_plan.snapshot_sha256, registry_root=registry)

    assert first_plan.snapshot_sha256 == second_plan.snapshot_sha256
    assert not first.reused_snapshot
    assert second.reused_snapshot
    assert (registry / "active-target.json").read_bytes() == first_metadata


def test_mutation_after_plan_cannot_activate(tmp_path: Path) -> None:
    source = _target(tmp_path)
    planned = inspect_target(source)
    (source / "app.py").write_text("print('changed')\n", encoding="utf-8")

    with pytest.raises(TargetImportError, match="does not match approval"):
        register_approved(source, planned.snapshot_sha256, registry_root=tmp_path / "registry")

    assert not (tmp_path / "registry" / "active-target.json").exists()


def test_extra_compose_service_or_runtime_setting_is_rejected(tmp_path: Path) -> None:
    source = _target(tmp_path)
    (source / "docker-compose.yml").write_text(
        "services:\n  app-under-test:\n    build: .\n    command: not-allowed\n", encoding="utf-8"
    )

    with pytest.raises(TargetImportError, match="compose descriptor"):
        inspect_target(source)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"unexpected": "value"}, "fields"),
        ({"runtime": "shell"}, "runtime"),
        ({"compose_file": "../docker-compose.yml"}, "compose_file"),
        ({"service": "other-service"}, "service"),
        ({"internal_port": 9000}, "internal_port"),
        ({"health_path": "https://outside.example/health"}, "health_path"),
    ],
)
def test_manifest_rejects_unknown_and_nonfixed_values(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    with pytest.raises(TargetImportError, match=message):
        inspect_target(_target(tmp_path, **changes))


def test_root_and_nested_symlinks_are_rejected(tmp_path: Path) -> None:
    source = _target(tmp_path)
    linked_file = source / "linked.py"
    linked_file.symlink_to(source / "app.py")
    with pytest.raises(TargetImportError, match="symlink"):
        inspect_target(source)

    source = _target(tmp_path / "second")
    linked_directory = source / "linked-directory"
    linked_directory.symlink_to(source, target_is_directory=True)
    with pytest.raises(TargetImportError, match="symlink"):
        inspect_target(source)

    root_link = tmp_path / "target-link"
    root_link.symlink_to(source, target_is_directory=True)
    with pytest.raises(TargetImportError, match="symlink"):
        inspect_target(root_link)


def test_case_and_unicode_normalization_collisions_are_rejected_when_supported(tmp_path: Path) -> None:
    source = _target(tmp_path)
    (source / "CASE.py").write_text("first", encoding="utf-8")
    (source / "case.py").write_text("second", encoding="utf-8")
    case_names = [name for name in os.listdir(source) if name.casefold() == "case.py"]
    if len(case_names) == 2:
        with pytest.raises(TargetImportError, match="ambiguous"):
            inspect_target(source)

    source = _target(tmp_path / "unicode")
    (source / "é.txt").write_text("first", encoding="utf-8")
    (source / "e\u0301.txt").write_text("second", encoding="utf-8")
    normalized_names = [name for name in os.listdir(source) if name.casefold() == "é.txt"]
    if len(normalized_names) == 2:
        with pytest.raises(TargetImportError, match="ambiguous"):
            inspect_target(source)


@pytest.mark.parametrize("name", [".env.local", "id_ed25519", "credentials.json", "portal.sqlite3"])
def test_secret_and_database_filenames_are_rejected(tmp_path: Path, name: str) -> None:
    source = _target(tmp_path)
    (source / name).write_text("safe placeholder", encoding="utf-8")

    with pytest.raises(TargetImportError, match="secret-bearing or database"):
        inspect_target(source)


def test_credential_like_content_is_rejected_without_echoing_value(tmp_path: Path) -> None:
    source = _target(tmp_path)
    secret = "not-for-output-value"
    (source / "settings.txt").write_text(f"API_KEY={secret}\n", encoding="utf-8")

    with pytest.raises(TargetImportError) as error:
        inspect_target(source)

    assert "credential-like" in str(error.value)
    assert secret not in str(error.value)


def test_unreadable_file_is_rejected(tmp_path: Path) -> None:
    source = _target(tmp_path)
    unreadable = source / "app.py"
    original_mode = stat.S_IMODE(unreadable.stat().st_mode)
    unreadable.chmod(0)
    try:
        with pytest.raises(TargetImportError, match="cannot be read safely"):
            inspect_target(source)
    finally:
        unreadable.chmod(original_mode)


def test_special_file_is_rejected_when_fifo_is_supported(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("platform has no FIFO support")
    source = _target(tmp_path)
    fifo = source / "source.fifo"
    os.mkfifo(fifo)
    try:
        with pytest.raises(TargetImportError, match="non-regular"):
            inspect_target(source)
    finally:
        fifo.unlink(missing_ok=True)


def test_file_and_byte_caps_fail_closed(tmp_path: Path) -> None:
    source = _target(tmp_path)
    with pytest.raises(TargetImportError, match="file cap"):
        inspect_target(source, limits=ImportLimits(max_files=2, max_total_bytes=1024, max_file_bytes=1024))

    with pytest.raises(TargetImportError, match="total byte cap"):
        inspect_target(source, limits=ImportLimits(max_files=10, max_total_bytes=4, max_file_bytes=1024))

    with pytest.raises(TargetImportError, match="per-file byte cap"):
        inspect_target(source, limits=ImportLimits(max_files=10, max_total_bytes=1024, max_file_bytes=4))


def test_fixed_generated_directories_are_excluded_from_hash_and_snapshot(tmp_path: Path) -> None:
    source = _target(tmp_path)
    generated = source / "node_modules"
    generated.mkdir()
    (generated / ".env").write_text("API_KEY=excluded-generated-value", encoding="utf-8")
    (generated / "large.js").write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    registry = tmp_path / "registry"
    plan = inspect_target(source)

    register_approved(source, plan.snapshot_sha256, registry_root=registry)

    snapshot = registry / "snapshots" / plan.snapshot_sha256
    assert not (snapshot / "node_modules").exists()


def test_casefolded_fixed_generated_directory_is_excluded(tmp_path: Path) -> None:
    source = _target(tmp_path)
    generated = source / "NODE_MODULES"
    generated.mkdir()
    (generated / ".env").write_text("API_KEY=excluded-generated-value", encoding="utf-8")

    assert inspect_target(source).file_count == 3


def test_directory_replacement_during_descriptor_walk_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _target(tmp_path)
    nested = source / "nested"
    nested.mkdir()
    (nested / "module.py").write_text("safe", encoding="utf-8")
    original = __import__("targets.inspection", fromlist=["_open_directory_at"])._open_directory_at

    def replace_directory(parent_fd: int, component: str, expected_stat: os.stat_result) -> int:
        if component == "nested":
            nested.rename(source / "nested-replaced")
            nested.mkdir()
        return original(parent_fd, component, expected_stat)

    monkeypatch.setattr("targets.inspection._open_directory_at", replace_directory)
    with pytest.raises(TargetImportError, match="changed"):
        inspect_target(source)


def test_failed_copy_cleans_staging_and_never_writes_active_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _target(tmp_path)
    plan = inspect_target(source)
    registry = tmp_path / "registry"

    def fail_copy(*_: object) -> None:
        raise TargetImportError("forced copy failure")

    monkeypatch.setattr(registry_module, "_copy_regular_file", fail_copy)
    with pytest.raises(TargetImportError, match="forced copy failure"):
        register_approved(source, plan.snapshot_sha256, registry_root=registry)

    assert not (registry / "active-target.json").exists()
    assert not list(registry.glob(".staging-*"))
    assert not (registry / "snapshots" / plan.snapshot_sha256).exists()


def test_source_and_registry_cannot_overlap_and_source_must_be_absolute(tmp_path: Path) -> None:
    source = _target(tmp_path)
    plan = inspect_target(source)
    nested_registry = source / "registry"
    with pytest.raises(TargetImportError, match="overlap"):
        register_approved(source, plan.snapshot_sha256, registry_root=nested_registry)
    assert not nested_registry.exists()
    with pytest.raises(TargetImportError, match="absolute"):
        inspect_target(Path("relative-target"))


def test_overlap_rejects_symlink_aliases_without_creating_nested_registry(tmp_path: Path) -> None:
    source = _target(tmp_path)
    nested_registry = source / "registry"
    alias_parent = tmp_path / "source-parent-alias"
    alias_parent.symlink_to(tmp_path, target_is_directory=True)
    aliased_source = alias_parent / source.name
    plan = inspect_target(aliased_source)

    with pytest.raises(TargetImportError, match="overlap"):
        register_approved(aliased_source, plan.snapshot_sha256, registry_root=nested_registry)
    assert not nested_registry.exists()

    registry_alias = tmp_path / "registry-alias"
    registry_alias.symlink_to(nested_registry, target_is_directory=True)
    direct_plan = inspect_target(source)
    with pytest.raises(TargetImportError, match="overlap"):
        register_approved(source, direct_plan.snapshot_sha256, registry_root=registry_alias)
    assert not nested_registry.exists()


def test_registry_parent_component_symlink_is_rejected_before_write(tmp_path: Path) -> None:
    source = _target(tmp_path)
    plan = inspect_target(source)
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    symlink_parent = tmp_path / "symlink-parent"
    symlink_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(TargetImportError, match="registry directory is not safe"):
        register_approved(source, plan.snapshot_sha256, registry_root=symlink_parent / "registry")

    assert not (real_parent / "registry").exists()

def test_importer_has_no_execution_network_or_provider_imports() -> None:
    forbidden = {"subprocess", "socket", "requests", "httpx", "urllib", "docker", "openai", "tarfile", "zipfile"}
    imported: set[str] = set()
    for path in (
        ROOT / "targets" / "__init__.py",
        ROOT / "targets" / "add.py",
        ROOT / "targets" / "inspection.py",
        ROOT / "targets" / "manifest.py",
        ROOT / "targets" / "registry.py",
    ):
        module = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(module):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

    assert not imported & forbidden


def test_registry_path_is_ignored() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "/targets/registry/" in ignored
