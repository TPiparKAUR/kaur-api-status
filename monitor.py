#!/usr/bin/env python3
"""Entry point. Requires only Python 3.11+ and the standard library."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from kaur_monitor.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
