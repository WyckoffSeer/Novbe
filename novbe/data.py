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


def offline_demo_parse(problem):
    """Hand-written ParseResult for data/demo_rules.txt (no AI). Used only by the offline
    fallback button in the UI and as the expected answer in tests."""
    from .schema import Ambiguous, MaxConsecutiveDays, MinRestHours, MinRole, ParseResult, Unavailable

    lines = [l.strip() for l in demo_rules().splitlines() if l.strip()]
    ids = {s.name: s.id for s in problem.staff}
    cs = [
        Unavailable(person=ids["Aysel"], weekdays=[4]),
        MinRole(shift="night", role="senior", n=2),
        MaxConsecutiveDays(person="all", n=5),
        Unavailable(person=ids["Elnur"], weekdays=[2], shift="morning"),
        Unavailable(person=ids["Leyla"], weekdays=[5]),
        MinRestHours(hours=11, after_shift="night"),
    ]
    for i, c in enumerate(cs):
        c.id, c.source_text = f"c{i + 1}", lines[i]
    return ParseResult(constraints=cs, ambiguous=[Ambiguous(source_text=lines[6], question="Bu qəti qaydadır, yoxsa sadəcə istək?")])
