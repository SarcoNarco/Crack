"""Deterministic, read-only architecture map for Crack's approved school portal."""

from __future__ import annotations

import argparse
import ast
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from uuid import uuid4

from .active import ActiveTarget, ActiveTargetError, load_active_target, read_active_file
from .inspection import TargetImportError
from .registry import DEFAULT_REGISTRY_ROOT, _open_absolute_directory_chain


_ROOT: Final = Path(__file__).resolve().parents[1]
ARCHITECTURE_OUTPUT: Final = _ROOT / "targets" / "architecture-output" / "architecture.json"
SCHEMA_VERSION: Final = 1
_SOURCE_PROVENANCE: Final = "source-derived"
_LAYOUT_PROVENANCE: Final = "presentation-only"
_EXPECTED_FILES: Final = frozenset(
    {
        "app/main.py",
        "app/database.py",
        "app/static/index.html",
        "app/static/portal.css",
        "app/static/portal.js",
    }
)
_EXPECTED_ROUTES: Final = {
    ("GET", "/"): "portal_home",
    ("GET", "/health"): "health",
    ("GET", "/submissions/mine"): "get_my_submissions",
    ("GET", "/submissions/{submission_id}/grade"): "get_submission_grade",
    ("GET", "/grades/mine"): "get_my_grades",
    ("POST", "/grades/{grade_id}/review"): "review_grade",
    ("POST", "/grades/{grade_id}/publish"): "publish_grade",
}
_PROTECTED_ROUTES: Final = frozenset(
    {
        ("GET", "/submissions/mine"),
        ("GET", "/submissions/{submission_id}/grade"),
        ("GET", "/grades/mine"),
        ("POST", "/grades/{grade_id}/review"),
        ("POST", "/grades/{grade_id}/publish"),
    }
)
_EXPECTED_ROLE_BY_ROUTE: Final = {
    ("GET", "/submissions/mine"): "student",
    ("GET", "/submissions/{submission_id}/grade"): "student",
    ("GET", "/grades/mine"): "teacher",
    ("POST", "/grades/{grade_id}/review"): "teacher",
    ("POST", "/grades/{grade_id}/publish"): "teacher",
}
_EXPECTED_TABLES: Final = ("PEOPLE", "CLASSES", "ASSIGNMENTS", "SUBMISSIONS", "GRADES")
_EXPECTED_SCHEMA: Final = {
    "PEOPLE": (
        "ID", "TEXT", "PRIMARY", "KEY", ",", "ROLE", "TEXT", "NOT", "NULL", "CHECK", "(",
        "ROLE", "IN", "(", "STRING:TEACHER", ",", "STRING:STUDENT", ")", ")", ",", "TOKEN",
        "TEXT", "NOT", "NULL", "UNIQUE", ",", "DISPLAY_NAME", "TEXT", "NOT", "NULL",
    ),
    "CLASSES": (
        "ID", "TEXT", "PRIMARY", "KEY", ",", "TEACHER_ID", "TEXT", "NOT", "NULL", "REFERENCES",
        "PEOPLE", "(", "ID", ")", ",", "TITLE", "TEXT", "NOT", "NULL",
    ),
    "ASSIGNMENTS": (
        "ID", "TEXT", "PRIMARY", "KEY", ",", "CLASS_ID", "TEXT", "NOT", "NULL", "REFERENCES",
        "CLASSES", "(", "ID", ")", ",", "TITLE", "TEXT", "NOT", "NULL",
    ),
    "SUBMISSIONS": (
        "ID", "TEXT", "PRIMARY", "KEY", ",", "ASSIGNMENT_ID", "TEXT", "NOT", "NULL", "REFERENCES",
        "ASSIGNMENTS", "(", "ID", ")", ",", "STUDENT_ID", "TEXT", "NOT", "NULL", "REFERENCES",
        "PEOPLE", "(", "ID", ")", ",", "BODY", "TEXT", "NOT", "NULL",
    ),
    "GRADES": (
        "ID", "TEXT", "PRIMARY", "KEY", ",", "SUBMISSION_ID", "TEXT", "NOT", "NULL", "UNIQUE",
        "REFERENCES", "SUBMISSIONS", "(", "ID", ")", ",", "TEACHER_ID", "TEXT", "NOT", "NULL",
        "REFERENCES", "PEOPLE", "(", "ID", ")", ",", "FEEDBACK", "TEXT", "NOT", "NULL", ",",
        "STATE", "TEXT", "NOT", "NULL", "CHECK", "(", "STATE", "IN", "(", "STRING:DRAFT", ",",
        "STRING:REVIEWED", ",", "STRING:PUBLISHED", ")", ")",
    ),
}
_ALLOWED_NODE_TYPES: Final = frozenset({"interface", "service", "boundary", "domain", "persistence"})
_ALLOWED_LAYERS: Final = frozenset({"presentation", "application", "security", "domain", "data"})
_NODE_IDS: Final = (
    "browser-portal",
    "fastapi-api",
    "grade-lifecycle",
    "role-authentication",
    "sqlite-persistence",
    "submissions",
)


