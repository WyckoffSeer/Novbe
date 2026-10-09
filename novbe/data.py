"""Load synthetic team files from data/."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .schema import Problem, Staff

DATA = Path(__file__).resolve().parent.parent / "data"


def load_problem(name: str = "shop_staff.json", weeks: int | None = None) -> Problem:
    raw = json.loads((DATA / name).read_text(encoding="utf-8"))
    return Problem(
        staff=[Staff(**s) for s in raw["staff"]],
        start_date=dt.date.fromisoformat(raw["start_date"]),
        weeks=weeks or raw.get("weeks", 4),
    )


def demo_rules() -> str:
    return (DATA / "demo_rules.txt").read_text(encoding="utf-8")
