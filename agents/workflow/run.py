"""CLI entry point for the contained workflow-rule agent."""

from __future__ import annotations

from .agent import WorkflowError, run_workflow


def main() -> int:
    try:
        result = run_workflow()
    except WorkflowError as exc:
        print(f"WORKFLOW BLOCKED: {exc}")
        return 2
    except Exception as exc:
        print(f"WORKFLOW FAILED: {exc}")
        return 1
    print(f"WORKFLOW COMPLETED: {result.run_id}")
    for hypothesis_id in result.hypothesis_ids:
        print(f"UNVERIFIED HYPOTHESIS: {hypothesis_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
