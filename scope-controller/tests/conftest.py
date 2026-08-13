"""Make the repository-local library importable from either pytest invocation root."""

from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCOPE_CONTROLLER_ROOT = REPOSITORY_ROOT / "scope-controller"

for import_root in (REPOSITORY_ROOT, SCOPE_CONTROLLER_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))
