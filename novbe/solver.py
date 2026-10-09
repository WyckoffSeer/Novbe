"""CP-SAT model for Növbə.

Every user constraint is guarded by its own assumption literal, so when the model is
infeasible CP-SAT can tell us which constraints clash (the infeasibility core). The
core is then shrunk by deletion so that every reported rule is really needed.
"""
from __future__ import annotations

import time
from typing import Optional

from ortools.sat.python import cp_model

from .schema import Problem, Schedule

TIMEOUT_S = 20.0


def ensure_ids(constraints: list) -> list:
    seen = set()
    for i, c in enumerate(constraints, 1):
        if not c.id or c.id in seen:
            c.id = f"c{i}"
        seen.add(c.id)
    return constraints


class _Model:
    def __init__(self, problem: Problem, constraints: list):
        self.p = problem
        self.cs = constraints
        self.m = cp_model.CpModel()
        self.sid = [s.id for s in problem.staff]
        self.tid = [t.id for t in problem.shifts]
        self.nd = len(problem.days)
        self.x = {
            (s, d, t): self.m.NewBoolVar(f"x_{s}_{d}_{t}")
            for s in self.sid
            for d in range(self.nd)
            for t in self.tid
        }
        for s in self.sid:  # at most one shift per person per day (structural)
            for d in range(self.nd):
                self.m.AddAtMostOne(self.x[s, d, t] for t in self.tid)
        self.lit: dict[str, cp_model.IntVar] = {}
        for c in constraints:
            lit = self.m.NewBoolVar(f"a_{c.id}")
            self.lit[c.id] = lit
            getattr(self, "_" + c.type)(c, lit)

    # ------------------------------------------------------------ helpers
    def _people(self, person: str) -> list[str]:
        if person == "all":
            return self.sid
        if person not in self.sid:
            raise ValueError(f"unknown staff id {person!r}")
        return [person]

    def _shifts(self, shift: Optional[str]) -> list[str]:
        if shift in (None, "all"):
            return self.tid
        if shift not in self.tid:
            raise ValueError(f"unknown shift {shift!r}")
        return [shift]

    def _work(self, s: str, d: int):
        return sum(self.x[s, d, t] for t in self.tid)

    def _weeks(self):
        return [range(w * 7, min(w * 7 + 7, self.nd)) for w in range(self.p.weeks)]

    # ------------------------------------------------------------ constraint types
    def _unavailable(self, c, lit):
        days = self.p.days
        for d, day in enumerate(days):
            hit = False
            if c.weekdays is not None and day.weekday() in c.weekdays:
                hit = True
            if c.date_range is not None and c.date_range[0] <= day <= c.date_range[1]:
                hit = True
            if c.weekdays is None and c.date_range is None:
                hit = True
            if hit:
                for s in self._people(c.person):
                    for t in self._shifts(c.shift):
                        self.m.Add(self.x[s, d, t] == 0).OnlyEnforceIf(lit)

    def _max_consecutive_days(self, c, lit):
        n = c.n
        for s in self._people(c.person):
            for d0 in range(0, self.nd - n):
                self.m.Add(sum(self._work(s, d) for d in range(d0, d0 + n + 1)) <= n).OnlyEnforceIf(lit)

    def _min_staff(self, c, lit):
        for d, day in enumerate(self.p.days):
            if c.weekdays is not None and day.weekday() not in c.weekdays:
                continue
            for t in self._shifts(c.shift):
                self.m.Add(sum(self.x[s, d, t] for s in self.sid) >= c.n).OnlyEnforceIf(lit)

    def _min_role(self, c, lit):
        role_ids = [s.id for s in self.p.staff if s.role == c.role]
        for d in range(self.nd):
            for t in self._shifts(c.shift):
                self.m.Add(sum(self.x[s, d, t] for s in role_ids) >= c.n).OnlyEnforceIf(lit)

    def _max_hours_week(self, c, lit):
        hours = {t.id: t.hours for t in self.p.shifts}
        for s in self._people(c.person):
            for wk in self._weeks():
                self.m.Add(sum(hours[t] * self.x[s, d, t] for d in wk for t in self.tid) <= c.hours).OnlyEnforceIf(lit)

    def _min_rest_hours(self, c, lit):
        sh = {t.id: t for t in self.p.shifts}
        after = self._shifts(c.after_shift)
        for d1 in range(self.nd):
            for a in after:
                start_a = 24 * d1 + sh[a].start
                end_a = start_a + sh[a].hours
                for d2 in range(d1, min(d1 + 3, self.nd)):
                    for b in self.tid:
                        start_b = 24 * d2 + sh[b].start
                        if start_b <= start_a or start_b - end_a >= c.hours:
                            continue
                        for s in self.sid:
                            self.m.Add(self.x[s, d1, a] + self.x[s, d2, b] <= 1).OnlyEnforceIf(lit)

    def _fixed_assignment(self, c, lit):
        days = self.p.days
        if c.date not in days:
            raise ValueError(f"date {c.date} is outside the planning horizon")
        d = days.index(c.date)
        for s in self._people(c.person):
            for t in self._shifts(c.shift):
                self.m.Add(self.x[s, d, t] == 1).OnlyEnforceIf(lit)

    def _max_shifts_week(self, c, lit):
        for s in self._people(c.person):
            for wk in self._weeks():
                self.m.Add(sum(self.x[s, d, t] for d in wk for t in self.tid) <= c.n).OnlyEnforceIf(lit)

    # ------------------------------------------------------------ objective / output
    def balance_objective(self):
        total = {s: sum(self.x[s, d, t] for d in range(self.nd) for t in self.tid) for s in self.sid}
        mx = self.m.NewIntVar(0, self.nd, "max_shifts")
        for s in self.sid:
            self.m.Add(total[s] <= mx)
        # minimise the busiest person's load first, then avoid over-staffing
        self.m.Minimize(1000 * mx + sum(total.values()))

    def change_objective(self, prev: Schedule):
        diffs = []
        for (s, d, t), var in self.x.items():
            was = s in prev.assignments.get(self.p.days[d].isoformat(), {}).get(t, [])
            diffs.append(1 - var if was else var)
            self.m.AddHint(var, 1 if was else 0)
        self.m.Minimize(sum(diffs))

    def to_schedule(self, solver: cp_model.CpSolver) -> Schedule:
        out = {}
        for d, day in enumerate(self.p.days):
            out[day.isoformat()] = {
                t: [s for s in self.sid if solver.Value(self.x[s, d, t])] for t in self.tid
            }
        return Schedule(assignments=out)


