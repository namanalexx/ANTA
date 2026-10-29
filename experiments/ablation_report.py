"""Ablation report: what carries accuracy, and what carries efficiency?
Usage (from ~/ANTA, venv active): python3 -m experiments.ablation_report"""
from __future__ import annotations

import csv
import json

from benchmark import ROOT
from benchmark.evaluator import _agg, connect

VARIANTS = [
    ("anta", "LLM planner (qwen2.5:7b), full evidence model"),
    ("anta_ranked", "ranking only, no LLM"),
    ("anta_random", "random test order, no LLM"),
    ("anta_ranked_noelim", "ranking only, NO elimination rule"),
    ("anta_ranked_noprec", "ranking only, NO precondition rule"),
    ("anta_llama3b", "LLM planner (llama3.2:3b)"),
]
SPLITS = ("dev", "test", "stress", "stress_test")


def confidently_wrong(r: dict) -> bool:
    return not r["rca_ok"] and r["status"] == "confirmed"


def llm_valid_rate(rows: list):
    """Share of LLM calls that were usable (valid test choice / parsable report); only meaningful for LLM planners."""
    calls = fb = 0
    for r in rows:
        try:
            st = json.loads(r["result_json"])["stats"]
        except (TypeError, KeyError, ValueError):
            continue
        calls += st.get("llm_calls", 0)
        fb += st.get("llm_fallbacks", 0)
    return None if calls == 0 else 1 - fb / calls


def main() -> int:
    con = connect()
    all_rows = [dict(r) for r in con.execute("SELECT * FROM runs")]
    present = [(s, d) for s, d in VARIANTS if any(r["system"] == s for r in all_rows)]
    if not present:
        print("no ablation runs recorded yet")
        return 1
    csv_rows = []
    print("\n=== ABLATIONS on all 51 scenarios ===")
    print(f"  {'variant':20s} {'description':44s} {'n':>3s} {'RCA':>5s} {'conf.wrong':>10s} {'calls':>6s} {'sec':>6s} {'LLM ok':>7s}")
    for s, desc in present:
        rows = [r for r in all_rows if r["system"] == s and r["split"] in SPLITS]
        a = _agg(rows)
        cw = sum(1 for r in rows if confidently_wrong(r))
        v = llm_valid_rate(rows) if s in ("anta", "anta_llama3b") else None
        shown = f"{v * 100:.0f}%" if v is not None else "-"
        print(f"  {s:20s} {desc:44s} {a['n']:3d} {a['rca']:5.0%} {cw:10d} {a['calls']:6.1f} {a['sec']:6.1f} {shown:>7s}")
        csv_rows.append({"variant": s, "description": desc, "n": a["n"], "rca": round(a["rca"], 4),
                         "confidently_wrong": cw, "calls": round(a["calls"], 2), "sec": round(a["sec"], 2)})

    for title, key in (("RCA by split", "rca"), ("average tool calls by split", "calls")):
        print(f"\n=== {title} ===")
        print(f"  {'variant':20s} " + " ".join(f"{sp:>12s}" for sp in SPLITS))
        for s, _ in present:
            cells = []
            for sp in SPLITS:
                sub = [r for r in all_rows if r["system"] == s and r["split"] == sp]
                if not sub:
                    cells.append(f"{'-':>12s}")
                elif key == "rca":
                    cells.append(f"{_agg(sub)['rca']:12.0%}")
                else:
                    cells.append(f"{_agg(sub)['calls']:12.1f}")
            print(f"  {s:20s} " + " ".join(cells))

    for s, _ in present:
        if s == "anta":
            continue
        bad = [r for r in all_rows if r["system"] == s and r["split"] in SPLITS and not r["rca_ok"]]
        if bad:
            print(f"\n  {s}: {len(bad)} wrong answers")
            for r in sorted(bad, key=lambda r: r["scenario_id"])[:14]:
                print(f"    {r['scenario_id']} truth={r['truth_cause']}@{r['truth_device']} "
                      f"pred={r['pred_cause']}@{r['pred_device']} [{r['status']}]")

    out = ROOT / "experiments" / "results" / "ablations.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(csv_rows[0]))
        w.writeheader()
        w.writerows(csv_rows)
    print(f"\nsaved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
