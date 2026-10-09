"""Rules text (Azerbaijani / Russian / mixed) -> ParseResult.

The LLM only translates sentences into the 8 supported constraint types. It never
builds a schedule. Names are resolved to staff ids here in code, and every input
sentence is accounted for as exactly one of: constraint, ambiguous, unsupported.
"""
from __future__ import annotations

import difflib
import json
import re
import unicodedata
from typing import Literal, Optional

from pydantic import BaseModel, Field

from . import llm
from .schema import Ambiguous, Constraint, ParseResult, Problem, Unsupported

# ---------------------------------------------------------------- sentence split


def split_sentences(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        line = line.strip().lstrip("-*•").strip()
        if not line:
            continue
        out.extend(p.strip() for p in re.split(r"(?<=[.!?])\s+", line) if p.strip())
    return out


# ---------------------------------------------------------------- name resolution

_CYR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                ["a", "b", "v", "g", "d", "e", "o", "j", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s",
                 "t", "u", "f", "x", "ts", "c", "s", "s", "", "i", "", "e", "u", "a"]))
_AZ = {"ə": "e", "ı": "i", "ğ": "g", "ö": "o", "ü": "u", "ş": "s", "ç": "c", "kh": "x", "sh": "s", "ch": "c"}


def norm_name(s: str) -> str:
    s = s.lower().strip()
    s = "".join(_CYR.get(ch, ch) for ch in s)
    for a, b in _AZ.items():
        s = s.replace(a, b)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if ch.isalpha())
    return s.replace("a", "e")  # ə/a/e are written interchangeably across scripts


def resolve_person(mention: str, problem: Problem) -> Optional[str]:
    """Map a written name (any script, inflected, no diacritics) to a staff id, or None."""
    if mention.strip().lower() in ("all", "everyone", "*"):
        return "all"
    m = norm_name(mention)
    if not m:
        return None
    keys = {s.id: norm_name(s.name) for s in problem.staff}
    exact = [i for i, k in keys.items() if k == m]
    if len(exact) == 1:
        return exact[0]
    def common(a: str, b: str) -> int:
        n = 0
        while n < min(len(a), len(b)) and a[n] == b[n]:
            n += 1
        return n

    # inflected forms: "Aysel'in", "Лейлы", "Elnura" share all but the last letter of the name
    pref = [i for i, k in keys.items() if common(m, k) >= max(4, len(k) - 1)]
    if len(pref) == 1:
        return pref[0]
    scored = sorted(((difflib.SequenceMatcher(None, m, k).ratio(), i) for i, k in keys.items()), reverse=True)
    if scored and scored[0][0] >= 0.75 and (len(scored) == 1 or scored[1][0] < scored[0][0] - 0.1):
        return scored[0][1]
    return None


# ---------------------------------------------------------------- LLM contract


class _Item(BaseModel):
    index: int
    kind: Literal["constraint", "ambiguous", "unsupported"]
    constraints: list[Constraint] = Field(default_factory=list)
    question: Optional[str] = None
    reason: Optional[str] = None


class _Out(BaseModel):
    items: list[_Item]