def _run(mm: _Model, active: list[str], timeout: float, workers: int = 8, first_only: bool = False):
    mm.m.ClearAssumptions()
    mm.m.AddAssumptions([mm.lit[i] for i in active])
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout
    solver.parameters.num_search_workers = workers
    solver.parameters.stop_after_first_solution = first_only
    status = solver.Solve(mm.m)
    return status, solver


def _feasible(problem: Problem, constraints: list, timeout: float) -> Optional[bool]:
    mm = _Model(problem, constraints)
    mm.balance_objective()  # with an objective CP-SAT uses its LP relaxation and proves infeasibility far faster
    status, _ = _run(mm, [c.id for c in constraints], timeout, first_only=True)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return True
    if status == cp_model.INFEASIBLE:
        return False
    return None  # unknown (timeout)


def minimize_core(problem: Problem, core: list, budget_s: float = 15.0) -> list:
    """Deletion-based shrinking: drop each rule whose removal keeps the set infeasible."""
    t0 = time.perf_counter()
    kept = list(core)
    for c in list(core):
        left = budget_s - (time.perf_counter() - t0)
        if left <= 0.5:
            break
        trial = [k for k in kept if k.id != c.id]
        if not trial:
            continue
        if _feasible(problem, trial, timeout=min(5.0, left)) is False:
            kept = trial
    return kept


def solve(problem: Problem, constraints: list, timeout: float = TIMEOUT_S, prev: Optional[Schedule] = None) -> dict:
    """Solve. Returns {status, schedule, core_ids, core, solve_seconds}."""
    ensure_ids(constraints)
    t0 = time.perf_counter()
    mm = _Model(problem, constraints)
    if prev is not None:
        mm.change_objective(prev)
    else:
        mm.balance_objective()
    status, solver = _run(mm, [c.id for c in constraints], timeout)
    res = {"status": solver.StatusName(status), "schedule": None, "core_ids": [], "core": [], "solve_seconds": 0.0}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        res["schedule"] = mm.to_schedule(solver)
    elif status == cp_model.INFEASIBLE:
        lit_to_id = {lit.Index(): cid for cid, lit in mm.lit.items()}
        raw_ids = [lit_to_id[i] for i in solver.SufficientAssumptionsForInfeasibility() if i in lit_to_id]
        by_id = {c.id: c for c in constraints}
        core = [by_id[i] for i in raw_ids] or list(constraints)
        core = minimize_core(problem, core)
        res["core"] = core
        res["core_ids"] = [c.id for c in core]
    res["solve_seconds"] = round(time.perf_counter() - t0, 3)
    return res
