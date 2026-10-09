"""Build 30 synthetic evaluation cases with ground truth.

Ground-truth constraints are written FIRST, then rendered into rule text by templates in
four styles: Azerbaijani (az), Russian (ru), mixed AZ/RU (mixed) and Azerbaijani without
diacritics (noaz). Optionally (--paraphrase, needs an API key) each sentence is rewritten
informally by the LLM; a paraphrase is kept only if every number in it is preserved.

25 feasible cases + 5 genuinely infeasible cases (planted minimal conflict, checked with
the solver). 5 ambiguous sentences and 5 unsupported sentences are mixed in.

Usage: python -m eval.gen_cases [--paraphrase]
"""
from __future__ import annotations

import datetime as dt
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from novbe.schema import (  # noqa: E402
    FixedAssignment, MaxConsecutiveDays, MaxHoursWeek, MaxShiftsWeek, MinRestHours, MinRole, MinStaff,
    Problem, Staff, Unavailable, base_coverage,
)
from novbe.solver import solve  # noqa: E402

CASES = ROOT / "eval" / "cases"
START = dt.date(2026, 10, 12)
WEEKS = 2
BASE_N = 2

# (latin name, cyrillic name) — all fictional
NAMES = [("Aysel", "Айсель"), ("Elnur", "Эльнур"), ("Leyla", "Лейла"), ("Nigar", "Нигяр"), ("Tural", "Турал"),
         ("Rəşad", "Рашад"), ("Günel", "Гюнель"), ("Kamran", "Камран"), ("Sevinc", "Севиндж"), ("Orxan", "Орхан"),
         ("Lalə", "Лала"), ("Fərid", "Фарид"), ("Murad", "Мурад"), ("Səbinə", "Сабина"), ("Vüsal", "Вюсал"),
         ("Aynur", "Айнур")]
CYR = dict(NAMES)

AZ_DAY = ["bazar ertəsi", "çərşənbə axşamı", "çərşənbə", "cümə axşamı", "cümə", "şənbə", "bazar"]
RU_PO_DAY = ["по понедельникам", "по вторникам", "по средам", "по четвергам", "по пятницам", "по субботам", "по воскресеньям"]
AZ_SHIFT = {"morning": "səhər", "evening": "axşam", "night": "gecə"}
RU_SHIFT_ACC = {"morning": "утреннюю", "evening": "вечернюю", "night": "ночную"}
RU_SHIFT_LOC = {"morning": "утренней", "evening": "вечерней", "night": "ночной"}
AZ_ROLE = {"senior": "senior", "junior": "junior"}
RU_ROLE = {"senior": "старших (senior)", "junior": "младших (junior)"}
DIACRITICS = str.maketrans("əƏıİşŞçÇğĞöÖüÜ", "eEiIsScCgGoOuU")


def strip_az(s: str) -> str:
    return s.translate(DIACRITICS)


def nm(name: str, style: str) -> str:
    return CYR[name] if style == "ru" else (strip_az(name) if style == "noaz" else name)


# ---------------------------------------------------------------- rendering


