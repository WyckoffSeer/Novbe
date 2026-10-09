"""Plain-language explanations of verified facts.

The LLM only rephrases facts computed in code. Any number in its output that is not in
the input facts makes us fall back to a fixed template sentence.
"""
from __future__ import annotations

import json
import re

from . import llm

AZ_CHARS = set("əğışçöüƏĞİŞÇÖÜ")


def detect_lang(text: str) -> str:
    cyr = sum(1 for ch in text if "Ѐ" <= ch <= "ӿ")
    az = sum(1 for ch in text if ch in AZ_CHARS)
    if cyr > az:
        return "ru"
    if az:
        return "az"
    return "az" if re.search(r"\b(novbe|gece|seher|heç|hec|gun|bilmez)\b", text.lower()) else "en"


def numbers_ok(output: str, facts: str) -> bool:
    allowed = set(re.findall(r"\d+", facts))
    return all(n in allowed for n in re.findall(r"\d+", output))


# ---------------------------------------------------------------- templates

def conflict_template(rules: list[str], lang: str) -> str:
    joined = "; ".join(f"«{r}»" for r in rules)
    if lang == "ru":
        return f"Эти правила нельзя выполнить одновременно: {joined}. Ослабьте или уберите одно из них."
    if lang == "az":
        return f"Bu qaydalar eyni vaxtda ödənilə bilməz: {joined}. Onlardan birini yumşaldın və ya silin."
    return f"These rules cannot all hold at once: {joined}. Relax or remove one of them."


def changes_template(changes: list[dict], lang: str) -> str:
    parts = [f"{c['date']} {c['shift']}: {c['from'] or '-'} → {c['to'] or '-'}" for c in changes]
    body = "; ".join(parts)
    if lang == "ru":
        return f"Изменено смен: {len(changes)}. {body}." if changes else "Изменений не потребовалось."
    if lang == "az":
        return f"Dəyişən növbələr: {len(changes)}. {body}." if changes else "Heç bir dəyişiklik lazım olmadı."
    return f"Changed shifts: {len(changes)}. {body}." if changes else "No changes were needed."


# ---------------------------------------------------------------- LLM phrasing

SYSTEM = (
    "You explain the result of a shift-scheduling solver to a shop manager. "
    "Write 1-3 short plain sentences in the requested language (az = Azerbaijani, ru = Russian, en = English). "
    "Use ONLY the facts given. Do not add any number, date, name or rule that is not in the facts. "
    "Return only the sentences."
)


def _phrase(kind: str, facts: dict, fallback: str, use_llm: bool) -> tuple[str, str]:
    """Returns (text, source) where source is 'llm' or 'template'."""
    if not use_llm or not llm.available():
        return fallback, "template"
    facts_json = json.dumps(facts, ensure_ascii=False)
    try:
        out = llm.complete(SYSTEM, f"Kind: {kind}\nLanguage: {facts['lang']}\nFacts: {facts_json}", max_tokens=400).strip()
    except Exception:
        return fallback, "template"
    if not out or not numbers_ok(out, facts_json):
        return fallback, "template"
    return out, "llm"


def explain_conflict(core: list, lang: str, use_llm: bool = True) -> tuple[str, str]:
    rules = [c.source_text or c.id for c in core]
    facts = {"lang": lang, "status": "no schedule satisfies all rules", "conflicting_rules": rules,
             "advice": "relax or remove one of the conflicting rules"}
    return _phrase("conflict", facts, conflict_template(rules, lang), use_llm)


def explain_changes(changed: list[tuple], names: dict, lang: str, use_llm: bool = True) -> tuple[str, str]:
    ch = [{"date": d, "shift": s, "from": names.get(a, a), "to": names.get(b, b)} for d, s, a, b in changed]
    facts = {"lang": lang, "number_of_changed_shifts": len(ch), "changes": ch,
             "note": "all other assignments are unchanged and every rule is still satisfied"}
    return _phrase("repair", facts, changes_template(ch, lang), use_llm)
