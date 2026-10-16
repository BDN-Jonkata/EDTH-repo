"""Make the seeder's flat modules (`catalog`, `scenario`) importable from other packages.

The seeder scripts import each other as top-level modules (`import catalog`), so
`seeder/` has to be on `sys.path`. The seeder tests do the same. Call this once
before `import catalog` or `import scenario`.
"""

import sys
from pathlib import Path

SEEDER_DIR = Path(__file__).resolve().parents[1] / "seeder"


def ensure_seeder_on_path() -> None:
    path = str(SEEDER_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)
