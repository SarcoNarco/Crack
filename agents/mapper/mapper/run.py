"""CLI entrypoint for one source-only app-mapper pass."""

from __future__ import annotations

from .agent import run_mapper


def main() -> None:
    print(run_mapper().model_dump_json(indent=2))


if __name__ == "__main__":
    main()
