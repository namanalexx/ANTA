"""Generate docs/RESULTS.md from the benchmark database: every number in the README comes from here.
Usage (from ~/ANTA, venv active): python3 -m experiments.final_report"""
from __future__ import annotations

from datetime import datetime

from benchmark import ROOT
from benchmark.evaluator import _agg, connect
from experiments.ablation_report import VARIANTS, confidently_wrong
from experiments.compare import wilson

MAIN, STRESS = ("dev", "test"), ("stress", "stress_test")
SYSTEMS = [("llm_only", "LLM-only (no tools)"), ("react", "ReAct (same tools)"),
           ("anta_v1", "ANTA before the fault-type extension"), ("anta", "ANTA (final)")]


def pct(x) -> str:
    return "-" if x is None or x != x else f"{x:.0%}"


def table(headers: list, rows: list) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    return "\n".join(out + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def pick(runs: list, system: str, splits: tuple) -> list:
    return [r for r in runs if r["system"] == system and r["split"] in splits]


def accuracy_rows(runs: list, splits: tuple, systems=SYSTEMS) -> list:
    body = []
    for s, name in systems:
        sub = pick(runs, s, splits)
        if not sub:
            continue
        a = _agg(sub)
        lo, hi = wilson(sum(r["rca_ok"] for r in sub), len(sub))
        body.append([name, a["n"], pct(a["detect"]), f"**{pct(a['rca'])}**", f"{lo:.0%}-{hi:.0%}",
                     sum(1 for r in sub if confidently_wrong(r)), f"{a['calls']:.1f}", f"{a['sec']:.1f}"])
    return body


def main() -> None:
    con = connect()
    runs = [dict(r) for r in con.execute("SELECT * FROM runs")]
    hdr = ["System", "n", "Detection", "Root-cause accuracy", "95% CI", "Confidently wrong", "Tool calls", "Seconds"]
    parts = [f"# ANTA results\n\nGenerated {datetime.now():%Y-%m-%d %H:%M} from `experiments/results/anta_bench.sqlite`.\n"]

    for title, splits, note in (
        ("Held-out test split (19 scenarios)", ("test",), ""),
        ("All main scenarios (35)", MAIN, ""),
        ("Fault types the earlier agent had no hypotheses for (16 scenarios)", STRESS,
         "s36-s45 shaped the extension (coverage evidence); s46-s51 were held out before the extension (see methodology)."),
        ("Final held-out batch (never tuned on)", ("final",), ""),
    ):
        body = accuracy_rows(runs, splits)
        if body:
            parts.append(f"## {title}\n\n{note}\n\n" + table(hdr, body) + "\n")

    for s, name in (("anta_v1", "before"), ("anta", "after")):
        sub = pick(runs, s, ("stress_test",))
        if sub:
            parts.append(f"Held-out s46-s51, {name} the extension: {sum(r['rca_ok'] for r in sub)}/{len(sub)} correct.\n")

    try:
        rem = [dict(r) for r in con.execute("SELECT * FROM remediation_runs")]
    except Exception:
        rem = []
    faults = [r for r in rem if r["fault_type"] != "no_fault"]
    if faults:
        by = sorted({r["fault_type"] for r in faults})
        rows = [[ft, len([r for r in faults if r["fault_type"] == ft]),
                 sum(r["fixed"] for r in faults if r["fault_type"] == ft),
                 sum(r["regression"] for r in faults if r["fault_type"] == ft)] for ft in by]
        rows.append(["**all**", len(faults), sum(r["fixed"] for r in faults), sum(r["regression"] for r in faults)])
        acted = sum(1 for r in rem if r["fault_type"] == "no_fault" and r["action_id"])
        parts.append("## Remediation (verified and regression-checked)\n\n" + table(["Fault type", "Scenarios", "Fixed", "Regressions"], rows)
                     + f"\n\nActions taken on healthy networks: {acted}/{len(rem) - len(faults)}.\n")

    try:
        g = [dict(r) for r in con.execute("SELECT * FROM gate_runs")]
    except Exception:
        g = []
    if g:
        by = lambda k: [r for r in g if r["kind"] == k]
        rows = [["Correct fixes applied (live fixed, no regression)", f"{sum(r['ok'] for r in by('correct_diagnosis'))}/{len(by('correct_diagnosis'))}"],
                ["Wrong-diagnosis fixes blocked, live untouched", f"{sum(r['ok'] for r in by('wrong_diagnosis'))}/{len(by('wrong_diagnosis'))}"],
                ["Unsafe fixes blocked, live untouched", f"{sum(r['ok'] for r in by('unsafe_action'))}/{len(by('unsafe_action'))}"],
                ["Same unsafe fixes WITHOUT the gate: regression or failure",
                 f"{sum(1 for r in by('unsafe_action') if r['ungated_regression'] or not r['ungated_fixed'])}/{len(by('unsafe_action'))}"],
                ["Shadow reproduced the live symptoms (fidelity)", f"{sum(r['fidelity'] for r in g)}/{len(g)}"]]
        parts.append("## Shadow-network gate\n\n" + table(["Check", "Result"], rows) + "\n")

    body = []
    for s, desc in VARIANTS:
        sub = [r for r in runs if r["system"] == s and r["split"] in MAIN + STRESS]
        if sub:
            a = _agg(sub)
            body.append([desc, a["n"], f"**{pct(a['rca'])}**", sum(1 for r in sub if confidently_wrong(r)),
                         f"{a['calls']:.1f}", f"{a['sec']:.1f}"])
    if body:
        parts.append("## Ablations (51 scenarios)\n\n" + table(["Variant", "n", "Root-cause accuracy", "Confidently wrong", "Tool calls", "Seconds"], body) + "\n")

    out = ROOT / "docs" / "RESULTS.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts))
    print("\n".join(parts))
    print(f"saved: {out}")


if __name__ == "__main__":
    main()
