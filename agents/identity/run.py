"""CLI entrypoint for one bounded identity-agent pass."""

from __future__ import annotations

from .agent import run_identity


def main() -> None:
    result = run_identity()
    print(f"run_id: {result.run_id}")
    print("tests:")
    for test in result.tests:
        status = "-" if test.status_code is None else str(test.status_code)
        print(f"- {test.as_role} {test.method} {test.path or '-'} [{status}]: {test.result}")
    if result.plan_was_capped:
        print("plan: capped at 2 app calls")
    print("hypotheses:")
    if not result.hypothesis_ids:
        print("- none")
    for hypothesis_id, claim in zip(result.hypothesis_ids, result.hypothesis_claims, strict=True):
        print(f"- {hypothesis_id}: {claim}")


if __name__ == "__main__":
    main()
