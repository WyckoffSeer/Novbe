"""Run the three evaluations and write eval/results/*. These files are the only source of
numbers for docs/TESTING.md.

1. Rule understanding  — per-sentence accuracy by language style; wrongly accepted sentences.
2. Schedule correctness — violations per schedule: Növbə vs plain-prompt chatbot baseline,
                          both scored by the same independent verifier.
3. Infeasible handling  — does the reported core equal the planted conflicting rules?

Usage: python -m eval.run_eval [--no-llm] [--workers 6]
"""
from __future__ import annotations

import datetime as dt
import json
import statistics
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pydantic import TypeAdapter  # noqa: E402

from eval import baseline_chatbot  # noqa: E402
from novbe import llm  # noqa: E402
from novbe.parser import parse  # noqa: E402
from novbe.schema import Constraint, Problem, Staff, base_coverage  # noqa: E402
from novbe.solver import solve  # noqa: E402
from novbe.verifier import verify  # noqa: E402

CASES = ROOT / "eval" / "cases"
RESULTS = ROOT / "eval" / "results"
CA = TypeAdapter(Constraint)


def load_cases() -> list[dict]:
    return [json.loads(f.read_text(encoding="utf-8")) for f in sorted(CASES.glob("case*.json"))]


def problem_of(case) -> Problem:
    return Problem(staff=[Staff(**s) for s in case["staff"]], start_date=dt.date.fromisoformat(case["start_date"]), weeks=case["weeks"])


def truth_constraints(case) -> list:
    out = []
    for s in case["sentences"]:
        for c in s["constraints"]:
            obj = CA.validate_python(c)
            obj.source_text = s["text"]
            out.append(obj)
    return out


def norm(c: dict) -> str:
    d = {k: v for k, v in c.items() if k not in ("id", "source_text")}
    for k in ("shift", "after_shift"):
        if d.get(k) == "all":
            d[k] = None
    if d.get("weekdays") is not None:
        d["weekdays"] = sorted(d["weekdays"])
    if d.get("date_range") is not None:
        d["date_range"] = [str(x) for x in d["date_range"]]
    if "date" in d:
        d["date"] = str(d["date"])
    return json.dumps(d, sort_keys=True)


def rules_text(case) -> str:
    return "\n".join(s["text"] for s in case["sentences"])


# ---------------------------------------------------------------- LLM stage (parallel)


def llm_stage(case) -> dict:
    p = problem_of(case)
    out = {"id": case["id"]}
    try:
        pr, meta = parse(rules_text(case), p)
        out["parse"] = pr.model_dump(mode="json")
        out["parse_seconds"] = meta["seconds"]
    except Exception as e:
        out["parse_error"] = f"{type(e).__name__}: {e}"
    if not case["infeasible"]:
        t0 = time.perf_counter()
        try:
            sched, _ = baseline_chatbot.run(p, rules_text(case), case["base_n"])
            out["baseline"] = sched.model_dump()
        except Exception as e:
            out["baseline_error"] = f"{type(e).__name__}: {e}"
        out["baseline_seconds"] = time.perf_counter() - t0
    return out


# ---------------------------------------------------------------- scoring


def score_sentences(case, parsed: dict | None) -> list[dict]:
    rows = []
    for s in case["sentences"]:
        text = s["text"]
        if parsed is None:
            rows.append({"text": text, "expected": s["expected"], "got": "parse_error", "correct": False})
            continue
        got_cs = [c for c in parsed["constraints"] if c["source_text"] and c["source_text"] in text]
        got_amb = [a for a in parsed["ambiguous"] if a["source_text"] in text]
        got_uns = [u for u in parsed["unsupported"] if u["source_text"] in text]
        if got_cs and not got_amb and not got_uns:
            got = "constraint"
        elif got_amb and not got_cs:
            got = "ambiguous"
        elif got_uns and not got_cs:
            got = "unsupported"
        elif not (got_cs or got_amb or got_uns):
            got = "missing"
        else:
            got = "mixed"
        if s["expected"] == "constraint":
            correct = got == "constraint" and sorted(norm(c) for c in got_cs) == sorted(norm(c) for c in s["constraints"])
        else:
            correct = got in ("ambiguous", "unsupported")
        rows.append({
            "text": text, "template_text": s.get("template_text"), "expected": s["expected"], "got": got, "correct": correct,
            "exact_bucket": got == s["expected"],
            "expected_constraints": s["constraints"], "got_constraints": got_cs,
            "got_note": (got_amb[0]["question"] if got_amb else got_uns[0]["reason"] if got_uns else None),
        })
    return rows