def render(c, names: dict, style: str) -> str:
    """Ground-truth constraint -> sentence in the given style."""
    az = style in ("az", "noaz")
    ru = style == "ru"
    t = c.type
    who = names.get(getattr(c, "person", ""), "")
    W = lambda n: nm(n, style)  # noqa: E731
    if t == "unavailable":
        if c.date_range:
            d1, d2 = c.date_range
            if ru:
                s = f"{W(who)} в отпуске с {d1:%d.%m} по {d2:%d.%m}."
            elif style == "mixed":
                s = f"{W(who)} {d1:%d.%m}–{d2:%d.%m} отпуск-dadır, işləmir."
            else:
                s = f"{W(who)} {d1:%d.%m}-dən {d2:%d.%m}-dək məzuniyyətdədir."
        else:
            d = c.weekdays[0]
            if c.shift:
                if ru:
                    s = f"{W(who)} не может выходить в {RU_SHIFT_ACC[c.shift]} смену {RU_PO_DAY[d]}."
                elif style == "mixed":
                    s = f"{W(who)} {RU_PO_DAY[d]} {AZ_SHIFT[c.shift]} növbəsinə çıxa bilməz."
                else:
                    s = f"{W(who)} {AZ_DAY[d]} günləri {AZ_SHIFT[c.shift]} növbəsinə çıxa bilməz."
            else:
                if ru:
                    s = f"{W(who)} не может работать {RU_PO_DAY[d]}."
                elif style == "mixed":
                    s = f"{W(who)} {AZ_DAY[d]} günləri работать не может."
                else:
                    s = f"{W(who)} {AZ_DAY[d]} günləri işləyə bilməz."
    elif t == "max_consecutive_days":
        if c.person == "all":
            s = {"ru": f"Никто не должен работать больше {c.n} дней подряд.",
                 "mixed": f"Никто ardıcıl {c.n} gündən çox işləməsin."}.get(style, f"Heç kim ardıcıl {c.n} gündən çox işləməsin.")
        else:
            s = {"ru": f"{W(who)} может работать не больше {c.n} дней подряд.",
                 "mixed": f"{W(who)} максимум {c.n} gün ardıcıl işləyə bilər."}.get(style, f"{W(who)} ardıcıl {c.n} gündən çox işləməməlidir.")
    elif t == "min_staff":
        s = {"ru": f"В каждой {RU_SHIFT_LOC[c.shift]} смене должно быть минимум {c.n} человека.",
             "mixed": f"Hər {AZ_SHIFT[c.shift]} növbəsində минимум {c.n} человек olsun."}.get(
            style, f"Hər {AZ_SHIFT[c.shift]} növbəsində ən azı {c.n} nəfər olmalıdır.")
    elif t == "min_role":
        s = {"ru": f"В каждой {RU_SHIFT_LOC[c.shift]} смене минимум {c.n} {RU_ROLE[c.role]}.",
             "mixed": f"{AZ_SHIFT[c.shift].capitalize()} növbəsində минимум {c.n} {c.role} olsun."}.get(
            style, f"Hər {AZ_SHIFT[c.shift]} növbəsində ən azı {c.n} {AZ_ROLE[c.role]} olmalıdır.")
    elif t == "max_hours_week":
        if c.person == "all":
            s = {"ru": f"Никто не работает больше {c.hours} часов в неделю.",
                 "mixed": f"Heç kim həftədə {c.hours} часов-dan çox işləməsin."}.get(style, f"Heç kim həftədə {c.hours} saatdan çox işləməsin.")
        else:
            s = {"ru": f"{W(who)} — максимум {c.hours} часов в неделю.",
                 "mixed": f"{W(who)} в неделю maksimum {c.hours} saat işləyə bilər."}.get(style, f"{W(who)} həftədə maksimum {c.hours} saat işləyə bilər.")
    elif t == "min_rest_hours":
        if c.after_shift == "night":
            s = {"ru": f"После ночной смены минимум {c.hours} часов отдыха.",
                 "mixed": f"Gecə növbəsindən sonra минимум {c.hours} часов отдых olmalıdır."}.get(
                style, f"Gecə növbəsindən sonra ən azı {c.hours} saat istirahət olmalıdır.")
        else:
            s = {"ru": f"Между любыми сменами минимум {c.hours} часов отдыха.",
                 "mixed": f"Növbələr arasında минимум {c.hours} saat istirahət olsun."}.get(
                style, f"İstənilən iki növbə arasında ən azı {c.hours} saat istirahət olsun.")
    elif t == "fixed_assignment":
        d = c.date
        if ru:
            s = f"{W(who)} работает в {RU_SHIFT_ACC[c.shift]} смену {d.day} октября."
        elif style == "mixed":
            s = f"{W(who)} {d.day} октября {AZ_SHIFT[c.shift]} növbəsində işləyir."
        else:
            s = f"{W(who)} {d.day} oktyabrda {AZ_SHIFT[c.shift]} növbəsində işləyir."
    elif t == "max_shifts_week":
        if c.person == "all":
            s = {"ru": f"У каждого не больше {c.n} смен в неделю.",
                 "mixed": f"Hər kəs в неделю ən çox {c.n} növbə işləsin."}.get(style, f"Hər kəs həftədə ən çox {c.n} növbə işləsin.")
        else:
            s = {"ru": f"{W(who)} — не больше {c.n} смен в неделю.",
                 "mixed": f"{W(who)} həftədə не больше {c.n} смен işləsin."}.get(style, f"{W(who)} həftədə {c.n} növbədən çox işləməsin.")
    else:
        raise ValueError(t)
    return strip_az(s) if style == "noaz" else s


def ambiguous_sentence(rng, team_names: list[str], style: str) -> str:
    a = rng.choice(team_names)
    opts = {
        "az": [f"{a} gecə növbələrini sevmir.", f"{a} səhərləri işləməyi üstün tutur.", "Bazar günləri kifayət qədər adam olsun.",
               "Rauf cümə günləri işləyə bilməz."],
        "ru": [f"{CYR[a]} не любит ночные смены.", f"Хорошо бы, чтобы {CYR[a]} работал поменьше.",
               "Самир не может работать по пятницам."],
        "mixed": [f"{a} ночные смены sevmir.", f"{a} лучше səhər növbəsində olsun."],
    }
    pool = opts.get(style, opts["az"])
    s = rng.choice(pool)
    return strip_az(s) if style == "noaz" else s