class ArchitectureMapError(ValueError):
    """Safe failure for unsupported or changed approved architecture state."""


@dataclass(frozen=True)
class _ArchitectureFacts:
    """Only source-derived structural facts required by the fixed graph."""

    route_count: int
    protected_route_count: int
    table_names: tuple[str, ...]


def build_architecture_map() -> dict[str, object]:
    """Build one graph after fail-closed snapshot and source validation."""
    active = _load_active_target()
    facts = _extract_facts(active)
    _revalidate_active_target(active)
    graph = _graph(active, facts)
    _validate_graph(graph)
    return graph


def write_architecture_map() -> dict[str, object]:
    """Atomically write the map to its sole fixed ignored output location."""
    graph = build_architecture_map()
    _atomic_write(ARCHITECTURE_OUTPUT, _json_bytes(graph))
    return graph


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m targets.architecture",
        description="Render only Crack's active approved school-portal architecture map.",
    )
    parser.add_argument("--write", action="store_true", help="atomically write only fixed ignored map path")
    args = parser.parse_args(argv)
    try:
        graph = write_architecture_map() if args.write else build_architecture_map()
    except ArchitectureMapError as error:
        print(json.dumps({"error": str(error)}, sort_keys=True))
        return 2
    print(_json_bytes(graph).decode("utf-8"), end="")
    return 0


def _load_active_target() -> ActiveTarget:
    try:
        return load_active_target(DEFAULT_REGISTRY_ROOT)
    except ActiveTargetError as error:
        raise ArchitectureMapError("active approved target is unavailable") from error


def _revalidate_active_target(active: ActiveTarget) -> None:
    refreshed = _load_active_target()
    if (
        refreshed.snapshot_root != active.snapshot_root
        or refreshed.plan.snapshot_sha256 != active.plan.snapshot_sha256
        or refreshed.plan.manifest != active.plan.manifest
        or refreshed.plan.files != active.plan.files
    ):
        raise ArchitectureMapError("active approved target changed during analysis")


def _extract_facts(active: ActiveTarget) -> _ArchitectureFacts:
    file_paths = {item.relative_path for item in active.plan.files}
    if not _EXPECTED_FILES <= file_paths:
        raise ArchitectureMapError("approved target source is not the supported school portal")
    try:
        main_tree = ast.parse(_read_source(active, "app/main.py"), filename="approved-main.py")
        database_tree = ast.parse(_read_source(active, "app/database.py"), filename="approved-database.py")
    except SyntaxError as error:
        raise ArchitectureMapError("approved target source is not supported") from error
    if not _has_fastapi_application(main_tree):
        raise ArchitectureMapError("approved target API declaration is not supported")
    routes = _route_definitions(main_tree)
    if routes != _EXPECTED_ROUTES:
        raise ArchitectureMapError("approved target routes are not the supported school portal")
    if not _serves_static_portal(main_tree, routes):
        raise ArchitectureMapError("approved target static portal structure is not supported")
    if not _has_only_supported_application_calls(main_tree):
        raise ArchitectureMapError("approved target API declaration is not supported")
    protected_routes = {
        route for route, name in routes.items() if _has_current_person_dependency(_function(main_tree, name))
    }
    if (
        protected_routes != _PROTECTED_ROUTES
        or not _has_fixed_auth_boundary(main_tree)
        or not _has_fixed_role_helper(main_tree)
        or not _has_fixed_role_checks(main_tree, routes)
    ):
        raise ArchitectureMapError("approved target authorization structure is not supported")
    if not _has_grade_lifecycle(main_tree):
        raise ArchitectureMapError("approved target grade lifecycle is not supported")
    table_names, table_bodies = _schema_tables(database_tree)
    if table_names != _EXPECTED_TABLES or table_bodies != _EXPECTED_SCHEMA:
        raise ArchitectureMapError("approved target persistence structure is not supported")
    return _ArchitectureFacts(
        route_count=len(routes),
        protected_route_count=len(protected_routes),
        table_names=table_names,
    )


