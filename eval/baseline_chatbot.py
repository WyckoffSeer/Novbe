"""Baseline: give the same rules to the LLM in a careful plain prompt and ask it for the rota.

The output is scored by the same independent verifier as Növbə.
"""
from __future__ import annotations

from pydantic import BaseModel

from novbe import llm
from novbe.schema import Problem, Schedule

SYSTEM = """You are a careful, experienced shift planner. Build a complete shift schedule that satisfies EVERY hard rule.
Think about each rule before answering and double-check the final schedule against every rule.
Rules about preferences or wishes are soft; ignore rules that are unclear or refer to people not on the team.
Return ONLY JSON of the form {"assignments": {"YYYY-MM-DD": {"morning": [staff ids], "evening": [...], "night": [...]}, ...}} covering every date."""


class _Out(BaseModel):
    assignments: dict[str, dict[str, list[str]]]


def prompt(problem: Problem, rules_text: str, base_n: int) -> str:
    days = problem.days
    return (
        "Staff (id, name, role):\n" + "\n".join(f"- {s.id}, {s.name}, {s.role}" for s in problem.staff) + "\n\n"
        "Shifts: " + ", ".join(f"{t.id} {t.start:02d}:00-{t.end:02d}:00 ({t.hours}h)" for t in problem.shifts) + "\n"
        f"Dates: {days[0]} (Monday) to {days[-1]}, {len(days)} days. Weeks run Monday-Sunday.\n\n"
        "Always-on rules:\n"
        "- A person works at most one shift per day.\n"
        f"- Every shift on every day needs at least {base_n} people.\n\n"
        "Manager's rules (Azerbaijani/Russian):\n" + rules_text + "\n\nUse staff ids in the output."
    )


def run(problem: Problem, rules_text: str, base_n: int) -> tuple[Schedule, dict]:
    out, meta = llm.complete_json(SYSTEM, prompt(problem, rules_text, base_n), _Out, max_tokens=16000)
    return Schedule(assignments=out.assignments), meta
