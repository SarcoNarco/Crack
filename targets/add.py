"""CLI for read-only planning and hash-bound offline target registration."""

from __future__ import annotations

import argparse
from pathlib import Path

from .inspection import TargetImportError, inspect_target
from .registry import register_approved


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m targets.add",
        description="Inspect or register Crack's one fixed local target shape without running it.",
    )
    parser.add_argument("source", help="absolute local target directory")
    parser.add_argument("--approve-sha256", help="exact hash printed by the read-only inspection")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.approve_sha256 is None:
            plan = inspect_target(Path(args.source))
            print(f"target_id={plan.manifest.target_id}")
            print(f"files={plan.file_count}")
            print(f"bytes={plan.total_bytes}")
            print(f"snapshot_sha256={plan.snapshot_sha256}")
            print(f"approve with --approve-sha256 {plan.snapshot_sha256}")
            return 0
        registration = register_approved(
            Path(args.source),
            args.approve_sha256,
        )
    except TargetImportError as error:
        print(f"error: {error}")
        return 2

    print(f"target_id={registration.target_id}")
    print(f"files={registration.file_count}")
    print(f"bytes={registration.total_bytes}")
    print(f"snapshot_sha256={registration.snapshot_sha256}")
    print("registration=existing" if registration.reused_snapshot else "registration=created")
    print("active_target=updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