def unsupported_sentence(rng, team_names: list[str], style: str) -> str:
    a, b = rng.sample(team_names, 2)
    opts = {
        "az": [f"{a} və {b} eyni növbədə işləməsin.", "Hər kəsə ayda iki bazar günü istirahət verilsin."],
        "ru": [f"{CYR[a]} и {CYR[b]} не должны работать в одной смене.", "Выходные нужно распределять по справедливости."],
        "mixed": [f"{a} и {b} eyni növbədə olmasın."],
    }
    s = rng.choice(opts.get(style, opts["az"]))
    return strip_az(s) if style == "noaz" else s


# ---------------------------------------------------------------- case building


def make_team(rng, size: int, seniors: int) -> list[Staff]:
    picks = rng.sample(NAMES, size)
    roles = ["senior"] * seniors + ["junior"] * (size - seniors)
    rng.shuffle(roles)
    return [Staff(id=f"p{i + 1:02d}", name=n, role=r) for i, ((n, _), r) in enumerate(zip(picks, roles))]


def random_constraint(rng, team: list[Staff]):
    p = rng.choice(team).id
    days = [START + dt.timedelta(days=i) for i in range(WEEKS * 7)]
    t = rng.choice(["unavailable", "unavailable", "max_consecutive_days", "min_staff", "min_role", "max_hours_week",
                    "min_rest_hours", "fixed_assignment", "max_shifts_week"])
    if t == "unavailable":
        if rng.random() < 0.2:
            d = rng.choice(days[:10])
            return Unavailable(person=p, date_range=(d, d + dt.timedelta(days=rng.randint(1, 3))))
        return Unavailable(person=p, weekdays=[rng.randint(0, 6)], shift=rng.choice([None, None, "morning", "evening", "night"]))
    if t == "max_consecutive_days":
        return MaxConsecutiveDays(person=rng.choice(["all", p]), n=rng.choice([4, 5, 6]))
    if t == "min_staff":
        return MinStaff(shift=rng.choice(["morning", "evening", "night"]), n=3)
    if t == "min_role":
        return MinRole(shift=rng.choice(["morning", "evening", "night"]), role="senior", n=rng.choice([1, 2]))
    if t == "max_hours_week":
        return MaxHoursWeek(person=rng.choice(["all", p]), hours=rng.choice([40, 48]) if rng.random() < 0.5 else 32)
    if t == "min_rest_hours":
        return MinRestHours(hours=rng.choice([11, 12, 16]), after_shift=rng.choice(["night", None]))
    if t == "fixed_assignment":
        return FixedAssignment(person=p, date=rng.choice(days), shift=rng.choice(["morning", "evening", "night"]))
    return MaxShiftsWeek(person=rng.choice(["all", p]), n=rng.choice([4, 5]) if rng.random() < 0.5 else 3)


def planted_conflict(kind: int, rng, team: list[Staff]):
    """Return a list of constraints that together (and only together) are infeasible."""
    seniors = [s.id for s in team if s.role == "senior"]
    juniors = [s.id for s in team if s.role == "junior"]
    p = rng.choice(juniors)
    if kind == 0:  # unavailable weekday vs fixed assignment that day
        wd = rng.randint(0, 6)
        return [Unavailable(person=p, weekdays=[wd]), FixedAssignment(person=p, date=START + dt.timedelta(days=wd + 7), shift="morning")]
    if kind == 1:  # every senior needed every night, but nobody may work >5 days in a row
        return [MinRole(shift="night", role="senior", n=len(seniors)), MaxConsecutiveDays(person="all", n=5)]
    if kind == 2:  # night then morning next day is too little rest
        d = START + dt.timedelta(days=rng.randint(1, 5))
        return [FixedAssignment(person=p, date=d, shift="night"), FixedAssignment(person=p, date=d + dt.timedelta(days=1), shift="morning"),
                MinRestHours(hours=11, after_shift="night")]
    if kind == 3:  # two seniors off Fridays leaves too few seniors for nights
        a, b = seniors[:2]
        return [MinRole(shift="night", role="senior", n=len(seniors) - 1), Unavailable(person=a, weekdays=[4]), Unavailable(person=b, weekdays=[4])]
    # kind 4: one shift a week but fixed on two days of the same week
    return [MaxShiftsWeek(person=p, n=1), FixedAssignment(person=p, date=START + dt.timedelta(days=1), shift="evening"),
            FixedAssignment(person=p, date=START + dt.timedelta(days=3), shift="morning")]


