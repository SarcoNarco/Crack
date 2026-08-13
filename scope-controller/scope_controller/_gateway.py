"""Fixed capability gateway for Crack's disposable local test environment.

Only the five functions re-exported by :mod:`scope_controller` are public.
There is intentionally no configurable host, token source, command runner, or
generic file/database handle in this module.
"""

from __future__ import annotations

import http.client as _http_client
import importlib.util as _importlib_util
import json as _json
from datetime import UTC as _UTC
from datetime import datetime as _datetime
from pathlib import Path as _Path
import sys as _sys
import threading as _threading
from types import ModuleType as _ModuleType
from typing import Final as _Final
from urllib.parse import urlsplit as _urlsplit

from ledger.init_db import record_event as _record_event


_REPOSITORY_ROOT: _Final = _Path(__file__).resolve().parents[2]
_APP_ROOT: _Final = (_REPOSITORY_ROOT / "app-under-test").resolve(strict=True)
_APP_DATABASE_PATH: _Final = _APP_ROOT / "data" / "demo_app.db"
_LEDGER_DATABASE_PATH: _Final = _REPOSITORY_ROOT / "data" / "ledger.db"
_APP_HOST: _Final = "127.0.0.1"
_APP_PORT: _Final = 8100
_APP_ORIGIN: _Final = f"http://{_APP_HOST}:{_APP_PORT}"
_ALLOWED_METHODS: _Final = frozenset({"GET", "POST", "PUT", "DELETE"})
_ALLOWED_ACCOUNT_TOKENS: _Final = frozenset(
    {"token-account-a-fixed", "token-account-b-fixed"}
)
_SEED_LOCK: _Final = _threading.Lock()


def _contained_source_path(path: str | _Path) -> _Path:
    if not isinstance(path, (str, _Path)):
        raise TypeError("read_source blocked: path must be a string or pathlib.Path")

    candidate = _Path(path)
    if not candidate.is_absolute():
        candidate = _APP_ROOT / candidate

    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(_APP_ROOT)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise PermissionError(
            "read_source blocked: path must resolve to an existing file inside app-under-test"
        ) from exc

    if not resolved.is_file():
        raise PermissionError("read_source blocked: directories and non-files are not readable")
    return resolved


def read_source(path: str | _Path) -> str:
    """Read one UTF-8 source file contained by the fixed app-under-test root."""
    return _contained_source_path(path).read_text(encoding="utf-8")


def query_app_map(*_args: object, **_kwargs: object) -> None:
    """Reserve the app-map capability without providing an implementation yet."""
    raise NotImplementedError(
        "query_app_map is unavailable in Sprint 2; the fixed app-map implementation arrives in Sprint 4"
    )


def _validated_endpoint_path(path: str) -> str:
    if not isinstance(path, str):
        raise TypeError("call_app_endpoint blocked: path must be a string")
    if not path.startswith("/") or path.startswith("//"):
        raise PermissionError(
            f"call_app_endpoint blocked: only paths on fixed origin {_APP_ORIGIN} are allowed"
        )
    if "\\" in path or any(character in path for character in ("\r", "\n", "\x00")):
        raise PermissionError("call_app_endpoint blocked: malformed endpoint path")

    parsed = _urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        raise PermissionError(
            f"call_app_endpoint blocked: only paths on fixed origin {_APP_ORIGIN} are allowed"
        )
    return path


