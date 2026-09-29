#!/usr/bin/env python3
"""Run the agent-readiness evaluation (see src/kaur_monitor/agent_eval.py)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kaur_monitor import agent_eval

if __name__ == "__main__":
    raise SystemExit(agent_eval.main())
