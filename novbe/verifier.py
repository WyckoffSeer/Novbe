"""Independent rule checker.

Re-checks a finished Schedule against the constraint list with plain Python loops.
Deliberately does NOT import solver code: it is the second opinion, and it is also
used to score the chatbot baseline.
"""
from __future__ import annotations

import datetime as dt

from .schema import Problem, Schedule, VerifyReport, Violation


def _people(problem: Problem, person: str) -> list[str]:
    return [s.id for s in problem.staff] if person == "all" else [person]


def _shift_ok(shift_filter, shift_id) -> bool:
    return shift_filter in (None, "all") or shift_filter == shift_id


def _week_of(problem: Problem, day: dt.date) -> int:
    return (day - problem.start_date).days // 7


def verify(problem: Problem, schedule: Schedule, constraints: list) -> VerifyReport:
    v: list[Violation] = []
    days = problem.days
    staff_ids = {s.id for s in problem.staff}
    role = {s.id: s.role for s in problem.staff}
    hours = {t.id: t.hours for t in problem.shifts}
    shift_by_id = {t.id: t for t in problem.shifts}

    # who works what on which day: shifts_of[(person, date_iso)] -> list of shift ids
    shifts_of: dict[tuple[str, str], list[str]] = {}
    for day in days:
        key = day.isoformat()
        for shift_id, people in schedule.assignments.get(key, {}).items():
            for p in people:
                shifts_of.setdefault((p, key), []).append(shift_id)

    # structural checks: known people and shifts, one shift per day, dates in horizon
    horizon = {d.isoformat() for d in days}
    for key, per_shift in schedule.assignments.items():
        if key not in horizon:
            v.append(Violation(constraint_id="structural", date=key, detail="date outside planning horizon"))
        for shift_id, people in per_shift.items():
            if shift_id not in shift_by_id:
                v.append(Violation(constraint_id="structural", date=key, detail=f"unknown shift {shift_id}"))
            for p in people:
                if p not in staff_ids:
                    v.append(Violation(constraint_id="structural", date=key, detail=f"unknown person {p}"))
    for (p, key), lst in shifts_of.items():
        if len(lst) > 1:
            v.append(Violation(constraint_id="structural", date=key, detail=f"{p} has {len(lst)} shifts on one day"))

    def works(p: str, day: dt.date) -> list[str]:
        return shifts_of.get((p, day.isoformat()), [])

    for c in constraints:
        t = c.type
        if t == "unavailable":
            for day in days:
                blocked = (c.weekdays is None and c.date_range is None)
                if c.weekdays is not None and day.weekday() in c.weekdays:
                    blocked = True
                if c.date_range is not None and c.date_range[0] <= day <= c.date_range[1]:
                    blocked = True
                if not blocked:
                    continue
                for p in _people(problem, c.person):
                    for s in works(p, day):
                        if _shift_ok(c.shift, s):
                            v.append(Violation(constraint_id=c.id, date=day.isoformat(), detail=f"{p} works {s} but is unavailable"))

        elif t == "max_consecutive_days":
            for p in _people(problem, c.person):
                run = 0
                for day in days:
                    run = run + 1 if works(p, day) else 0
                    if run == c.n + 1:
                        v.append(Violation(constraint_id=c.id, date=day.isoformat(), detail=f"{p} works {run} days in a row (max {c.n})"))

        elif t == "min_staff":
            for day in days:
                if c.weekdays is not None and day.weekday() not in c.weekdays:
                    continue
                for s in problem.shifts:
                    if not _shift_ok(c.shift, s.id):
                        continue
                    got = len(schedule.assignments.get(day.isoformat(), {}).get(s.id, []))
                    if got < c.n:
                        v.append(Violation(constraint_id=c.id, date=day.isoformat(), detail=f"{s.id}: {got} people, need {c.n}"))

        elif t == "min_role":
            for day in days:
                for s in problem.shifts:
                    if not _shift_ok(c.shift, s.id):
                        continue
                    people = schedule.assignments.get(day.isoformat(), {}).get(s.id, [])
                    got = sum(1 for p in people if role.get(p) == c.role)
                    if got < c.n:
                        v.append(Violation(constraint_id=c.id, date=day.isoformat(), detail=f"{s.id}: {got} {c.role}(s), need {c.n}"))

        elif t in ("max_hours_week", "max_shifts_week"):
            for p in _people(problem, c.person):
                per_week: dict[int, int] = {}
                for day in days:
                    for s in works(p, day):
                        add = hours[s] if t == "max_hours_week" else 1
                        per_week[_week_of(problem, day)] = per_week.get(_week_of(problem, day), 0) + add
                limit = c.hours if t == "max_hours_week" else c.n
                for w, total in sorted(per_week.items()):
                    if total > limit:
                        start = (problem.start_date + dt.timedelta(days=7 * w)).isoformat()
                        v.append(Violation(constraint_id=c.id, date=start, detail=f"{p}: {total} in week {w + 1} (max {limit})"))

        elif t == "min_rest_hours":
            # absolute hour timeline per person, then check each consecutive pair of shifts
            for p in staff_ids:
                spans = []
                for i, day in enumerate(days):
                    for s in works(p, day):
                        st = i * 24 + shift_by_id[s].start
                        spans.append((st, st + shift_by_id[s].hours, s, day))
                spans.sort()
                for (s1, e1, n1, d1), (s2, _e2, _n2, _d2) in zip(spans, spans[1:]):
                    if c.after_shift not in (None, "all") and n1 != c.after_shift:
                        continue
                    if s2 - e1 < c.hours:
                        v.append(Violation(constraint_id=c.id, date=d1.isoformat(), detail=f"{p}: only {s2 - e1}h rest after {n1}"))

        elif t == "fixed_assignment":
            for p in _people(problem, c.person):
                ws = works(p, c.date)
                if not any(_shift_ok(c.shift, s) for s in ws):
                    v.append(Violation(constraint_id=c.id, date=c.date.isoformat(), detail=f"{p} must work {c.shift}"))

    return VerifyReport(violations=v)