SYSTEM = """You convert workplace shift rules written in Azerbaijani, Russian, English or a mix (possibly without diacritics, e.g. "cume" for "cümə") into structured constraints.
You NEVER produce a schedule. You only classify and translate each numbered sentence.

Supported constraint types (exactly these 8; JSON fields shown):
1. unavailable: {"type":"unavailable","person":NAME,"weekdays":[int]|null,"date_range":["YYYY-MM-DD","YYYY-MM-DD"]|null,"shift":SHIFT|null}
   person cannot work (optionally only a given shift) on those weekdays or dates.
2. max_consecutive_days: {"type":"max_consecutive_days","person":NAME|"all","n":int}
3. min_staff: {"type":"min_staff","shift":SHIFT|"all","n":int,"weekdays":[int]|null}
4. min_role: {"type":"min_role","shift":SHIFT|"all","role":"senior"|"junior","n":int}
5. max_hours_week: {"type":"max_hours_week","person":NAME|"all","hours":int}
6. min_rest_hours: {"type":"min_rest_hours","hours":int,"after_shift":SHIFT|null}   (null = after any shift)
7. fixed_assignment: {"type":"fixed_assignment","person":NAME,"date":"YYYY-MM-DD","shift":SHIFT}
8. max_shifts_week: {"type":"max_shifts_week","person":NAME|"all","n":int}

Conventions:
- weekdays: 0=Monday(bazar ertəsi/понедельник) 1=Tuesday(çərşənbə axşamı/вторник) 2=Wednesday(çərşənbə/среда) 3=Thursday(cümə axşamı/четверг) 4=Friday(cümə/пятница) 5=Saturday(şənbə/суббота) 6=Sunday(bazar/воскресенье).
  Careful: "çərşənbə axşamı" is Tuesday, plain "çərşənbə" is Wednesday; "cümə axşamı" is Thursday, plain "cümə" is Friday.
- SHIFT is one of the shift ids given below. səhər/утро=morning, axşam/вечер=evening, gecə/ночь=night.
- NAME: copy the person's name as written in the sentence, in its base form. Do not translate or correct it. Use "all" for heç kim / hamı / никто / все / nobody / everyone.
- "nobody more than N days in a row" -> max_consecutive_days n=N. "max N hours" -> max_hours_week. "N shifts a week" -> max_shifts_week.
- One sentence may produce several constraints (e.g. two people, or two weekdays) but they must all come from that sentence.

Classify every sentence as exactly one kind:
- "constraint": a hard rule that fits the 8 types exactly. Put the constraint(s) in "constraints".
- "ambiguous": a preference/wish ("doesn't like", "prefers", "sevmir", "не любит", "istəyir"), a vague amount ("enough people", "a few"), an unclear person or date. Write a short "question" for the manager in the sentence's language, e.g. "Is this a hard rule or just a preference?". NEVER guess.
- "unsupported": a clear rule that does not fit any of the 8 types (e.g. two people must/must not work together, fair weekend rotation, skills other than senior/junior, pay). Give a short "reason".

Return ONLY JSON: {"items":[{"index":int,"kind":"constraint"|"ambiguous"|"unsupported","constraints":[...],"question":str|null,"reason":str|null}, ...]} with one item per input sentence, same indexes.

Examples (staff in examples: Aysel, Elnur, Leyla, Nigar, Tural; horizon starts 2026-10-12):
[AZ] "Tural bazar günləri işləmir." -> {"index":1,"kind":"constraint","constraints":[{"type":"unavailable","person":"Tural","weekdays":[6],"date_range":null,"shift":null}]}
[AZ] "Hər səhər növbəsində ən azı 3 nəfər olsun." -> {"index":1,"kind":"constraint","constraints":[{"type":"min_staff","shift":"morning","n":3,"weekdays":null}]}
[RU] "Никто не должен работать больше 40 часов в неделю." -> {"index":1,"kind":"constraint","constraints":[{"type":"max_hours_week","person":"all","hours":40}]}
[RU] "Эльнур хочет поменьше ночных смен." -> {"index":1,"kind":"ambiguous","constraints":[],"question":"Это жёсткое правило или пожелание? Если правило, сколько ночных смен максимум?"}
[mixed] "Leyla 14-ü səhər smenada работает." -> {"index":1,"kind":"constraint","constraints":[{"type":"fixed_assignment","person":"Leyla","date":"2026-10-14","shift":"morning"}]}
[mixed, no diacritics] "Aysel cume gunleri gece novbesine cixa bilmez." -> {"index":1,"kind":"constraint","constraints":[{"type":"unavailable","person":"Aysel","weekdays":[4],"date_range":null,"shift":"night"}]}
[unsupported] "Nigar ile Tural eyni novbede olmasin." -> {"index":1,"kind":"unsupported","constraints":[],"reason":"'Two people not on the same shift' is not one of the 8 supported rule types yet."}
"""


def _user_prompt(sentences: list[str], problem: Problem) -> str:
    days = problem.days
    return (
        f"Staff names: {', '.join(s.name for s in problem.staff)}\n"
        f"Roles: {', '.join(f'{s.name}={s.role}' for s in problem.staff)}\n"
        f"Shift ids: {', '.join(f'{t.id} ({t.start:02d}-{t.end:02d})' for t in problem.shifts)}\n"
        f"Planning horizon: {days[0]} (Monday) to {days[-1]}. A bare day-of-month like 'the 14th' means that day inside the horizon.\n\n"
        "Sentences:\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(sentences, 1))
    )


def parse(text: str, problem: Problem) -> tuple[ParseResult, dict]:
    sentences = split_sentences(text)
    if not sentences:
        return ParseResult(), {"seconds": 0.0}
    out, meta = llm.complete_json(SYSTEM, _user_prompt(sentences, problem), _Out)
    return assemble(sentences, out, problem), meta


def assemble(sentences: list[str], out: _Out, problem: Problem) -> ParseResult:
    """Turn the LLM items into a ParseResult. Code, not the LLM, resolves names and
    guarantees each sentence lands in exactly one bucket."""
    res = ParseResult()
    by_index = {}
    for it in out.items:
        by_index.setdefault(it.index, it)
    shift_ids = {t.id for t in problem.shifts} | {"all"}
    n = 0
    for i, sent in enumerate(sentences, 1):
        it = by_index.get(i)
        if it is None:
            res.unsupported.append(Unsupported(source_text=sent, reason="The parser returned nothing for this sentence."))
            continue
        if it.kind == "ambiguous":
            res.ambiguous.append(Ambiguous(source_text=sent, question=it.question or "Please clarify this rule."))
            continue
        if it.kind == "unsupported" or not it.constraints:
            res.unsupported.append(Unsupported(source_text=sent, reason=it.reason or "Not one of the 8 supported rule types."))
            continue
        problem_q = None
        resolved = []
        for c in it.constraints:
            c = c.model_copy()
            if hasattr(c, "person"):
                pid = resolve_person(c.person, problem)
                if pid is None:
                    problem_q = f"Who is '{c.person}'? This name is not in the staff list."
                    break
                c.person = pid
            for f in ("shift", "after_shift"):
                if getattr(c, f, None) not in (None, *shift_ids):
                    problem_q = f"Which shift is '{getattr(c, f)}'?"
            if c.type == "fixed_assignment" and c.date not in problem.days:
                problem_q = f"The date {c.date} is outside the planning horizon. Which date did you mean?"
            if problem_q:
                break
            n += 1
            c.id = f"c{n}"
            c.source_text = sent
            resolved.append(c)
        if problem_q:
            res.ambiguous.append(Ambiguous(source_text=sent, question=problem_q))
        else:
            res.constraints.extend(resolved)
    return res


def to_json(res: ParseResult) -> str:
    return json.dumps(res.model_dump(mode="json"), ensure_ascii=False, indent=2)