def main():
    use_llm = "--no-llm" not in sys.argv and llm.available()
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 6
    cases = load_cases()
    RESULTS.mkdir(parents=True, exist_ok=True)
    t_start = time.perf_counter()

    llm_out = {}
    if use_llm:
        with ThreadPoolExecutor(workers) as ex:
            for r in ex.map(llm_stage, cases):
                llm_out[r["id"]] = r
                print(f"  llm done {r['id']}", flush=True)

    per_case = []
    for case in cases:
        p = problem_of(case)
        base = base_coverage(p, case["base_n"])
        truth = truth_constraints(case)
        rec = {"id": case["id"], "style": case["style"], "team_size": len(case["staff"]), "infeasible": case["infeasible"],
               "paraphrased": case.get("paraphrased", False)}
        lo = llm_out.get(case["id"], {})

        # solver on ground truth (no LLM involved)
        gt = solve(p, base + truth)
        rec["truth_status"], rec["truth_solve_seconds"] = gt["status"], gt["solve_seconds"]
        if gt["schedule"] is not None:
            rec["truth_violations"] = len(verify(p, gt["schedule"], base + truth).violations)
        if case["infeasible"]:
            rec["truth_core"] = sorted(i for i in gt["core_ids"] if not i.startswith("base-"))
            rec["truth_core_has_base"] = any(i.startswith("base-") for i in gt["core_ids"])
            rec["truth_core_exact"] = rec["truth_core"] == case["conflict_ids"] and not rec["truth_core_has_base"]
            rec["truth_core_contains"] = set(case["conflict_ids"]) <= set(rec["truth_core"])

        if use_llm:
            parsed = lo.get("parse")
            rec["parse_error"] = lo.get("parse_error")
            rec["parse_seconds"] = lo.get("parse_seconds")
            rec["sentences"] = score_sentences(case, parsed)
            if parsed is not None:
                pcs = [CA.validate_python(c) for c in parsed["constraints"]]
                e2e = solve(p, base + pcs)
                rec["e2e_status"], rec["e2e_solve_seconds"] = e2e["status"], e2e["solve_seconds"]
                if e2e["schedule"] is not None:
                    rec["e2e_violations_vs_truth"] = len(verify(p, e2e["schedule"], base + truth).violations)
                    rec["e2e_violations_vs_parsed"] = len(verify(p, e2e["schedule"], base + pcs).violations)
                if case["infeasible"]:
                    planted = sorted(s["text"] for s in case["sentences"] for c in s["constraints"] if c["id"] in case["conflict_ids"])
                    core_txt = sorted({c.source_text for c in e2e["core"] if not c.id.startswith("base-")})
                    rec["e2e_core_sentences"] = core_txt
                    rec["e2e_core_exact"] = core_txt == sorted(set(planted))
            if not case["infeasible"]:
                rec["baseline_error"] = lo.get("baseline_error")
                rec["baseline_seconds"] = lo.get("baseline_seconds")
                if "baseline" in lo:
                    from novbe.schema import Schedule

                    rep = verify(p, Schedule(**lo["baseline"]), base + truth)
                    rec["baseline_violations"] = len(rep.violations)
                    rec["baseline_violation_examples"] = [v.model_dump() for v in rep.violations[:5]]
        per_case.append(rec)
        print(f"  scored {case['id']}", flush=True)

    summary = summarize(per_case, use_llm)
    summary["eval_wall_seconds"] = round(time.perf_counter() - t_start, 1)
    (RESULTS / "results.json").write_text(json.dumps({"summary": summary, "cases": per_case}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_failures(per_case)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 3) if xs else None


def summarize(cases: list[dict], use_llm: bool) -> dict:
    feas = [c for c in cases if not c["infeasible"]]
    inf = [c for c in cases if c["infeasible"]]
    s = {
        "run_at": dt.datetime.now().isoformat(timespec="seconds"),
        "model": llm.model_name() if use_llm else None,
        "llm_used": use_llm,
        "n_cases": len(cases), "n_feasible": len(feas), "n_infeasible": len(inf),
        "team_size_range": [min(c["team_size"] for c in cases), max(c["team_size"] for c in cases)],
        "paraphrased_cases": sum(c["paraphrased"] for c in cases),
        "solver_on_truth": {
            "feasible_cases_solved": sum(c["truth_status"] in ("OPTIMAL", "FEASIBLE") for c in feas),
            "feasible_cases_zero_violations": sum(c.get("truth_violations") == 0 for c in feas),
            "infeasible_detected": sum(c["truth_status"] == "INFEASIBLE" for c in inf),
            "core_exact": sum(c.get("truth_core_exact", False) for c in inf),
            "core_contains_planted": sum(c.get("truth_core_contains", False) for c in inf),
            "median_solve_seconds": med([c["truth_solve_seconds"] for c in cases]),
            "max_solve_seconds": max(c["truth_solve_seconds"] for c in cases),
        },
    }
    if not use_llm:
        return s
    sents = [r for c in cases for r in c.get("sentences", [])]
    by_style = {}
    for c in cases:
        for r in c.get("sentences", []):
            if r["expected"] == "constraint":
                b = by_style.setdefault(c["style"], [0, 0])
                b[0] += r["correct"]
                b[1] += 1
    flag = [r for r in sents if r["expected"] != "constraint"]
    s["understanding"] = {
        "sentences": len(sents),
        "constraint_sentences": sum(r["expected"] == "constraint" for r in sents),
        "constraint_sentences_correct": sum(r["correct"] for r in sents if r["expected"] == "constraint"),
        "by_style": {k: {"correct": v[0], "total": v[1]} for k, v in sorted(by_style.items())},
        "should_flag": len(flag),
        "flagged_correctly": sum(r["correct"] for r in flag),
        "wrongly_accepted": sum(r["got"] == "constraint" for r in flag),
        "valid_rules_wrongly_flagged": sum(r["expected"] == "constraint" and r["got"] in ("ambiguous", "unsupported") for r in sents),
        "parse_errors": sum(bool(c.get("parse_error")) for c in cases),
        "median_parse_seconds": med([c.get("parse_seconds") for c in cases]),
    }
    s["schedules"] = {
        "novbe_e2e_schedules": sum("e2e_violations_vs_truth" in c for c in feas),
        "novbe_e2e_zero_violations_vs_truth": sum(c.get("e2e_violations_vs_truth") == 0 for c in feas),
        "novbe_e2e_zero_violations_vs_parsed": sum(c.get("e2e_violations_vs_parsed") == 0 for c in feas),
        "novbe_e2e_total_violations_vs_truth": sum(c.get("e2e_violations_vs_truth", 0) for c in feas),
        "novbe_e2e_no_schedule": sum("e2e_violations_vs_truth" not in c for c in feas),
        "baseline_schedules": sum("baseline_violations" in c for c in feas),
        "baseline_invalid_output": sum(bool(c.get("baseline_error")) for c in feas),
        "baseline_zero_violations": sum(c.get("baseline_violations") == 0 for c in feas),
        "baseline_total_violations": sum(c.get("baseline_violations", 0) for c in feas),
        "baseline_median_violations": med([c.get("baseline_violations") for c in feas]),
        "baseline_median_seconds": med([c.get("baseline_seconds") for c in feas]),
        "novbe_median_e2e_solve_seconds": med([c.get("e2e_solve_seconds") for c in cases]),
    }
    s["infeasible"] = {
        "e2e_detected": sum(c.get("e2e_status") == "INFEASIBLE" for c in inf),
        "e2e_core_exact": sum(c.get("e2e_core_exact", False) for c in inf),
    }
    return s


def write_failures(cases: list[dict]) -> None:
    lines = ["# Real failure cases (auto-collected by eval/run_eval.py)", ""]
    fails = [(c, r) for c in cases for r in c.get("sentences", []) if not r["correct"]]
    # prefer diversity of styles
    picked, seen = [], set()
    for c, r in fails:
        if c["style"] not in seen:
            picked.append((c, r))
            seen.add(c["style"])
    for c, r in fails:
        if len(picked) >= 3:
            break
        if (c, r) not in picked:
            picked.append((c, r))
    for c in cases:
        if c.get("baseline_violations"):
            picked.append((c, None))
            break
    if not picked:
        lines.append("No failures in this run.")
    for c, r in picked[:4]:
        if r is None:
            lines += [f"## {c['id']} ({c['style']}): baseline chatbot schedule", "",
                      f"- What happened: the plain-prompt chatbot's rota broke {c['baseline_violations']} rule checks.",
                      "- Examples: " + "; ".join(f"`{v['constraint_id']}` {v['date']}: {v['detail']}" for v in c["baseline_violation_examples"][:3]),
                      "- Why: the chatbot writes the rota token by token and has no step that checks it; nothing forces every rule to hold.", ""]
            continue
        lines += [f"## {c['id']} ({c['style']})", "", f"- Input: “{r['text']}”"]
        if r.get("template_text"):
            lines.append(f"- (template before paraphrase: “{r['template_text']}”)")
        lines.append(f"- Expected: {r['expected']} {json.dumps(r['expected_constraints'], ensure_ascii=False) if r['expected_constraints'] else ''}")
        lines.append(f"- Got: {r['got']} {json.dumps(r['got_constraints'], ensure_ascii=False) if r['got_constraints'] else ''} {r['got_note'] or ''}")
        why = []
        if r["expected"] == "constraint" and r["got"] == "constraint":
            exp, got = r["expected_constraints"], r["got_constraints"]
            if len(exp) != len(got):
                why.append(f"produced {len(got)} constraint(s) instead of {len(exp)}")
            else:
                for e, g in zip(exp, got):
                    diff = [k for k in e if k not in ("id",) and json.dumps(e.get(k)) != json.dumps(g.get(k))]
                    why.append("fields differ: " + ", ".join(diff))
        elif r["expected"] != "constraint" and r["got"] == "constraint":
            why.append("accepted a sentence that should have been flagged (preference/unknown/unsupported)")
        else:
            why.append(f"bucket was '{r['got']}' instead of '{r['expected']}'")
        lines += [f"- Why (automatic diff): {'; '.join(why)}", ""]
    (RESULTS / "failures.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
