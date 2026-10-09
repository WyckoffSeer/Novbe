import datetime as dt

from novbe.data import load_problem
from novbe.schema import (
    FixedAssignment,
    MaxConsecutiveDays,
    MaxHoursWeek,
    MinRestHours,
    MinRole,
    MinStaff,
    Unavailable,
    base_coverage,
)
from novbe.solver import solve
from novbe.verifier import verify


def demo_constraints(p):
    ids = {s.name: s.id for s in p.staff}
    return base_coverage(p) + [
        Unavailable(id="r1", person=ids["Aysel"], weekdays=[4]),
        MinRole(id="r2", shift="night", role="senior", n=2),
        MaxConsecutiveDays(id="r3", person="all", n=5),
        Unavailable(id="r4", person=ids["Elnur"], weekdays=[2], shift="morning"),
        Unavailable(id="r5", person=ids["Leyla"], weekdays=[5]),
        MinRestHours(id="r6", hours=11, after_shift="night"),
    ]


def test_demo_rules_solve_with_zero_violations():
    p = load_problem()
    cs = demo_constraints(p)
    res = solve(p, cs)
    assert res["schedule"] is not None, res["status"]
    rep = verify(p, res["schedule"], cs)
    assert rep.ok, rep.violations[:5]


def test_infeasible_returns_core_naming_the_clash():
    p = load_problem(weeks=1)
    cs = base_coverage(p) + [
        MinStaff(id="many", shift="night", n=6),
        MaxHoursWeek(id="hrs", person="all", hours=16),
        MaxConsecutiveDays(id="cons", person="all", n=5),
    ]
    res = solve(p, cs)
    assert res["status"] == "INFEASIBLE"
    assert set(res["core_ids"]) >= {"many", "hrs"}
    assert "cons" not in res["core_ids"]


def test_fixed_vs_unavailable_core():
    p = load_problem(weeks=1)
    day = p.start_date + dt.timedelta(days=4)  # Friday
    cs = [
        Unavailable(id="u", person="s01", weekdays=[4]),
        FixedAssignment(id="f", person="s01", date=day, shift="morning"),
        MinStaff(id="m", shift="evening", n=1),
    ]
    res = solve(p, cs)
    assert res["status"] == "INFEASIBLE"
    assert sorted(res["core_ids"]) == ["f", "u"]
