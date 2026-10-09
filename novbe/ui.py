"""Presentation helpers for the Streamlit app: theme CSS and small HTML components.

Pure rendering only — no solving, parsing or checking happens here.
"""
from __future__ import annotations

import html
from typing import Iterable, Optional

from .schema import WEEKDAY_NAMES, Problem, Schedule

# shift identity: reference categorical slots 1-3 (validated all-pairs) + a letter, never colour alone
SHIFT_META = {
    "morning": {"letter": "M", "label": "Morning", "time": "07–15", "color": "#eb6834"},
    "evening": {"letter": "E", "label": "Evening", "time": "15–23", "color": "#1baf7a"},
    "night": {"letter": "N", "label": "Night", "time": "23–07", "color": "#2a78d6"},
}

TYPE_META = {
    "unavailable": ("⛔", "Unavailable"),
    "max_consecutive_days": ("🔁", "Max days in a row"),
    "min_staff": ("👥", "Minimum staff"),
    "min_role": ("🎖️", "Minimum by role"),
    "max_hours_week": ("⏱️", "Max hours / week"),
    "min_rest_hours": ("😴", "Minimum rest"),
    "fixed_assignment": ("📌", "Fixed shift"),
    "max_shifts_week": ("📅", "Max shifts / week"),
}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500&display=swap');
:root {
  --nv-paper: #faf8f4; --nv-card: #ffffff; --nv-ink: #1b1a17; --nv-ink-2: #55524b; --nv-muted: #8a867c;
  --nv-line: #e7e2d8; --nv-accent: #a3243b; --nv-accent-soft: #f6e4e7;
  --nv-good: #0f7b4b; --nv-good-soft: #e3f4ea; --nv-bad: #b42318; --nv-bad-soft: #fdecea;
  --nv-warn: #9a6100; --nv-warn-soft: #fdf3dc;
  --nv-radius: 14px; --nv-shadow: 0 1px 2px rgba(27,26,23,.05), 0 8px 24px -12px rgba(27,26,23,.18);
}
html, body, [class*="css"], .stApp { font-family: 'Inter', system-ui, sans-serif; }
.stApp { background: var(--nv-paper); }
h1, h2, h3, .nv-display { font-family: 'Space Grotesk', 'Inter', sans-serif !important; letter-spacing: -0.01em; color: var(--nv-ink); }
.block-container { padding-top: 3.6rem; max-width: 1280px; }
[data-testid="stAppDeployButton"] { display: none; }
[data-testid="stSidebar"] { background: #f3efe7; border-right: 1px solid var(--nv-line); }

/* hero */
.nv-hero { display:flex; gap:28px; align-items:flex-end; justify-content:space-between; flex-wrap:wrap;
  padding: 26px 28px; border-radius: 20px; background:
  radial-gradient(1200px 300px at 100% 0%, #f3d9de 0%, transparent 60%), linear-gradient(135deg,#fffdf9,#f7f1e7);
  border:1px solid var(--nv-line); box-shadow: var(--nv-shadow); margin-bottom: 18px; }
.nv-brand { display:flex; align-items:center; gap:14px; }
.nv-logo { width:52px; height:52px; border-radius:14px; background: var(--nv-accent); display:grid; place-items:center;
  color:#fff; font: 700 26px 'Space Grotesk', sans-serif; box-shadow: inset 0 -6px 0 rgba(0,0,0,.15); }
.nv-hero h1 { margin:0; padding:0; font-size: 2.3rem; line-height:1.05; }
.nv-tag { color: var(--nv-ink-2); margin: 6px 0 0; font-size: 1.02rem; max-width: 560px; }
.nv-pillars { display:flex; gap:10px; flex-wrap:wrap; }
.nv-pill { background: var(--nv-card); border:1px solid var(--nv-line); border-radius: 999px; padding: 8px 14px;
  font-size: .86rem; color: var(--nv-ink-2); display:flex; gap:8px; align-items:center; }
.nv-pill b { color: var(--nv-ink); font-weight:600; }

/* stepper */
.nv-steps { display:flex; gap:8px; margin: 6px 0 18px; flex-wrap:wrap; }
.nv-step { flex:1 1 160px; display:flex; align-items:center; gap:10px; padding:10px 14px; border-radius:12px;
  border:1px solid var(--nv-line); background: var(--nv-card); color: var(--nv-muted); font-size:.9rem; transition: all .2s ease; }
.nv-step .n { width:26px; height:26px; border-radius:50%; display:grid; place-items:center; font-weight:600; font-size:.82rem;
  background:#f1ede5; color: var(--nv-ink-2); flex: 0 0 auto; }
.nv-step.done { color: var(--nv-ink-2); } .nv-step.done .n { background: var(--nv-good); color:#fff; }
.nv-step.active { border-color: var(--nv-accent); color: var(--nv-ink); box-shadow: 0 0 0 3px var(--nv-accent-soft); }
.nv-step.active .n { background: var(--nv-accent); color:#fff; }

/* section headers */
.nv-sec { display:flex; align-items:baseline; gap:12px; margin: 26px 0 6px; }
.nv-sec .num { font: 600 .8rem 'JetBrains Mono', monospace; color: var(--nv-accent); background: var(--nv-accent-soft);
  padding: 3px 8px; border-radius: 6px; }
.nv-sec h3 { margin:0; padding:0; font-size: 1.35rem; }
.nv-sub { color: var(--nv-ink-2); margin: 0 0 12px; font-size: .95rem; }

/* cards */
.nv-card { background: var(--nv-card); border:1px solid var(--nv-line); border-radius: var(--nv-radius); padding: 16px 18px;
  box-shadow: var(--nv-shadow); }
.nv-q { border-left: 4px solid var(--nv-warn); background: linear-gradient(90deg, var(--nv-warn-soft), #fff 40%); }
.nv-q .src { font-style: italic; color: var(--nv-ink); }
.nv-q .ask { color: var(--nv-warn); font-weight: 600; margin-top: 4px; }
.nv-uns { border-left: 4px solid var(--nv-muted); }
.nv-uns li { margin: 4px 0; } .nv-uns .why { color: var(--nv-ink-2); font-size: .9rem; }

/* stat tiles */
.nv-stats { display:grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 10px 0 16px; }
.nv-stat { background: var(--nv-card); border:1px solid var(--nv-line); border-radius: var(--nv-radius); padding: 14px 16px; }
.nv-stat .k { color: var(--nv-ink-2); font-size: .8rem; text-transform: uppercase; letter-spacing: .06em; }
.nv-stat .v { font: 600 1.7rem 'Space Grotesk', sans-serif; color: var(--nv-ink); margin-top: 2px; }
.nv-stat .s { color: var(--nv-muted); font-size: .82rem; }

/* verdict */
.nv-verdict { display:flex; gap:14px; align-items:center; padding: 14px 18px; border-radius: var(--nv-radius); font-weight: 500; }
.nv-verdict .ic { width:36px; height:36px; border-radius:50%; display:grid; place-items:center; font-size:1.1rem; color:#fff; flex: 0 0 auto; }
.nv-verdict.ok { background: var(--nv-good-soft); color: var(--nv-good); border:1px solid #bfe3cd; } .nv-verdict.ok .ic { background: var(--nv-good); }
.nv-verdict.bad { background: var(--nv-bad-soft); color: var(--nv-bad); border:1px solid #f5c2bd; } .nv-verdict.bad .ic { background: var(--nv-bad); }
.nv-verdict small { display:block; color: var(--nv-ink-2); font-weight: 400; }

/* schedule grid */
.nv-legend { display:flex; gap:16px; flex-wrap:wrap; color: var(--nv-ink-2); font-size: .85rem; margin: 6px 0 10px; }
.nv-legend span { display:inline-flex; align-items:center; gap:6px; }
.nv-scroll { overflow-x:auto; border:1px solid var(--nv-line); border-radius: var(--nv-radius); background: var(--nv-card); box-shadow: var(--nv-shadow); }
table.nv-grid { border-collapse: separate; border-spacing: 0; font-size: .82rem; width: max-content; min-width: 100%; }
.nv-grid th, .nv-grid td { padding: 0; text-align:center; border-bottom: 1px solid #f0ece4; }
.nv-grid thead th { position: sticky; top: 0; background: #fbf9f5; font-weight: 500; color: var(--nv-ink-2); padding: 8px 2px; min-width: 34px; z-index: 1; }
.nv-grid thead th .d { display:block; font: 600 .9rem 'Space Grotesk', sans-serif; color: var(--nv-ink); }
.nv-grid thead th.wk, .nv-grid td.wk { background-color: #f7f3ec; }
.nv-grid th.who { position: sticky; left: 0; background: #fff; text-align:left; padding: 6px 12px; min-width: 150px; z-index: 2;
  border-right: 1px solid var(--nv-line); font-weight: 500; color: var(--nv-ink); white-space: nowrap; }
.nv-grid thead th.who { background: #fbf9f5; z-index: 3; }
.nv-grid .role { font: 500 .68rem 'JetBrains Mono', monospace; padding: 1px 6px; border-radius: 4px; margin-left: 6px; }
.nv-grid .role.senior { background: #ece8f8; color: #4a3aa7; } .nv-grid .role.junior { background: #eef1ee; color: #52514e; }
.nv-cell { display:inline-grid; place-items:center; width: 28px; height: 26px; margin: 3px 2px; border-radius: 6px;
  font: 600 .78rem 'JetBrains Mono', monospace; color: var(--nv-ink); transition: transform .12s ease; }
.nv-cell:hover { transform: scale(1.15); }
.nv-cell.M { background: #eb683426; box-shadow: inset 0 -3px 0 #eb6834; }
.nv-cell.E { background: #1baf7a26; box-shadow: inset 0 -3px 0 #1baf7a; }
.nv-cell.N { background: #2a78d626; box-shadow: inset 0 -3px 0 #2a78d6; }
.nv-cell.off { color: #cfc9bd; font-weight: 400; }
.nv-cell.chg { outline: 2.5px solid var(--nv-accent); outline-offset: 1px; animation: nvpulse 1.6s ease-out 2; }
@keyframes nvpulse { 0% { box-shadow: 0 0 0 0 rgba(163,36,59,.45);} 100% { box-shadow: 0 0 0 10px rgba(163,36,59,0);} }
.nv-grid td.load { padding: 0 12px; min-width: 120px; text-align:left; border-left: 1px solid var(--nv-line); }
.nv-bar { height: 8px; background: #f1ede5; border-radius: 4px; overflow: hidden; display:inline-block; width: 70px; vertical-align: middle; }
.nv-bar i { display:block; height: 100%; background: #a3243b; border-radius: 0 4px 4px 0; }
.nv-grid td.load span { font: 500 .78rem 'JetBrains Mono', monospace; color: var(--nv-ink-2); margin-left: 8px; }
.nv-grid tfoot td { background: #fbf9f5; color: var(--nv-ink-2); font: 500 .74rem 'JetBrains Mono', monospace; padding: 6px 0; }
.nv-grid tfoot th.who { background: #fbf9f5; font-size: .78rem; color: var(--nv-ink-2); }

/* conflict */
.nv-conflict { border:1px solid #f5c2bd; background: linear-gradient(180deg, var(--nv-bad-soft), #fff 70%); border-radius: var(--nv-radius); padding: 18px 20px; }
.nv-conflict h4 { margin: 0 0 6px; color: var(--nv-bad); font-family: 'Space Grotesk', sans-serif; }
.nv-rule { display:flex; gap:12px; align-items:flex-start; background:#fff; border:1px solid var(--nv-line); border-radius: 10px; padding: 10px 12px; margin-top: 8px; }
.nv-rule .tag { font: 600 .72rem 'JetBrains Mono', monospace; color: var(--nv-bad); background: var(--nv-bad-soft); padding: 2px 6px; border-radius: 5px; }
.nv-rule .m { color: var(--nv-ink-2); font-size: .86rem; }

/* empty state */
.nv-empty { text-align:center; padding: 34px 20px; border: 1.5px dashed var(--nv-line); border-radius: var(--nv-radius); color: var(--nv-ink-2); background: #fffdf9; }
.nv-empty .big { font-size: 2rem; }

/* streamlit widgets */
.stButton > button { border-radius: 10px; font-weight: 600; transition: transform .08s ease, box-shadow .2s ease; }
.stButton > button:hover { transform: translateY(-1px); box-shadow: 0 6px 16px -8px rgba(163,36,59,.6); }
.stButton > button:active { transform: translateY(0); }
.stTextArea textarea { font-size: .98rem; line-height: 1.55; background: #fffdf9; }
[data-testid="stDataFrame"], [data-testid="stDataEditor"] { border-radius: 12px; overflow: hidden; }
@media (max-width: 640px) {
  .block-container { padding-top: 3.2rem; }
  .nv-hero { padding: 18px; gap: 16px; } .nv-hero h1 { font-size: 1.8rem; } .nv-tag { font-size: .95rem; }
  .nv-pillars { gap: 6px; } .nv-pill { padding: 5px 10px; font-size: .78rem; }
  .nv-step { flex: 1 1 100%; padding: 8px 12px; }
  .nv-grid th.who { min-width: 110px; padding: 6px 8px; }
}
</style>
"""


def esc(s) -> str:
    return html.escape(str(s))


def hero() -> str:
    return f"""
<div class="nv-hero">
  <div>
    <div class="nv-brand"><div class="nv-logo">N</div><div><h1>Növbə</h1></div></div>
    <p class="nv-tag">Write your shift rules the way you talk — Azerbaijani, Russian or both.
      Get a rota that <b>provably</b> follows every rule, or a clear answer about which rules clash.</p>
  </div>
  <div class="nv-pillars">
    <div class="nv-pill">🧠 <span><b>AI reads</b> the rules</span></div>
    <div class="nv-pill">🧮 <span><b>Solver builds</b> the rota</span></div>
    <div class="nv-pill">✅ <span><b>Checker proves</b> it</span></div>
  </div>
</div>"""


def stepper(current: int) -> str:
    labels = ["Team & rules", "Confirm what was understood", "Schedule"]
    parts = []
    for i, lab in enumerate(labels, 1):
        cls = "done" if i < current else "active" if i == current else ""
        mark = "✓" if i < current else str(i)
        parts.append(f'<div class="nv-step {cls}"><span class="n">{mark}</span>{esc(lab)}</div>')
    return f'<div class="nv-steps">{"".join(parts)}</div>'


def section(num: int, title: str, sub: str = "") -> str:
    s = f'<div class="nv-sec"><span class="num">STEP {num}</span><h3>{esc(title)}</h3></div>'
    return s + (f'<p class="nv-sub">{sub}</p>' if sub else "")


def type_label(t: str) -> str:
    icon, label = TYPE_META.get(t, ("•", t))
    return f"{icon} {label}"


def question_card(source: str, question: str) -> str:
    return f'<div class="nv-card nv-q"><div class="src">“{esc(source)}”</div><div class="ask">❓ {esc(question)}</div></div>'


def unsupported_card(items: Iterable[tuple[str, str]]) -> str:
    lis = "".join(f'<li>“{esc(s)}”<br><span class="why">{esc(r)}</span></li>' for s, r in items)
    return (f'<div class="nv-card nv-uns"><b>Not supported yet</b> — shown so nothing is silently dropped. '
            f'These sentences are not used.<ul>{lis}</ul></div>')


def stats(tiles: list[tuple[str, str, str]]) -> str:
    inner = "".join(f'<div class="nv-stat"><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div><div class="s">{esc(s)}</div></div>'
                    for k, v, s in tiles)
    return f'<div class="nv-stats">{inner}</div>'


def verdict(ok: bool, n_rules: int, n_viol: int) -> str:
    if ok:
        return (f'<div class="nv-verdict ok"><span class="ic">✓</span><div>0 rule violations — independent check'
                f'<small>All {n_rules} confirmed rules were re-checked on the final rota by a separate checker that does not use the solver.</small></div></div>')
    return (f'<div class="nv-verdict bad"><span class="ic">!</span><div>{n_viol} violation(s) found by the independent check'
            f'<small>See the list below.</small></div></div>')


def legend() -> str:
    items = "".join(f'<span><span class="nv-cell {m["letter"]}" style="margin:0">{m["letter"]}</span>{m["label"]} {m["time"]}</span>'
                    for m in SHIFT_META.values())
    return (f'<div class="nv-legend">{items}<span><span class="nv-cell chg off" style="margin:0;animation:none">·</span>changed by repair</span>'
            f'<span>Shaded columns = weekend</span></div>')


def schedule_grid(problem: Problem, schedule: Schedule, changed: frozenset = frozenset()) -> str:
    days = problem.days
    head = ['<th class="who">Person</th>']
    for d in days:
        wk = " wk" if d.weekday() >= 5 else ""
        head.append(f'<th class="{wk.strip()}" title="{d.isoformat()}">{WEEKDAY_NAMES[d.weekday()][:2]}<span class="d">{d.day:02d}</span></th>')
    head.append('<th>Load</th>')
    rows = []
    counts = {s.id: 0 for s in problem.staff}
    for s in problem.staff:
        for d in days:
            if schedule.works(s.id, d):
                counts[s.id] += 1
    mx = max(counts.values() or [1]) or 1
    for s in problem.staff:
        cells = [f'<th class="who">{esc(s.name)}<span class="role {s.role}">{s.role[0].upper()}</span></th>']
        for d in days:
            sh = schedule.works(s.id, d)
            wk = "wk" if d.weekday() >= 5 else ""
            chg = " chg" if (s.id, d.isoformat()) in changed else ""
            if sh:
                m = SHIFT_META.get(sh, {"letter": sh[:1].upper(), "label": sh, "time": ""})
                tip = f"{s.name} · {WEEKDAY_NAMES[d.weekday()]} {d.isoformat()} · {m['label']} {m['time']}"
                cells.append(f'<td class="{wk}"><span class="nv-cell {m["letter"]}{chg}" title="{esc(tip)}">{m["letter"]}</span></td>')
            else:
                tip = f"{s.name} · {WEEKDAY_NAMES[d.weekday()]} {d.isoformat()} · day off"
                cells.append(f'<td class="{wk}"><span class="nv-cell off{chg}" title="{esc(tip)}">·</span></td>')
        n = counts[s.id]
        cells.append(f'<td class="load" title="{esc(s.name)}: {n} shifts"><span class="nv-bar"><i style="width:{100 * n / mx:.0f}%"></i></span><span>{n}</span></td>')
        rows.append(f"<tr>{''.join(cells)}</tr>")
    foot = ['<th class="who">On shift</th>']
    for d in days:
        per = schedule.assignments.get(d.isoformat(), {})
        tip = " · ".join(f"{SHIFT_META.get(k, {'label': k})['label']}: {len(v)}" for k, v in per.items())
        foot.append(f'<td title="{esc(tip)}">{sum(len(v) for v in per.values())}</td>')
    foot.append("<td></td>")
    return (f'<div class="nv-scroll"><table class="nv-grid" aria-label="Shift schedule">'
            f'<thead><tr>{"".join(head)}</tr></thead><tbody>{"".join(rows)}</tbody>'
            f'<tfoot><tr>{"".join(foot)}</tr></tfoot></table></div>')


def conflict(text: str, rules: list[tuple[str, str, str]], source: str) -> str:
    items = "".join(f'<div class="nv-rule"><span class="tag">{esc(i)}</span><div>“{esc(src)}”<div class="m">{esc(meaning)}</div></div></div>'
                    for i, src, meaning in rules)
    return (f'<div class="nv-conflict"><h4>These rules cannot all be true at once</h4><div>{esc(text)}</div>{items}'
            f'<div class="m" style="margin-top:10px;color:#8a867c;font-size:.82rem">Found by the solver (infeasibility core, shrunk to a minimal set) — '
            f'not guessed. Wording: {esc(source)}.</div></div>')


def empty(icon: str, title: str, body: str) -> str:
    return f'<div class="nv-empty"><div class="big">{icon}</div><b>{esc(title)}</b><div>{esc(body)}</div></div>'


def load_range(problem: Problem, schedule: Schedule) -> tuple[int, int]:
    counts = [sum(1 for d in problem.days if schedule.works(s.id, d)) for s in problem.staff]
    return (min(counts), max(counts)) if counts else (0, 0)


def changed_cells(changed: Optional[list]) -> frozenset:
    out = set()
    for d, _s, a, b in changed or []:
        for p in (a, b):
            if p:
                out.add((p, d))
    return frozenset(out)
