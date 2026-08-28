"""CLI entrypoint for one independent Crack verification pass."""

from __future__ import annotations

import argparse
import json

from .agent import run_verifier


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hypothesis_id", help="Unverified hypothesis ID from the ledger")
    return parser


def main() -> None:
    args = _parser().parse_args()
    result = run_verifier(args.hypothesis_id)
    print(f"run_id: {result.run_id}")
    print(f"hypothesis_id: {result.hypothesis_id}")
    for attempt in result.attempts:
        print(f"{attempt.verifier_role}:")
        print(f"  snapshot_id: {attempt.snapshot_id}")
        print("  proposed_plan:")
        for step in attempt.plan.steps:
            if hasattr(step, "operation"):
                print(f"  - workflow operation: {step.operation}")
            else:
                print(f"  - {step.role} {step.method} {step.path}")
        print("  executed_call_results:")
        for step in attempt.executed_steps:
            resolved_path = step.resolved_path or "<unresolved>"
            print(
                f"  - {step.role} {step.method} {resolved_path}: "
                f"{json.dumps(step.response, sort_keys=True, default=str)}"
            )
        print(
            "  deterministic_check: "
            f"{str(attempt.check.satisfied).lower()} — {attempt.check.reason}"
        )
    print(f"final_verdict: {result.verdict}")
    print(f"finding_id: {result.finding_id or 'none'}")


if __name__ == "__main__":
    main()
