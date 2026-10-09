"""Növbə — Streamlit UI. Rules in, provably rule-following rota out."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from novbe import llm
from novbe.data import demo_rules, load_problem, offline_demo_parse
from novbe.explain import detect_lang, explain_changes, explain_conflict
from novbe.parser import parse
from novbe.repair import repair
from novbe.schema import WEEKDAY_NAMES, Problem, Staff, Unavailable, base_coverage, describe
from novbe.solver import solve
from novbe.verifier import verify

st.set_page_config(page_title="Növbə", page_icon="🗓️", layout="wide")
S = st.session_state
SHIFT_LETTER = {"morning": "M", "evening": "E", "night": "N"}
SHIFT_COLOR = {"M": "#fff3c4", "E": "#cfe8ff", "N": "#d9d2f5"}

# ---------------------------------------------------------------- sidebar
default = load_problem()
with st.sidebar:
    st.header("Settings")
    start = st.date_input("First Monday", default.start_date)
    weeks = st.number_input("Weeks", 1, 8, default.weeks)
    base_n = st.number_input("Default people per shift", 0, 6, 2,
                             help="Implicit coverage rule added to every plan; shown in the confirmation table.")
    st.divider()
    st.caption(f"Model: `{llm.model_name()}`")
    st.caption("API key: " + ("set ✅" if llm.available() else "missing ❌ (set ANTHROPIC_API_KEY)"))
    st.caption("Synthetic data only. Nothing is stored beyond this session.")

st.title("🗓️ Növbə")
st.markdown("Write shift rules in **Azerbaijani, Russian or both**. The AI only *reads* the rules; "
            "a constraint solver builds the rota and an independent checker proves every rule holds.")

# ---------------------------------------------------------------- step 1: inputs
st.subheader("1 · Team and rules")
c1, c2 = st.columns([2, 3])
with c1:
    staff_df = st.data_editor(
        pd.DataFrame([s.model_dump() for s in default.staff]),
        column_config={"role": st.column_config.SelectboxColumn("role", options=["senior", "junior"], required=True)},
        num_rows="dynamic", hide_index=True, key="staff_editor", height=460,
    )
with c2:
    rules_text = st.text_area("Rules (one per line)", demo_rules(), height=300, key="rules")
    parse_clicked = st.button("🔍 Parse rules", type="primary", disabled=not llm.available())
    if not llm.available():
        st.warning("Set ANTHROPIC_API_KEY (or a .env file) to parse rules.")
        offline_clicked = st.button("Offline fallback: load hand-written constraints for the demo rules (no AI)")
    else:
        offline_clicked = False


def current_problem() -> Problem:
    if start.weekday() != 0:
        st.error("The first day must be a Monday.")
        st.stop()
    staff = [Staff(id=str(r["id"]), name=str(r["name"]), role=r["role"])
             for r in staff_df.to_dict("records") if r.get("id") and r.get("name")]
    return Problem(staff=staff, start_date=start, weeks=int(weeks))


if parse_clicked:
    problem = current_problem()
    with st.spinner("Reading the rules…"):
        try:
            pr, meta = parse(rules_text, problem)
        except Exception as e:  # fail loudly, never silently
            st.error(f"Parsing failed: {e}")
            st.stop()
    S.problem, S.parse, S.parse_seconds = problem, pr, meta["seconds"]
    S.extra = []          # constraints added by answering ambiguous questions
    S.resolved = set()    # ambiguous sentences the manager has answered
    S.result = S.prev = S.changed = S.explanation = None

if offline_clicked:
    problem = current_problem()
    S.problem, S.parse, S.parse_seconds = problem, offline_demo_parse(problem), 0.0
    S.extra, S.resolved = [], set()
    S.result = S.prev = S.changed = S.explanation = None

if "parse" not in S:
    st.stop()

problem: Problem = S.problem
pr = S.parse
names = {s.id: s.name for s in problem.staff}

# ---------------------------------------------------------------- step 2: confirm
st.subheader("2 · Check what was understood")
st.caption(f"Parsed in {S.parse_seconds:.1f}s. Nothing is solved until you confirm.")

all_constraints = base_coverage(problem, int(base_n)) + pr.constraints + S.extra
rows = [{"use": True, "id": c.id, "your sentence": c.source_text, "meaning": describe(c, problem), "type": c.type}
        for c in all_constraints]
confirm = st.data_editor(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                         disabled=["id", "your sentence", "meaning", "type"], key=f"confirm_{len(rows)}")
chosen_ids = set(confirm.loc[confirm["use"], "id"])

open_amb = [a for a in pr.ambiguous if a.source_text not in S.resolved]
if open_amb:
    st.markdown("**Needs your answer** (not used until you decide):")
for k, a in enumerate(open_amb):
    with st.container(border=True):
        st.markdown(f"“{a.source_text}”  \n❓ {a.question}")
        b1, b2, b3, b4 = st.columns([1, 1.4, 3, 0.8])
        hard = b1.button("Hard rule", key=f"hard_{k}")
        skip = b2.button("Just a preference — ignore", key=f"skip_{k}")
        note = b3.text_input("Clarify", key=f"clar_{k}", label_visibility="collapsed",
                             placeholder="…or clarify in your own words")
        send = b4.button("Send", key=f"send_{k}")
        if skip:
            S.resolved.add(a.source_text)
            st.rerun()
        if hard or (send and note.strip()):
            hint = note.strip() if send else "Manager's answer: this is a HARD rule, it must always hold. / Bu qəti qaydadır. / Это обязательное правило."
            with st.spinner("Re-reading with your answer…"):
                sub, _ = parse(f"{a.source_text} ({hint})", problem)
            if sub.constraints:
                for c in sub.constraints:
                    c.id = f"a{len(S.extra) + 1}"
                    c.source_text = a.source_text
                    S.extra.append(c)
                S.resolved.add(a.source_text)
                st.rerun()
            else:
                st.warning(sub.ambiguous[0].question if sub.ambiguous
                           else sub.unsupported[0].reason if sub.unsupported else "Still unclear.")

if pr.unsupported:
    st.markdown("**Not supported yet** (shown, not silently dropped):")
    for u in pr.unsupported:
        st.markdown(f"- “{u.source_text}” — _{u.reason}_")

if st.button("🧮 Build schedule", type="primary"):
    used = [c for c in all_constraints if c.id in chosen_ids]
    with st.spinner("Solving…"):
        res = solve(problem, used)
    S.used, S.result, S.prev, S.changed = used, res, res["schedule"], None
    S.lang = detect_lang(rules_text)
    S.explanation = explain_conflict(res["core"], S.lang) if res["status"] == "INFEASIBLE" else None

if not S.get("result"):
    st.stop()

# ---------------------------------------------------------------- step 3: result
st.subheader("3 · Schedule")
res = S.result


def grid(schedule, changed_cells=frozenset()):
    days = problem.days
    data = {}
    for s in problem.staff:
        row = []
        for d in days:
            sh = schedule.works(s.id, d)
            row.append(SHIFT_LETTER.get(sh, sh) if sh else "")
        data[f"{s.name} ({s.role[0].upper()})"] = row
    cols = [f"{WEEKDAY_NAMES[d.weekday()]} {d.day:02d}" for d in days]
    df = pd.DataFrame.from_dict(data, orient="index", columns=cols)
    ids = [s.id for s in problem.staff]

    def style(_):
        out = pd.DataFrame("", index=df.index, columns=df.columns)
        for i, sid in enumerate(ids):
            for j, d in enumerate(days):
                v = df.iat[i, j]
                css = f"background-color:{SHIFT_COLOR[v]};" if v in SHIFT_COLOR else ""
                if (sid, d.isoformat()) in changed_cells:
                    css += "outline:3px solid #e4572e;font-weight:700;"
                out.iat[i, j] = css + "text-align:center;"
        return out

    return df.style.apply(style, axis=None)


if res["status"] == "INFEASIBLE":
    text, source = S.explanation
    st.error("No schedule can satisfy all confirmed rules.")
    st.markdown(f"**Why:** {text}")
    st.caption(f"Explanation source: {source}. The conflicting rules were found by the solver (infeasibility core), not guessed.")
    st.table(pd.DataFrame([{"id": c.id, "your sentence": c.source_text, "meaning": describe(c, problem)} for c in res["core"]]))
    st.stop()
if res["schedule"] is None:
    st.error(f"Solver status {res['status']} — no schedule found within the time limit.")
    st.stop()

schedule = S.prev
report = verify(problem, schedule, S.used)
m1, m2, m3 = st.columns(3)
if report.ok:
    m1.success(f"✅ 0 rule violations (independent check of {len(S.used)} rules)")
else:
    m1.error(f"❌ {len(report.violations)} violations found by the independent check")
m2.metric("Solve time", f"{res['solve_seconds']:.2f}s")
m3.metric("Solver status", res["status"])
if not report.ok:
    st.dataframe(pd.DataFrame([v.model_dump() for v in report.violations]))

changed_cells = set()
for d, _s, a, b in S.changed or []:
    for p in (a, b):
        if p:
            changed_cells.add((p, d))
st.dataframe(grid(schedule, frozenset(changed_cells)), use_container_width=True, height=36 * (len(problem.staff) + 1) + 4)
st.caption("M = morning 07–15 · E = evening 15–23 · N = night 23–07 · (S)/(J) = senior/junior")

if S.changed is not None:
    text, source = S.repair_expl
    st.info(f"**Repair:** {text}")
    st.caption(f"{len(S.changed)} seat(s) changed, outlined in red. Explanation source: {source}.")

# ---------------------------------------------------------------- absence repair
st.subheader("Report an absence")
a1, a2, a3, a4 = st.columns([2, 2, 2, 1])
who = a1.selectbox("Who", problem.staff, format_func=lambda s: s.name)
day = a2.selectbox("Day", problem.days, format_func=lambda d: f"{WEEKDAY_NAMES[d.weekday()]} {d.isoformat()}")
shift = a3.selectbox("Shift", ["all", *[t.id for t in problem.shifts]])
if a4.button("Repair", type="primary"):
    absence = Unavailable(person=who.id, date_range=(day, day), shift=None if shift == "all" else shift,
                          source_text=f"{who.name} is absent on {day.isoformat()}" + ("" if shift == "all" else f" ({shift})"))
    with st.spinner("Re-planning with as few changes as possible…"):
        rr = repair(problem, S.used, S.prev, [absence])
    if rr["schedule"] is None:
        S.result = rr
        S.explanation = explain_conflict(rr["core"], S.lang)
    else:
        S.used = S.used + [absence]
        S.prev, S.changed = rr["schedule"], rr["changed"]
        S.result = rr
        S.repair_expl = explain_changes(rr["changed"], names, S.lang)
    st.rerun()