def problem_of(team) -> Problem:
    return Problem(staff=team, start_date=START, weeks=WEEKS)


def ids(cs, prefix="g"):
    for i, c in enumerate(cs, 1):
        c.id = f"{prefix}{i}"
    return cs


def build(seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    styles = ["az"] * 8 + ["ru"] * 8 + ["mixed"] * 7 + ["noaz"] * 7
    rng.shuffle(styles)
    infeasible_at = set(rng.sample(range(30), 5))
    amb_at = set(rng.sample(sorted(set(range(30)) - infeasible_at), 5))
    uns_at = set(rng.sample(sorted(set(range(30)) - infeasible_at), 5))
    cases, kind = [], 0
    for i, style in enumerate(styles):
        while True:
            size = rng.randint(9, 14)
            team = make_team(rng, size, seniors=3 if i in infeasible_at else rng.randint(4, 6))
            prob = problem_of(team)
            if i in infeasible_at:
                planted = planted_conflict(kind, rng, team)
                filler = []
                while len(filler) < rng.randint(1, 2):
                    c = random_constraint(rng, team)
                    if c.type not in {x.type for x in planted}:
                        filler.append(c)
                truth = ids(planted + filler)
                rng.shuffle(truth)
                base = base_coverage(prob, BASE_N)
                res = solve(prob, base + truth, timeout=10)
                if res["status"] != "INFEASIBLE":
                    continue
                # planted set must be minimal: dropping any planted rule makes everything feasible
                ok = all(solve(prob, base + [c for c in truth if c.id != x.id], timeout=10)["schedule"] is not None for x in planted)
                if not ok:
                    continue
                conflict = sorted(x.id for x in planted)
                kind += 1
            else:
                truth = ids([random_constraint(rng, team) for _ in range(rng.randint(3, 5))])
                res = solve(prob, base_coverage(prob, BASE_N) + truth, timeout=10)
                if res["schedule"] is None:
                    continue
                conflict = []
            break
        names = {s.id: s.name for s in team}
        sentences = [{"text": render(c, names, style), "expected": "constraint", "constraints": [c.model_dump(mode="json", exclude={"source_text"})]}
                     for c in truth]
        team_names = [s.name for s in team]
        if i in amb_at:
            sentences.insert(rng.randint(0, len(sentences)), {"text": ambiguous_sentence(rng, team_names, style), "expected": "ambiguous", "constraints": []})
        if i in uns_at:
            sentences.insert(rng.randint(0, len(sentences)), {"text": unsupported_sentence(rng, team_names, style), "expected": "unsupported", "constraints": []})
        cases.append({
            "id": f"case{i + 1:02d}", "style": style, "start_date": START.isoformat(), "weeks": WEEKS, "base_n": BASE_N,
            "staff": [s.model_dump() for s in team], "sentences": sentences,
            "infeasible": bool(conflict), "conflict_ids": conflict, "paraphrased": False,
        })
    return cases


PARA_SYSTEM = ("Rewrite the shift rule the way a busy shop manager would type it in a chat: informal, short, maybe a typo. "
               "Keep the same language mix ({style}: az=Azerbaijani, ru=Russian, mixed=Azerbaijani+Russian, noaz=Azerbaijani with no special letters). "
               "Keep EXACTLY the same meaning, the same person names, the same numbers, days and dates. Return only the rewritten sentence.")


def paraphrase(cases: list[dict]) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from novbe import llm

    def one(args):
        case, s = args
        try:
            out = llm.complete(PARA_SYSTEM.format(style=case["style"]), s["text"], max_tokens=200).strip().strip('"')
        except Exception:
            return
        if out and sorted(re.findall(r"\d+", out)) == sorted(re.findall(r"\d+", s["text"])):
            s["template_text"], s["text"] = s["text"], out
            case["paraphrased"] = True

    jobs = [(c, s) for c in cases for s in c["sentences"]]
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(one, jobs))


def main():
    cases = build()
    if "--paraphrase" in sys.argv:
        paraphrase(cases)
    CASES.mkdir(parents=True, exist_ok=True)
    for f in CASES.glob("case*.json"):
        f.unlink()
    for c in cases:
        (CASES / f"{c['id']}.json").write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
    n_amb = sum(s["expected"] == "ambiguous" for c in cases for s in c["sentences"])
    n_uns = sum(s["expected"] == "unsupported" for c in cases for s in c["sentences"])
    print(f"wrote {len(cases)} cases ({sum(c['infeasible'] for c in cases)} infeasible, {n_amb} ambiguous, {n_uns} unsupported sentences)")


if __name__ == "__main__":
    main()
