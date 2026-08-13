"""Bounded identity and authorization testing agent for Crack."""

from __future__ import annotations

import sys
from pathlib import Path


# Keep the requested ``python -m agents.identity.run`` entrypoint usable from
# the repository checkout, without giving the agent any new capabilities.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
for _dependency_root in (
    _REPOSITORY_ROOT,
    _REPOSITORY_ROOT / "scope-controller",
    _REPOSITORY_ROOT / "agents" / "router",
):
    if str(_dependency_root) not in sys.path:
        sys.path.insert(0, str(_dependency_root))

