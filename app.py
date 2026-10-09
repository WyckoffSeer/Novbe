"""Növbə — Streamlit UI. Rules in, provably rule-following rota out.

UI only: parsing (novbe.parser), solving (novbe.solver), checking (novbe.verifier) and
repair (novbe.repair) are unchanged; presentation lives in novbe.ui.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from novbe import llm, ui
from novbe.data import demo_rules, load_problem, offline_demo_parse
from novbe.explain import detect_lang, explain_changes, explain_conflict
from novbe.parser import parse, split_sentences
from novbe.repair import repair
from novbe.schema import WEEKDAY_NAMES, Problem, Staff, Unavailable, base_coverage, describe
from novbe.solver import solve
from novbe.verifier import verify

st.set_page_config(page_title="Növbə — shift rules to rota", page_icon="🗓️", layout="wide")
st.markdown(ui.CSS, unsafe_allow_html=True)
S = st.session_state
IMPOSSIBLE_RULE = "Hər gecə növbəsində ən azı 7 senior olmalıdır."

# ---------------------------------------------------------------- sidebar
default = load_problem()
with st.sidebar:
    st.markdown("### ⚙️ Planning settings")
    start = st.date_input("First day (a Monday)", default.start_date)
    weeks = st.number_input("Weeks to plan", 1, 8, default.weeks)
    base_n = st.number_input("Default people per shift", 0, 6, 2,
                             help="An always-on coverage rule. It appears in the confirmation table so you can see and untick it.")
    st.divider()
    st.markdown("**AI model**")
    st.caption(f"`{llm.model_name()}` · temperature 0")
    if llm.available():
        st.success("API key found", icon="🔑")
    else:
        st.warning("No API key — set `ANTHROPIC_API_KEY` or a `.env` file. The offline demo still works.", icon="🔑")
    st.divider()
    st.caption("🔒 Synthetic data only. Nothing is stored or logged beyond this browser session.")

stage = 3 if S.get("result") else 2 if "parse" in S else 1
st.markdown(ui.hero(), unsafe_allow_html=True)
st.markdown(ui.stepper(stage), unsafe_allow_html=True)

# ---------------------------------------------------------------- step 1: inputs
st.markdown(ui.section(1, "Team and rules", "Edit the team on the left, write rules on the right — one per line, in any mix of Azerbaijani and Russian."),
            unsafe_allow_html=True)
if "rules" not in S:
    S.rules = demo_rules()

c1, c2 = st.columns([2, 3], gap="large")
with c1:
    staff_df = st.data_editor(
        pd.DataFrame([s.model_dump() for s in default.staff]),
        column_config={
            "id": st.column_config.TextColumn("ID", width="small", required=True),
            "name": st.column_config.TextColumn("Name", required=True),
            "role": st.column_config.SelectboxColumn("Role", options=["senior", "junior"], required=True),
        },
        num_rows="dynamic", hide_index=True, key="staff_editor", height=455, use_container_width=True,
    )
with c2:
    st.text_area("Rules", key="rules", height=290, label_visibility="collapsed",
                 placeholder="e.g. Aysel cümə günləri işləyə bilməz.\nЛейла не может работать по субботам.")
    rules_text = S.rules
    n_sent = len(split_sentences(rules_text))
    st.caption(f"{n_sent} sentence(s) · each one will end up as a rule, a question for you, or “not supported yet” — never silently dropped.")
    b1, b2, b3 = st.columns([1.2, 1, 1])
    parse_clicked = b1.button("🔍 Read the rules", type="primary", use_container_width=True,
                              disabled=not llm.available() or n_sent == 0)
    if b2.button("↺ Demo rules", use_container_width=True, help="Restore the 7 demo sentences"):
        S.rules = demo_rules()
        st.rerun()
    if b3.button("⚡ Add a clash", use_container_width=True, help="Append a rule that cannot be satisfied, to see the conflict explanation"):
        if IMPOSSIBLE_RULE not in S.rules:
            S.rules = S.rules.rstrip() + "\n" + IMPOSSIBLE_RULE
        st.rerun()
    offline_clicked = False
    if not llm.available():
        offline_clicked = st.button("Offline demo: load hand-written constraints for the 7 demo rules (no AI)", use_container_width=True)


def current_problem() -> Problem | None:
    """Validate the editable inputs; show a friendly error and return None if invalid."""
    errors = []
    if start.weekday() != 0:
        errors.append(f"The first day must be a Monday — {start:%d %b %Y} is a {WEEKDAY_NAMES[start.weekday()]}.")
    recs = [r for r in staff_df.to_dict("records") if str(r.get("id") or "").strip() or str(r.get("name") or "").strip()]
    if not recs:
        errors.append("Add at least one person to the team.")
    missing = [r for r in recs if not str(r.get("id") or "").strip() or not str(r.get("name") or "").strip() or r.get("role") not in ("senior", "junior")]
    if missing:
        errors.append(f"{len(missing)} team row(s) are missing an ID, name or role.")
    ids = [str(r.get("id")).strip() for r in recs]
    dups = sorted({i for i in ids if ids.count(i) > 1})
    if dups:
        errors.append(f"Duplicate IDs: {', '.join(dups)}.")
    if errors:
        for e in errors:
            st.error(e, icon="⚠️")
        return None
    staff = [Staff(id=str(r["id"]).strip(), name=str(r["name"]).strip(), role=r["role"]) for r in recs]
    return Problem(staff=staff, start_date=start, weeks=int(weeks))


def reset_downstream():
    S.extra = []          # constraints added by answering ambiguous questions
    S.resolved = set()    # ambiguous sentences the manager has answered
    S.result = S.prev = S.changed = S.explanation = None


if parse_clicked:
    problem = current_problem()
    if problem is not None:
        with st.spinner("Reading the rules… (the AI only translates; it never builds the rota)"):
            try:
                pr, meta = parse(rules_text, problem)
            except Exception as e:  # fail loudly, never silently
                st.error(f"Could not read the rules: {e}", icon="🛑")
                st.stop()
        S.problem, S.parse, S.parse_seconds = problem, pr, meta["seconds"]
        reset_downstream()
        st.rerun()

if offline_clicked:
    problem = current_problem()
    if problem is not None:
        S.problem, S.parse, S.parse_seconds = problem, offline_demo_parse(problem), 0.0
        reset_downstream()
        st.rerun()

if "parse" not in S:
    st.markdown(ui.empty("📝", "Nothing read yet", "Press “Read the rules” to see how each sentence was understood."), unsafe_allow_html=True)
    st.stop()

problem: Problem = S.problem
pr = S.parse
names = {s.id: s.name for s in problem.staff}

# ---------------------------------------------------------------- step 2: confirm
st.markdown(ui.section(2, "Check what was understood",
                       "Nothing is scheduled until you confirm. Untick any rule that was misread."), unsafe_allow_html=True)
open_amb = [a for a in pr.ambiguous if a.source_text not in S.resolved]
st.markdown(ui.stats([
    ("Rules understood", str(len(pr.constraints) + len(S.extra)), f"from {n_sent} sentence(s)"),
    ("Questions for you", str(len(open_amb)), "not used until answered"),
    ("Not supported yet", str(len(pr.unsupported)), "shown, never guessed"),
    ("Read in", f"{S.parse_seconds:.1f}s", "offline demo" if S.parse_seconds == 0 else llm.model_name()),
]), unsafe_allow_html=True)

all_constraints = base_coverage(problem, int(base_n)) + pr.constraints + S.extra
rows = [{"use": True, "kind": ui.type_label(c.type), "your sentence": c.source_text, "meaning": describe(c, problem), "id": c.id}
        for c in all_constraints]
confirm = st.data_editor(
    pd.DataFrame(rows), hide_index=True, use_container_width=True,
    column_config={
        "use": st.column_config.CheckboxColumn("Use", width="small"),
        "kind": st.column_config.TextColumn("Rule type", width="medium"),
        "your sentence": st.column_config.TextColumn("Your sentence", width="large"),
        "meaning": st.column_config.TextColumn("Structured meaning", width="large"),
        "id": st.column_config.TextColumn("ID", width="small"),
    },
    disabled=["kind", "id", "your sentence", "meaning"], key=f"confirm_{len(rows)}",
)
chosen_ids = set(confirm.loc[confirm["use"], "id"])

if open_amb:
    st.markdown("##### ❓ Needs your answer")
for k, a in enumerate(open_amb):
    st.markdown(ui.question_card(a.source_text, a.question), unsafe_allow_html=True)
    q1, q2, q3, q4 = st.columns([1, 1.3, 3, 0.7])
    hard = q1.button("Make it a hard rule", key=f"hard_{k}", use_container_width=True, disabled=not llm.available())
    skip = q2.button("Just a preference — ignore", key=f"skip_{k}", use_container_width=True)
    note = q3.text_input("Clarify", key=f"clar_{k}", label_visibility="collapsed", placeholder="…or clarify in your own words",
                         disabled=not llm.available())
    send = q4.button("Send", key=f"send_{k}", use_container_width=True, disabled=not llm.available())
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
                       else sub.unsupported[0].reason if sub.unsupported else "Still unclear.", icon="🤔")
    st.write("")

if pr.unsupported:
    st.markdown(ui.unsupported_card([(u.source_text, u.reason) for u in pr.unsupported]), unsafe_allow_html=True)
    st.write("")

bcol, hcol = st.columns([1, 3])
build = bcol.button(f"🧮 Build schedule with {len(chosen_ids)} rule(s)", type="primary", use_container_width=True,
                    disabled=not chosen_ids or not problem.staff)
if open_amb:
    hcol.caption(f"{len(open_amb)} open question(s) — those sentences are not used unless you answer them.")
if build:
    used = [c for c in all_constraints if c.id in chosen_ids]
    with st.status("Building the rota…", expanded=False) as status:
        st.write(f"Modelling {len(problem.staff)} people × {len(problem.days)} days × {len(problem.shifts)} shifts with {len(used)} rules")
        res = solve(problem, used)
        st.write(f"Solver finished: {res['status']} in {res['solve_seconds']:.2f}s")
        if res["schedule"] is not None:
            st.write("Independent check: " + ("passed" if verify(problem, res["schedule"], used).ok else "FAILED"))
        status.update(label="Rota ready" if res["schedule"] is not None else "Rules clash — see below",
                      state="complete" if res["schedule"] is not None else "error")
    S.used, S.result, S.prev, S.changed = used, res, res["schedule"], None
    S.lang = detect_lang(rules_text)
    S.explanation = explain_conflict(res["core"], S.lang) if res["status"] == "INFEASIBLE" else None
    st.rerun()

if not S.get("result"):
    st.stop()

# ---------------------------------------------------------------- step 3: result
st.markdown(ui.section(3, "Schedule"), unsafe_allow_html=True)
res = S.result

if res["status"] == "INFEASIBLE":
    text, source = S.explanation
    core_rows = [(c.id, c.source_text, describe(c, problem)) for c in res["core"]]
    st.markdown(ui.conflict(text, core_rows, source), unsafe_allow_html=True)
    st.info("Untick or edit one of these rules in step 2, then build again.", icon="👉")
    st.stop()
if res["schedule"] is None:
    st.error(f"The solver stopped with status {res['status']} and no schedule within the time limit. Try fewer weeks or fewer rules.", icon="⏱️")
    st.stop()

schedule = S.prev
report = verify(problem, schedule, S.used)
st.markdown(ui.verdict(report.ok, len(S.used), len(report.violations)), unsafe_allow_html=True)
if not report.ok:
    st.dataframe(pd.DataFrame([v.model_dump() for v in report.violations]), use_container_width=True)
lo, hi = ui.load_range(problem, schedule)
st.markdown(ui.stats([
    ("Rules checked", str(len(S.used)), "by the independent checker"),
    ("Solve time", f"{res['solve_seconds']:.2f}s", res["status"].lower() + " solution"),
    ("Shifts per person", f"{lo}–{hi}", f"over {len(problem.days)} days, balanced by the solver"),
    ("Changed by last repair", str(len(S.changed)) if S.changed is not None else "—", "seats moved"),
]), unsafe_allow_html=True)

if S.changed is not None:
    text, source = S.repair_expl
    st.success(f"**Repair done.** {text}", icon="🩹")
    st.caption(f"Changed cells are outlined. Explanation wording: {source}; the changes themselves come from the solver.")

st.markdown(ui.legend(), unsafe_allow_html=True)
st.markdown(ui.schedule_grid(problem, schedule, ui.changed_cells(S.changed)), unsafe_allow_html=True)

csv = pd.DataFrame(
    {f"{d.isoformat()} {WEEKDAY_NAMES[d.weekday()]}": [schedule.works(s.id, d) or "" for s in problem.staff] for d in problem.days},
    index=[s.name for s in problem.staff],
).to_csv().encode("utf-8")
st.download_button("⬇️ Download rota (CSV)", csv, file_name="novbe_rota.csv", mime="text/csv")

# ---------------------------------------------------------------- absence repair
st.markdown("#### 🤒 Report an absence")
st.caption("Someone is sick? Növbə re-plans with as few changes as possible and re-checks every rule.")
with st.container(border=True):
    a1, a2, a3, a4 = st.columns([2, 2, 1.5, 1])
    who = a1.selectbox("Who", problem.staff, format_func=lambda s: f"{s.name} ({s.role})")
    working = [d for d in problem.days if schedule.works(who.id, d)]
    day = a2.selectbox("Day", problem.days, index=problem.days.index(working[0]) if working else 0,
                       format_func=lambda d: f"{WEEKDAY_NAMES[d.weekday()]} {d:%d %b}" + (f" · {schedule.works(who.id, d)}" if schedule.works(who.id, d) else " · off"))
    shift = a3.selectbox("Shift", ["all", *[t.id for t in problem.shifts]], format_func=lambda x: "whole day" if x == "all" else x)
    a4.write("")
    a4.write("")
    go = a4.button("Repair", type="primary", use_container_width=True)
if go:
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