def _read_source(active: ActiveTarget, relative_path: str) -> str:
    try:
        content = read_active_file(active, relative_path)
        return content.decode("utf-8")
    except (ActiveTargetError, UnicodeDecodeError) as error:
        raise ArchitectureMapError("approved target source cannot be read") from error


def _function(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    matches = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    if len(matches) != 1:
        raise ArchitectureMapError("approved target source is ambiguous")
    return matches[0]


def _has_fastapi_application(tree: ast.Module) -> bool:
    declarations = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "app"
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "FastAPI"
    ]
    return len(declarations) == 1


def _route_definitions(tree: ast.Module) -> dict[tuple[str, str], str]:
    routes: dict[tuple[str, str], str] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            if not isinstance(decorator.func.value, ast.Name) or decorator.func.value.id != "app":
                continue
            method = decorator.func.attr.upper()
            if method not in {"GET", "POST"}:
                raise ArchitectureMapError("approved target route declaration is not supported")
            if len(decorator.args) != 1 or not isinstance(decorator.args[0], ast.Constant):
                raise ArchitectureMapError("approved target route declaration is ambiguous")
            path = decorator.args[0].value
            if not isinstance(path, str):
                raise ArchitectureMapError("approved target route declaration is ambiguous")
            key = (method, path)
            if key in routes:
                raise ArchitectureMapError("approved target route declaration is ambiguous")
            routes[key] = node.name
    return routes


def _has_only_supported_application_calls(tree: ast.Module) -> bool:
    return all(
        node.func.attr in {"get", "post", "mount"}
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "app"
    )


def _serves_static_portal(tree: ast.Module, routes: dict[tuple[str, str], str]) -> bool:
    portal_home = _function(tree, routes[("GET", "/")])
    has_file_response = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "FileResponse"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.BinOp)
        and isinstance(node.args[0].op, ast.Div)
        and isinstance(node.args[0].left, ast.Name)
        and node.args[0].left.id == "_STATIC_DIR"
        and isinstance(node.args[0].right, ast.Constant)
        and node.args[0].right.value == "index.html"
        for node in ast.walk(portal_home)
    )
    has_static_mount = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "app"
        and node.func.attr == "mount"
        and len(node.args) == 2
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "/static"
        and isinstance(node.args[1], ast.Call)
        and isinstance(node.args[1].func, ast.Name)
        and node.args[1].func.id == "StaticFiles"
        and len(node.args[1].args) == 0
        and len(node.args[1].keywords) == 1
        and node.args[1].keywords[0].arg == "directory"
        and isinstance(node.args[1].keywords[0].value, ast.Name)
        and node.args[1].keywords[0].value.id == "_STATIC_DIR"
        for node in ast.walk(tree)
    )
    return has_file_response and has_static_mount


