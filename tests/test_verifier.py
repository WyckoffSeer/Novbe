"""One passing and one failing example for each of the 8 constraint types."""
import datetime as dt

import pytest

from novbe.schema import (
    FixedAssignment,
    MaxConsecutiveDays,
    MaxHoursWeek,
    MaxShiftsWeek,
    MinRestHours,
    MinRole,
    MinStaff,
    Problem,
    Schedule,
    Staff,
    Unavailable,
)
from novbe.verifier import verify

MON = dt.date(2026, 10, 12)


@pytest.fixture
def problem():
    return Problem(
        staff=[Staff(id="a", name="A", role="senior"), Staff(id="b", name="B", role="junior")],
        start_date=MON,
        weeks=1,
    )


def sched(rows):
    """rows: {(day_offset, shift): [people]} -> Schedule over one week."""
    out = {}
    for i in range(7):
        key = (MON + dt.timedelta(days=i)).isoformat()
        out[key] = {"morning": [], "evening": [], "night": []}
    for (i, shift), people in rows.items():
        out[(MON + dt.timedelta(days=i)).isoformat()][shift] = people
    return Schedule(assignments=out)


def check(problem, rows, c):
    c.id = "t"
    return verify(problem, sched(rows), [c])


def test_unavailable(problem):
    c = Unavailable(person="a", weekdays=[4])  # Fridays
    assert check(problem, {(3, "morning"): ["a"]}, c).ok
    rep = check(problem, {(4, "morning"): ["a"]}, c)
    assert not rep.ok and rep.violations[0].constraint_id == "t"


def test_unavailable_shift_only(problem):
    c = Unavailable(person="a", weekdays=[2], shift="morning")
    assert check(problem, {(2, "evening"): ["a"]}, c).ok
    assert not check(problem, {(2, "morning"): ["a"]}, c).ok


def test_max_consecutive_days(problem):
    c = MaxConsecutiveDays(person="all", n=3)
    assert check(problem, {(i, "morning"): ["a"] for i in (0, 1, 2, 4, 5, 6)}, c).ok
    assert not check(problem, {(i, "morning"): ["a"] for i in (0, 1, 2, 3)}, c).ok


def test_min_staff(problem):
    c = MinStaff(shift="night", n=2)
    assert check(problem, {(i, "night"): ["a", "b"] for i in range(7)}, c).ok
    assert not check(problem, {(i, "night"): ["a", "b"] for i in range(6)}, c).ok


def test_min_role(problem):
    c = MinRole(shift="night", role="senior", n=1)
    assert check(problem, {(i, "night"): ["a"] for i in range(7)}, c).ok
    assert not check(problem, {(i, "night"): ["b"] for i in range(7)}, c).ok


def test_max_hours_week(problem):
    c = MaxHoursWeek(person="all", hours=32)
    assert check(problem, {(i, "morning"): ["a"] for i in range(4)}, c).ok
    assert not check(problem, {(i, "morning"): ["a"] for i in range(5)}, c).ok


def test_min_rest_hours(problem):
    c = MinRestHours(hours=11, after_shift="night")
    assert check(problem, {(0, "night"): ["a"], (1, "night"): ["a"]}, c).ok  # 16h rest
    assert not check(problem, {(0, "night"): ["a"], (1, "evening"): ["a"]}, c).ok  # 8h rest


def test_fixed_assignment(problem):
    c = FixedAssignment(person="b", date=MON + dt.timedelta(days=2), shift="morning")
    assert check(problem, {(2, "morning"): ["b"]}, c).ok
    assert not check(problem, {(2, "evening"): ["b"]}, c).ok


def test_max_shifts_week(problem):
    c = MaxShiftsWeek(person="b", n=2)
    assert check(problem, {(0, "morning"): ["b"], (3, "night"): ["b"]}, c).ok
    assert not check(problem, {(i, "morning"): ["b"] for i in range(3)}, c).ok


def test_structural_two_shifts_one_day(problem):
    rep = verify(problem, sched({(0, "morning"): ["a"], (0, "night"): ["a"]}), [])
    assert not rep.ok and rep.violations[0].constraint_id == "structural"