def call_app_endpoint(method: str, path: str, account_token: str) -> dict[str, object]:
    """Call the fixed demo app origin with a seeded identity and allowed verb."""
    if not isinstance(method, str):
        raise TypeError("call_app_endpoint blocked: method must be a string")
    normalized_method = method.upper()
    if normalized_method not in _ALLOWED_METHODS:
        raise PermissionError(
            "call_app_endpoint blocked: method must be one of GET, POST, PUT, DELETE"
        )
    if account_token not in _ALLOWED_ACCOUNT_TOKENS:
        raise PermissionError("call_app_endpoint blocked: account token is not a seeded demo token")

    endpoint_path = _validated_endpoint_path(path)
    connection = _http_client.HTTPConnection(_APP_HOST, _APP_PORT, timeout=5)
    try:
        connection.request(
            normalized_method,
            endpoint_path,
            headers={"Authorization": f"Bearer {account_token}"},
        )
        response = connection.getresponse()
        raw_body = response.read()
        content_type = response.getheader("Content-Type", "")
        if "application/json" in content_type:
            body: object = _json.loads(raw_body.decode("utf-8"))
        else:
            body = raw_body.decode("utf-8", errors="replace")
        return {
            "status_code": response.status,
            "headers": {name.lower(): value for name, value in response.getheaders()},
            "body": body,
        }
    except OSError as exc:
        raise ConnectionError(
            f"call_app_endpoint could not reach fixed local origin {_APP_ORIGIN}: {exc}"
        ) from exc
    finally:
        connection.close()


def _load_fixed_seed_module() -> _ModuleType:
    """Load Sprint 1's seed module with its database path pinned in code."""
    database_source = _APP_ROOT / "app" / "database.py"
    seed_source = _APP_ROOT / "scripts" / "seed.py"

    package_module = _ModuleType("app")
    package_module.__path__ = [str(_APP_ROOT / "app")]

    database_spec = _importlib_util.spec_from_file_location("app.database", database_source)
    if database_spec is None or database_spec.loader is None:
        raise RuntimeError("reset_environment blocked: Sprint 1 database module could not be loaded")
    database_module = _importlib_util.module_from_spec(database_spec)

    previous_app = _sys.modules.get("app")
    previous_database = _sys.modules.get("app.database")
    try:
        _sys.modules["app"] = package_module
        _sys.modules["app.database"] = database_module
        database_spec.loader.exec_module(database_module)
        database_module.database_path = lambda: str(_APP_DATABASE_PATH)

        seed_spec = _importlib_util.spec_from_file_location("_crack_sprint1_seed", seed_source)
        if seed_spec is None or seed_spec.loader is None:
            raise RuntimeError("reset_environment blocked: Sprint 1 seed script could not be loaded")
        seed_module = _importlib_util.module_from_spec(seed_spec)
        seed_spec.loader.exec_module(seed_module)
        return seed_module
    finally:
        if previous_app is None:
            _sys.modules.pop("app", None)
        else:
            _sys.modules["app"] = previous_app
        if previous_database is None:
            _sys.modules.pop("app.database", None)
        else:
            _sys.modules["app.database"] = previous_database


def reset_environment() -> None:
    """Run only the fixed Sprint 1 seed routine against its fixed local database."""
    with _SEED_LOCK:
        seed_module = _load_fixed_seed_module()
        seed_module.seed()


def _required_text(field_name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"record_evidence blocked: {field_name} must be a non-empty string")
    return value


def record_evidence(
    *,
    run_id: str,
    sequence_number: int,
    action_type: str,
    request_response_summary: str,
    artifact_reference: str,
    policy_decision: str,
) -> None:
    """Write exactly one event through the existing ledger persistence module."""
    if not isinstance(sequence_number, int) or isinstance(sequence_number, bool) or sequence_number < 0:
        raise ValueError("record_evidence blocked: sequence_number must be a non-negative integer")

    _record_event(
        run_id=_required_text("run_id", run_id),
        sequence_number=sequence_number,
        action_type=_required_text("action_type", action_type),
        request_response_summary=_required_text(
            "request_response_summary", request_response_summary
        ),
        artifact_reference=_required_text("artifact_reference", artifact_reference),
        policy_decision=_required_text("policy_decision", policy_decision),
        timestamp=_datetime.now(_UTC).isoformat(),
        database_path=_LEDGER_DATABASE_PATH,
    )
