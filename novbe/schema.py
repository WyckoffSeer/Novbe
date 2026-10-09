"""Pydantic domain model for Növbə: problem, constraints, parse results, schedules, reports."""
from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator

Role = Literal["senior", "junior"]
WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class Staff(BaseModel):
    id: str
    name: str
    role: Role


class Shift(BaseModel):
    id: str
    name: str
    start: int  # hour of day, 0-23
    end: int  # hour of day; end <= start means it ends the next day
    hours: int


DEFAULT_SHIFTS = [
    Shift(id="morning", name="Morning", start=7, end=15, hours=8),
    Shift(id="evening", name="Evening", start=15, end=23, hours=8),
    Shift(id="night", name="Night", start=23, end=7, hours=8),
]


class Problem(BaseModel):
    staff: list[Staff]
    shifts: list[Shift] = Field(default_factory=lambda: [s.model_copy() for s in DEFAULT_SHIFTS])
    start_date: dt.date
    weeks: int = 4

    @field_validator("start_date")
    @classmethod
    def _monday(cls, v: dt.date) -> dt.date:
        if v.weekday() != 0:
            raise ValueError("start_date must be a Monday")
        return v

    @property
    def days(self) -> list[dt.date]:
        return [self.start_date + dt.timedelta(days=i) for i in range(self.weeks * 7)]

    def shift(self, shift_id: str) -> Shift:
        for s in self.shifts:
            if s.id == shift_id:
                return s
        raise KeyError(shift_id)


# ---------------------------------------------------------------- constraints
# `person` is a staff id or "all". `shift` is a shift id or "all".
# `weekdays` are 0=Mon .. 6=Sun.


class _Base(BaseModel):
    id: str = ""
    source_text: str = ""


class Unavailable(_Base):
    type: Literal["unavailable"] = "unavailable"
    person: str
    weekdays: Optional[list[int]] = None
    date_range: Optional[tuple[dt.date, dt.date]] = None
    shift: Optional[str] = None


class MaxConsecutiveDays(_Base):
    type: Literal["max_consecutive_days"] = "max_consecutive_days"
    person: str = "all"
    n: int


class MinStaff(_Base):
    type: Literal["min_staff"] = "min_staff"
    shift: str
    n: int
    weekdays: Optional[list[int]] = None


class MinRole(_Base):
    type: Literal["min_role"] = "min_role"
    shift: str
    role: Role
    n: int


class MaxHoursWeek(_Base):
    type: Literal["max_hours_week"] = "max_hours_week"
    person: str = "all"
    hours: int


class MinRestHours(_Base):
    type: Literal["min_rest_hours"] = "min_rest_hours"
    hours: int
    after_shift: Optional[str] = None  # only rest after this shift; None = after any shift


class FixedAssignment(_Base):
    type: Literal["fixed_assignment"] = "fixed_assignment"
    person: str
    date: dt.date
    shift: str


class MaxShiftsWeek(_Base):
    type: Literal["max_shifts_week"] = "max_shifts_week"
    person: str = "all"
    n: int


Constraint = Annotated[
    Union[
        Unavailable,
        MaxConsecutiveDays,
        MinStaff,
        MinRole,
        MaxHoursWeek,
        MinRestHours,
        FixedAssignment,
        MaxShiftsWeek,
    ],
    Field(discriminator="type"),
]

CONSTRAINT_TYPES = [
    "unavailable",
    "max_consecutive_days",
    "min_staff",
    "min_role",
    "max_hours_week",
    "min_rest_hours",
    "fixed_assignment",
    "max_shifts_week",
]


class ConstraintList(BaseModel):
    constraints: list[Constraint]


class Ambiguous(BaseModel):
    source_text: str
    question: str


class Unsupported(BaseModel):
    source_text: str
    reason: str


class ParseResult(BaseModel):
    constraints: list[Constraint] = Field(default_factory=list)
    ambiguous: list[Ambiguous] = Field(default_factory=list)
    unsupported: list[Unsupported] = Field(default_factory=list)


class Schedule(BaseModel):
    # assignments[date_iso][shift_id] -> list of staff ids
    assignments: dict[str, dict[str, list[str]]]

    def works(self, staff_id: str, day: dt.date) -> Optional[str]:
        """Return the first shift id this person works on `day`, or None."""
        for shift_id, people in self.assignments.get(day.isoformat(), {}).items():
            if staff_id in people:
                return shift_id
        return None


class Violation(BaseModel):
    constraint_id: str
    date: Optional[str] = None
    detail: str


class VerifyReport(BaseModel):
    violations: list[Violation] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations


def base_coverage(problem: Problem, n: int = 2) -> list[MinStaff]:
    """Implicit default coverage so an empty rule set still yields a staffed rota."""
    return [
        MinStaff(id=f"base-{s.id}", shift=s.id, n=n, source_text=f"(default) at least {n} people on every {s.name.lower()} shift")
        for s in problem.shifts
    ]


def describe(c, problem: Optional[Problem] = None) -> str:
    """Short English meaning of a constraint, for the confirmation table."""
    names = {s.id: s.name for s in problem.staff} if problem else {}
    who = lambda p: "everyone" if p == "all" else names.get(p, p)  # noqa: E731
    sh = lambda s: "every shift" if s in (None, "all") else f"{s} shift"  # noqa: E731
    wd = lambda w: ", ".join(WEEKDAY_NAMES[i] for i in w)  # noqa: E731
    t = c.type
    if t == "unavailable":
        when = f"on {wd(c.weekdays)}" if c.weekdays else f"from {c.date_range[0]} to {c.date_range[1]}" if c.date_range else "always"
        return f"{who(c.person)} cannot work {sh(c.shift)} {when}"
    if t == "max_consecutive_days":
        return f"{who(c.person)}: at most {c.n} consecutive working days"
    if t == "min_staff":
        return f"at least {c.n} people on {sh(c.shift)}" + (f" on {wd(c.weekdays)}" if c.weekdays else "")
    if t == "min_role":
        return f"at least {c.n} {c.role}(s) on {sh(c.shift)}"
    if t == "max_hours_week":
        return f"{who(c.person)}: at most {c.hours} hours per week"
    if t == "min_rest_hours":
        return f"at least {c.hours} hours rest after " + ("any shift" if not c.after_shift else f"a {c.after_shift} shift")
    if t == "fixed_assignment":
        return f"{who(c.person)} works {c.shift} on {c.date}"
    if t == "max_shifts_week":
        return f"{who(c.person)}: at most {c.n} shifts per week"
    return t