def _has_current_person_dependency(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for default in (*function.args.defaults, *function.args.kw_defaults):
        if (
            isinstance(default, ast.Call)
            and isinstance(default.func, ast.Name)
            and default.func.id == "Depends"
            and len(default.args) == 1
            and isinstance(default.args[0], ast.Name)
            and default.args[0].id == "current_person"
        ):
            return True
    return False


def _has_fixed_auth_boundary(tree: ast.Module) -> bool:
    current_person = _function(tree, "current_person")
    body = _non_docstring_body(current_person)
    if not _has_authorization_header_default(current_person) or len(body) != 5:
        return False
    return (
        _is_missing_bearer_guard(body[0])
        and _is_token_extraction(body[1])
        and _is_parameterized_people_lookup(body[2])
        and _is_invalid_token_guard(body[3])
        and _is_database_row_return(body[4])
    )


def _non_docstring_body(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    body = list(function.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        return body[1:]
    return body


def _has_authorization_header_default(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    arguments = function.args
    if len(arguments.args) != 1 or arguments.args[0].arg != "authorization":
        return False
    if arguments.vararg or arguments.kwarg or arguments.kwonlyargs or len(arguments.defaults) != 1:
        return False
    default = arguments.defaults[0]
    return (
        isinstance(default, ast.Call)
        and isinstance(default.func, ast.Name)
        and default.func.id == "Header"
        and not default.args
        and len(default.keywords) == 1
        and default.keywords[0].arg == "default"
        and isinstance(default.keywords[0].value, ast.Constant)
        and default.keywords[0].value.value is None
    )


def _is_missing_bearer_guard(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.If)
        and isinstance(statement.test, ast.BoolOp)
        and isinstance(statement.test.op, ast.Or)
        and len(statement.test.values) == 2
        and isinstance(statement.test.values[0], ast.UnaryOp)
        and isinstance(statement.test.values[0].op, ast.Not)
        and isinstance(statement.test.values[0].operand, ast.Name)
        and statement.test.values[0].operand.id == "authorization"
        and _is_bearer_startswith_negation(statement.test.values[1])
        and _is_unauthorized_raise(statement.body)
        and not statement.orelse
    )


def _is_bearer_startswith_negation(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.Not)
        and isinstance(node.operand, ast.Call)
        and isinstance(node.operand.func, ast.Attribute)
        and isinstance(node.operand.func.value, ast.Name)
        and node.operand.func.value.id == "authorization"
        and node.operand.func.attr == "startswith"
        and len(node.operand.args) == 1
        and isinstance(node.operand.args[0], ast.Constant)
        and node.operand.args[0].value == "Bearer "
        and not node.operand.keywords
    )


def _is_token_extraction(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id == "token"
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Attribute)
        and isinstance(statement.value.func.value, ast.Name)
        and statement.value.func.value.id == "authorization"
        and statement.value.func.attr == "removeprefix"
        and len(statement.value.args) == 1
        and isinstance(statement.value.args[0], ast.Constant)
        and statement.value.args[0].value == "Bearer "
        and not statement.value.keywords
    )


def _is_parameterized_people_lookup(statement: ast.stmt) -> bool:
    if not isinstance(statement, ast.With) or len(statement.items) != 1 or len(statement.body) != 1:
        return False
    item = statement.items[0]
    if not (
        isinstance(item.context_expr, ast.Call)
        and isinstance(item.context_expr.func, ast.Name)
        and item.context_expr.func.id == "connect"
        and not item.context_expr.args
        and not item.context_expr.keywords
        and isinstance(item.optional_vars, ast.Name)
        and item.optional_vars.id == "connection"
    ):
        return False
    lookup = statement.body[0]
    if not (
        isinstance(lookup, ast.Assign)
        and len(lookup.targets) == 1
        and isinstance(lookup.targets[0], ast.Name)
        and lookup.targets[0].id == "person"
        and isinstance(lookup.value, ast.Call)
        and isinstance(lookup.value.func, ast.Attribute)
        and lookup.value.func.attr == "fetchone"
        and not lookup.value.args
        and not lookup.value.keywords
    ):
        return False
    execute = lookup.value.func.value
    return (
        isinstance(execute, ast.Call)
        and isinstance(execute.func, ast.Attribute)
        and isinstance(execute.func.value, ast.Name)
        and execute.func.value.id == "connection"
        and execute.func.attr == "execute"
        and len(execute.args) == 2
        and not execute.keywords
        and isinstance(execute.args[0], ast.Constant)
        and isinstance(execute.args[0].value, str)
        and _is_people_token_query(execute.args[0].value)
        and isinstance(execute.args[1], ast.Tuple)
        and len(execute.args[1].elts) == 1
        and isinstance(execute.args[1].elts[0], ast.Name)
        and execute.args[1].elts[0].id == "token"
    )


def _is_people_token_query(query: str) -> bool:
    return " ".join(query.split()) == "SELECT id, role, display_name FROM people WHERE token = ?"


def _is_invalid_token_guard(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.If)
        and isinstance(statement.test, ast.Compare)
        and isinstance(statement.test.left, ast.Name)
        and statement.test.left.id == "person"
        and len(statement.test.ops) == 1
        and isinstance(statement.test.ops[0], ast.Is)
        and len(statement.test.comparators) == 1
        and isinstance(statement.test.comparators[0], ast.Constant)
        and statement.test.comparators[0].value is None
        and _is_unauthorized_raise(statement.body)
        and not statement.orelse
    )


