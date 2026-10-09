"""Minimal-change repair after an absence: re-solve keeping as much of the old rota as possible."""
from __future__ import annotations

from .schema import Problem, Schedule
from .solver import solve


def diff(prev: Schedule, new: Schedule) -> list[tuple[str, str, str | None, str | None]]:
    """(date, shift, from_person, to_person) for every seat that changed."""
    out = []
    for day, per_shift in new.assignments.items():
        for shift, people in per_shift.items():
            before = prev.assignments.get(day, {}).get(shift, [])
            removed = [p for p in before if p not in people]
            added = [p for p in people if p not in before]
            for i in range(max(len(removed), len(added))):
                out.append((day, shift, removed[i] if i < len(removed) else None, added[i] if i < len(added) else None))
    return sorted(out)


def repair(problem: Problem, constraints: list, prev: Schedule, new_constraints: list) -> dict:
    """Add `new_constraints` (e.g. a sick day) and re-solve minimising changed assignments.

    Returns {status, schedule, changed, core_ids, core, solve_seconds}.
    """
    taken = {c.id for c in constraints}
    for i, c in enumerate(new_constraints, 1):
        if not c.id or c.id in taken:
            c.id = f"absence{i}"
    res = solve(problem, list(constraints) + list(new_constraints), prev=prev)
    res["changed"] = diff(prev, res["schedule"]) if res["schedule"] is not None else []
    return res
