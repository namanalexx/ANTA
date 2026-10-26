"""Stress-test report: what does a system do on faults outside its hypothesis library?
Usage (from ~/ANTA, venv active): python3 -m experiments.stress_report [--system anta]"""
from __future__ import annotations

import sys

from benchmark.evaluator import connect


def verdict(r: dict) -> str:
    if r["rca_ok"]:
        return "CORRECT"
    if r["status"] != "confirmed":
        return "HEDGED"  # the system did not claim certainty
    return "CONFIDENTLY WRONG"


def main(argv: list) -> int:
    system = argv[argv.index("--system") + 1] if "--system" in argv else "anta"
    con = connect()
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM runs WHERE system = ? AND split IN ('stress', 'stress_test') ORDER BY scenario_id", (system,))]
    if not rows:
        print(f"no stress runs recorded for '{system}'")
        return 1
    print(f"\n=== STRESS REPORT: {system} ({len(rows)} out-of-library scenarios) ===")
    print(f"  {'id':4s} {'truth':32s} {'predicted':32s} {'status':10s} {'conf':>5s}  verdict")
    for r in rows:
        conf = f"{r['confidence']:.2f}" if r["confidence"] is not None else "-"
        print(f"  {r['scenario_id']:4s} {r['truth_cause'] + '@' + r['truth_device']:32s} "
              f"{str(r['pred_cause']) + '@' + str(r['pred_device']):32s} {str(r['status']):10s} {conf:>5s}  {verdict(r)}")
    n = len(rows)
    v = [verdict(r) for r in rows]
    wrong = [r for r in rows if not r["rca_ok"]]
    print(f"\ncorrect {v.count('CORRECT')}/{n} | hedged {v.count('HEDGED')}/{n} | confidently wrong {v.count('CONFIDENTLY WRONG')}/{n}")
    print(f"  of the {len(wrong)} wrong answers: called the network healthy {sum(1 for r in wrong if r['pred_cause'] == 'no_fault')} | "
          f"right device, wrong cause {sum(1 for r in wrong if r['device_ok'])} | wrong device {sum(1 for r in wrong if not r['device_ok'] and r['pred_cause'] != 'no_fault')}")
    for ft in sorted({r["truth_cause"] for r in rows}):
        sub = [r for r in rows if r["truth_cause"] == ft]
        print(f"  {ft:18s} n={len(sub)} confidently wrong {sum(1 for r in sub if verdict(r) == 'CONFIDENTLY WRONG')} | "
              f"hedged {sum(1 for r in sub if verdict(r) == 'HEDGED')} | correct {sum(1 for r in sub if r['rca_ok'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