def _is_unauthorized_raise(statements: list[ast.stmt]) -> bool:
    return _is_http_exception_raise(statements, "HTTP_401_UNAUTHORIZED")


def _is_conflict_raise(statements: list[ast.stmt]) -> bool:
    return _is_http_exception_raise(statements, "HTTP_409_CONFLICT")


def _is_forbidden_raise(statements: list[ast.stmt]) -> bool:
    return _is_http_exception_raise(statements, "HTTP_403_FORBIDDEN")


def _is_http_exception_raise(statements: list[ast.stmt], expected_status: str) -> bool:
    return (
        len(statements) == 1
        and isinstance(statements[0], ast.Raise)
        and isinstance(statements[0].exc, ast.Call)
        and isinstance(statements[0].exc.func, ast.Name)
        and statements[0].exc.func.id == "HTTPException"
        and any(
            keyword.arg == "status_code"
            and isinstance(keyword.value, ast.Attribute)
            and isinstance(keyword.value.value, ast.Name)
            and keyword.value.value.id == "status"
            and keyword.value.attr == expected_status
            for keyword in statements[0].exc.keywords
        )
    )


def _is_database_row_return(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Return)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Name)
        and statement.value.func.id == "dict"
        and len(statement.value.args) == 1
        and isinstance(statement.value.args[0], ast.Name)
        and statement.value.args[0].id == "person"
        and not statement.value.keywords
    )


def _has_fixed_role_checks(
    tree: ast.Module, routes: dict[tuple[str, str], str]
) -> bool:
    if set(_EXPECTED_ROLE_BY_ROUTE) != _PROTECTED_ROUTES:
        raise ArchitectureMapError("approved target role rules are incomplete")
    return all(
        _has_direct_role_call(_function(tree, routes[route]), role)
        for route, role in _EXPECTED_ROLE_BY_ROUTE.items()
    )


def _has_fixed_role_helper(tree: ast.Module) -> bool:
    helper = _function(tree, "_require_role")
    arguments = helper.args
    body = _non_docstring_body(helper)
    return (
        isinstance(helper, ast.FunctionDef)
        and not arguments.posonlyargs
        and len(arguments.args) == 2
        and [argument.arg for argument in arguments.args] == ["person", "role"]
        and not arguments.defaults
        and not arguments.vararg
        and not arguments.kwarg
        and not arguments.kwonlyargs
        and len(body) == 1
        and isinstance(body[0], ast.If)
        and _is_role_mismatch(body[0].test)
        and _is_forbidden_raise(body[0].body)
        and not body[0].orelse
    )


def _is_role_mismatch(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Subscript)
        and isinstance(node.left.value, ast.Name)
        and node.left.value.id == "person"
        and isinstance(node.left.slice, ast.Constant)
        and node.left.slice.value == "role"
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.NotEq)
        and len(node.comparators) == 1
        and isinstance(node.comparators[0], ast.Name)
        and node.comparators[0].id == "role"
    )


def _has_direct_role_call(function: ast.FunctionDef | ast.AsyncFunctionDef, expected_role: str) -> bool:
    calls = [
        statement.value
        for statement in function.body
        if isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Name)
        and statement.value.func.id == "_require_role"
    ]
    return len(calls) == 1 and _is_exact_role_call(calls[0], expected_role)


def _is_exact_role_call(call: ast.Call, expected_role: str) -> bool:
    return (
        len(call.args) == 2
        and not call.keywords
        and isinstance(call.args[0], ast.Name)
        and call.args[0].id == "person"
        and isinstance(call.args[1], ast.Constant)
        and call.args[1].value == expected_role
    )


def _has_grade_lifecycle(tree: ast.Module) -> bool:
    review = _function(tree, "review_grade")
    publish = _function(tree, "publish_grade")
    return (
        _has_grade_state_guard(review, "draft", ast.NotEq)
        and _has_grade_state_update(review, "reviewed")
        and _has_grade_state_guard(publish, "published", ast.Eq)
        and _has_grade_state_update(publish, "published")
        and not _has_executable_grade_state_comparison(
            publish, "reviewed", (ast.Eq, ast.NotEq)
        )
    )


def _has_grade_state_guard(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    expected_state: str,
    operators: type[ast.cmpop] | tuple[type[ast.cmpop], ...],
) -> bool:
    return any(
        isinstance(statement, ast.If)
        and _is_grade_state_comparison(statement.test, expected_state, operators)
        and _is_conflict_raise(statement.body)
        and not statement.orelse
        for statement in _non_docstring_body(function)
    )


def _has_executable_grade_state_comparison(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    expected_state: str,
    operators: type[ast.cmpop] | tuple[type[ast.cmpop], ...],
) -> bool:
    return any(
        isinstance(statement, ast.If)
        and _is_grade_state_comparison(statement.test, expected_state, operators)
        for statement in _non_docstring_body(function)
    )


def _is_grade_state_comparison(
    node: ast.expr,
    expected_state: str,
    operators: type[ast.cmpop] | tuple[type[ast.cmpop], ...],
) -> bool:
    return (
        isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Subscript)
        and isinstance(node.left.value, ast.Name)
        and node.left.value.id == "grade"
        and isinstance(node.left.slice, ast.Constant)
        and node.left.slice.value == "state"
        and len(node.ops) == 1
        and isinstance(node.ops[0], operators)
        and len(node.comparators) == 1
        and isinstance(node.comparators[0], ast.Constant)
        and node.comparators[0].value == expected_state
    )


def _has_grade_state_update(
    function: ast.FunctionDef | ast.AsyncFunctionDef, expected_state: str
) -> bool:
    return any(
        _is_grade_state_update(statement.value, expected_state)
        for statement in _non_docstring_body(function)
        if isinstance(statement, ast.With)
        for statement in statement.body
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
    )


def _is_grade_state_update(call: ast.Call, expected_state: str) -> bool:
    return (
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "connection"
        and call.func.attr == "execute"
        and len(call.args) == 2
        and not call.keywords
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
        and " ".join(call.args[0].value.split())
        == f"UPDATE grades SET state = '{expected_state}' WHERE id = ?"
        and isinstance(call.args[1], ast.Tuple)
        and len(call.args[1].elts) == 1
        and isinstance(call.args[1].elts[0], ast.Name)
        and call.args[1].elts[0].id == "grade_id"
    )


def _schema_tables(tree: ast.Module) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    initializer = _function(tree, "initialize_database")
    scripts = [
        node.args[0].value
        for node in ast.walk(initializer)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "executescript"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ]
    if len(scripts) != 1:
        raise ArchitectureMapError("approved target persistence schema is ambiguous")
    return _parse_schema(scripts[0])


def _parse_schema(script: str) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    tokens = _sql_tokens(script)
    index = 0
    tables: list[str] = []
    bodies: dict[str, tuple[str, ...]] = {}
    while index < len(tokens):
        if tokens[index : index + 5] != ("CREATE", "TABLE", "IF", "NOT", "EXISTS"):
            raise ArchitectureMapError("approved target persistence schema is not supported")
        if index + 6 >= len(tokens) or not _identifier(tokens[index + 5]) or tokens[index + 6] != "(":
            raise ArchitectureMapError("approved target persistence schema is not supported")
        table_name = tokens[index + 5]
        if table_name in bodies:
            raise ArchitectureMapError("approved target persistence schema is ambiguous")
        index += 7
        depth = 1
        body: list[str] = []
        while index < len(tokens) and depth:
            token = tokens[index]
            if token == "(":
                depth += 1
            elif token == ")":
                depth -= 1
                if depth == 0:
                    index += 1
                    break
            body.append(token)
            index += 1
        if depth or index >= len(tokens) or tokens[index] != ";":
            raise ArchitectureMapError("approved target persistence schema is not supported")
        index += 1
        tables.append(table_name)
        bodies[table_name] = tuple(body)
    return tuple(tables), bodies


def _sql_tokens(script: str) -> tuple[str, ...]:
    tokens: list[str] = []
    index = 0
    while index < len(script):
        character = script[index]
        if character.isspace():
            index += 1
            continue
        if character.isalpha() or character == "_":
            end = index + 1
            while end < len(script) and (script[end].isalnum() or script[end] == "_"):
                end += 1
            tokens.append(script[index:end].upper())
            index = end
            continue
        if character == "'":
            end = index + 1
            while end < len(script) and script[end] != "'":
                end += 1
            if end == len(script):
                raise ArchitectureMapError("approved target persistence schema is not supported")
            tokens.append(f"STRING:{script[index + 1:end].upper()}")
            index = end + 1
            continue
        if character in "(),;":
            tokens.append(character)
            index += 1
            continue
        raise ArchitectureMapError("approved target persistence schema is not supported")
    return tuple(tokens)


def _identifier(token: str) -> bool:
    return token not in {"CREATE", "TABLE", "IF", "NOT", "EXISTS", "REFERENCES", "TEXT", "PRIMARY", "KEY", "UNIQUE", "CHECK", "STRING"} and token.isupper()


def _graph(active: ActiveTarget, facts: _ArchitectureFacts) -> dict[str, object]:
    if facts.route_count != len(_EXPECTED_ROUTES) or facts.protected_route_count != len(_PROTECTED_ROUTES):
        raise ArchitectureMapError("approved target architecture is incomplete")
    if facts.table_names != _EXPECTED_TABLES:
        raise ArchitectureMapError("approved target architecture is incomplete")
    nodes = [
        _node("browser-portal", "Browser portal", "interface", "presentation", "Static browser portal served by FastAPI.", 0.08, 0.5),
        _node("fastapi-api", "FastAPI API", "service", "application", "Fixed school-portal HTTP routes.", 0.32, 0.5),
        _node("grade-lifecycle", "Grade lifecycle", "domain", "domain", "Review and publication lifecycle for grades.", 0.72, 0.7),
        _node("role-authentication", "Role and authentication", "boundary", "security", "Fixed role and bearer-authentication boundary.", 0.52, 0.2),
        _node("sqlite-persistence", "SQLite persistence", "persistence", "data", "SQLite stores portal domain records.", 0.92, 0.5),
        _node("submissions", "Submissions", "domain", "domain", "Student submission domain records.", 0.72, 0.32),
    ]
    edges = [
        _edge("fastapi-api--serves--browser-portal", "fastapi-api", "browser-portal", "serves static portal"),
        _edge("fastapi-api--uses--role-authentication", "fastapi-api", "role-authentication", "uses protected-route boundary"),
        _edge("fastapi-api--uses--submissions", "fastapi-api", "submissions", "exposes submission routes"),
        _edge("fastapi-api--uses--grade-lifecycle", "fastapi-api", "grade-lifecycle", "exposes grade routes"),
        _edge("role-authentication--authorizes--submissions", "role-authentication", "submissions", "authorizes submission access"),
        _edge("role-authentication--authorizes--grade-lifecycle", "role-authentication", "grade-lifecycle", "authorizes grade access"),
        _edge("submissions--links--grade-lifecycle", "submissions", "grade-lifecycle", "links submissions and grades"),
        _edge("submissions--persists--sqlite-persistence", "submissions", "sqlite-persistence", "persists submissions"),
        _edge("grade-lifecycle--persists--sqlite-persistence", "grade-lifecycle", "sqlite-persistence", "persists grades"),
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "target": {"id": active.plan.manifest.target_id, "snapshot_sha256": active.plan.snapshot_sha256},
        "nodes": sorted(nodes, key=lambda item: str(item["id"])),
        "edges": sorted(edges, key=lambda item: str(item["id"])),
    }


def _node(
    node_id: str,
    label: str,
    node_type: str,
    layer: str,
    description: str,
    x: float,
    y: float,
) -> dict[str, object]:
    return {
        "id": node_id,
        "label": label,
        "type": node_type,
        "layer": layer,
        "description": description,
        "coordinates": {"x": x, "y": y},
        "provenance": {"facts": _SOURCE_PROVENANCE, "layout": _LAYOUT_PROVENANCE},
    }


def _edge(edge_id: str, source: str, target: str, label: str) -> dict[str, str]:
    return {
        "id": edge_id,
        "source": source,
        "target": target,
        "label": label,
        "provenance": _SOURCE_PROVENANCE,
    }


def _validate_graph(graph: dict[str, object]) -> None:
    if set(graph) != {"schema_version", "target", "nodes", "edges"} or graph["schema_version"] != SCHEMA_VERSION:
        raise ArchitectureMapError("architecture map schema is invalid")
    target = graph["target"]
    nodes = graph["nodes"]
    edges = graph["edges"]
    if not isinstance(target, dict) or set(target) != {"id", "snapshot_sha256"}:
        raise ArchitectureMapError("architecture map target is invalid")
    if not isinstance(target["id"], str) or not _sha256(target["snapshot_sha256"]):
        raise ArchitectureMapError("architecture map target is invalid")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ArchitectureMapError("architecture map topology is invalid")
    node_ids: list[str] = []
    for node in nodes:
        if not isinstance(node, dict) or set(node) != {
            "id", "label", "type", "layer", "description", "coordinates", "provenance"
        }:
            raise ArchitectureMapError("architecture map node is invalid")
        if not all(isinstance(node[key], str) and node[key] for key in ("id", "label", "description")):
            raise ArchitectureMapError("architecture map node is invalid")
        if node["type"] not in _ALLOWED_NODE_TYPES or node["layer"] not in _ALLOWED_LAYERS:
            raise ArchitectureMapError("architecture map node is invalid")
        coordinates = node["coordinates"]
        provenance = node["provenance"]
        if (
            not isinstance(coordinates, dict)
            or set(coordinates) != {"x", "y"}
            or any(type(value) is not float or not 0.0 <= value <= 1.0 for value in coordinates.values())
            or provenance != {"facts": _SOURCE_PROVENANCE, "layout": _LAYOUT_PROVENANCE}
        ):
            raise ArchitectureMapError("architecture map node is invalid")
        node_ids.append(node["id"])
    if tuple(node_ids) != _NODE_IDS or len(node_ids) != len(set(node_ids)):
        raise ArchitectureMapError("architecture map nodes are incomplete")
    edge_ids: list[str] = []
    for edge in edges:
        if not isinstance(edge, dict) or set(edge) != {"id", "source", "target", "label", "provenance"}:
            raise ArchitectureMapError("architecture map edge is invalid")
        if not all(isinstance(edge[key], str) and edge[key] for key in ("id", "source", "target", "label")):
            raise ArchitectureMapError("architecture map edge is invalid")
        if edge["source"] not in node_ids or edge["target"] not in node_ids or edge["source"] == edge["target"]:
            raise ArchitectureMapError("architecture map edge is invalid")
        if edge["provenance"] != _SOURCE_PROVENANCE:
            raise ArchitectureMapError("architecture map edge is invalid")
        edge_ids.append(edge["id"])
    if edge_ids != sorted(edge_ids) or len(edge_ids) != len(set(edge_ids)):
        raise ArchitectureMapError("architecture map edges are invalid")


def _sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _json_bytes(graph: dict[str, object]) -> bytes:
    return (json.dumps(graph, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _atomic_write(path: Path, content: bytes) -> None:
    if path != ARCHITECTURE_OUTPUT:
        raise ArchitectureMapError("architecture output path is fixed")
    directory = _prepare_output_directory(path.parent)
    temporary_name = f".{path.name}.{uuid4().hex}.tmp"
    try:
        try:
            existing = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            pass
        except OSError:
            raise ArchitectureMapError("architecture output path is unavailable") from None
        else:
            if stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode):
                raise ArchitectureMapError("architecture output path is unsafe")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary_name, flags, 0o600, dir_fd=directory)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path.name, src_dir_fd=directory, dst_dir_fd=directory)
    except OSError as error:
        try:
            os.unlink(temporary_name, dir_fd=directory)
        except FileNotFoundError:
            pass
        except OSError:
            pass
        raise ArchitectureMapError("architecture output cannot be written") from error
    finally:
        os.close(directory)


def _prepare_output_directory(path: Path) -> int:
    if not path.is_absolute() or path != ARCHITECTURE_OUTPUT.parent:
        raise ArchitectureMapError("architecture output path is fixed")
    try:
        descriptor = _open_absolute_directory_chain(path, create=True)
    except TargetImportError as error:
        raise ArchitectureMapError("architecture output directory is unsafe") from error
    try:
        current = os.fstat(descriptor)
        if not stat.S_ISDIR(current.st_mode):
            raise ArchitectureMapError("architecture output directory is unsafe")
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


if __name__ == "__main__":
    raise SystemExit(main())
