"""Phase 5 gate: the full loop on benchmark scenarios.
reset -> inject -> ANTA diagnoses -> plan fix -> apply -> verify -> regression check -> reset.
Usage (from ~/ANTA, venv active): python3 -m remediation.run_eval [--split dev|test|all] [--scenarios s01,s02] [--force]"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime

from agent.anta import run_agent
from benchmark.evaluator import connect
from benchmark.runner import SCEN_DIR, healthy
from scenario_faults import inject, reset_network

from .pipeline import remediate

SCHEMA = """CREATE TABLE IF NOT EXISTS remediation_runs (
  run_id TEXT PRIMARY KEY, scenario_id TEXT, split TEXT, tier TEXT, fault_type TEXT, diag_ok INTEGER,
  action_id TEXT, applied_ok INTEGER, fixed INTEGER, regression INTEGER, detail_json TEXT, seconds REAL,
  error TEXT, ts TEXT)"""


def report(con) -> None:
    rows = [dict(r) for r in con.execute("SELECT * FROM remediation_runs ORDER BY scenario_id")]
    faults = [r for r in rows if r["fault_type"] != "no_fault"]
    healthy_rows = [r for r in rows if r["fault_type"] == "no_fault"]
    rate = lambda xs, k: (sum(r[k] for r in xs) / len(xs)) if xs else float("nan")
    print(f"\n==================== REMEDIATION REPORT ({len(rows)} scenarios) ====================")
    print(f"fault scenarios        n={len(faults):2d}  diagnosis ok {rate(faults, 'diag_ok'):.0%} | "
          f"remediation success {rate(faults, 'fixed'):.0%} | regression {rate(faults, 'regression'):.0%}")
    acted = sum(1 for r in healthy_rows if r["action_id"])
    print(f"healthy-network cases  n={len(healthy_rows):2d}  wrongly acted on: {acted}")
    print("\nBY FAULT TYPE")
    for ft in sorted({r["fault_type"] for r in faults}):
        sub = [r for r in faults if r["fault_type"] == ft]
        print(f"  {ft:16s} n={len(sub):2d} success {rate(sub, 'fixed'):4.0%}  regression {rate(sub, 'regression'):4.0%}")
    bad = [r for r in rows if (r["fault_type"] != "no_fault" and not r["fixed"]) or r["regression"]
           or r["error"] or (r["fault_type"] == "no_fault" and r["action_id"])]
    print(f"\nPROBLEMS ({len(bad)}):")
    for r in bad:
        d = json.loads(r["detail_json"]) if r["detail_json"] else {}
        print(f"  {r['scenario_id']} {r['fault_type']}: fixed={r['fixed']} regression={r['regression']} "
              f"action={r['action_id']} residual={d.get('residual_anomalies')} "
              f"unintended={d.get('unintended_changes')} {r['error'] or ''}")


def main(argv: list) -> int:
    from benchmark.lab_lock import acquire
    acquire("remediation.run_eval")
    split, only, force = "all", None, "--force" in argv
    if "--split" in argv:
        split = argv[argv.index("--split") + 1]
    if "--scenarios" in argv:
        only = argv[argv.index("--scenarios") + 1].split(",")
    scenarios = [json.loads(p.read_text()) for p in sorted(SCEN_DIR.glob("s*.json"))]
    if split != "all":
        scenarios = [s for s in scenarios if s["split"] == split]
    else:  # the out-of-library stress scenarios are only run when asked for explicitly
        scenarios = [s for s in scenarios if s["split"] not in ("stress", "stress_test")]
    if only:
        scenarios = [s for s in scenarios if s["id"] in only]

    con = connect()
    con.execute(SCHEMA)
    for sc in scenarios:
        run_id = f"rem:{sc['id']}"
        if not force and con.execute("SELECT 1 FROM remediation_runs WHERE run_id = ?", (run_id,)).fetchone():
            print(f"skip {run_id} (already recorded)")
            continue
        gt, f = sc["ground_truth"], sc["injected_fault"]
        print(f"\n=== {run_id} | {gt['cause']} on {gt['device']} ===", flush=True)
        rem, diag, err = None, None, None
        try:
            reset_network(); time.sleep(1)
            if not healthy():
                raise RuntimeError("baseline not healthy after reset")
            inject(f); time.sleep(1)
            diag = run_agent(sc["symptom"], verbose=False)["diagnosis"]
            rem = remediate(diag, verbose=False)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
        finally:
            try:
                reset_network()
            except Exception as e2:
                err = (err or "") + f" | reset failed: {e2}"
        diag_ok = int(bool(diag) and diag["cause"] == gt["cause"] and diag["device"] == gt["device"])
        row = (run_id, sc["id"], sc["split"], sc["tier"], gt["cause"], diag_ok,
               (rem or {}).get("action", {}) and rem["action"]["id"] or None,
               int(bool(rem) and rem["applied"]["ok"]), int(bool(rem) and rem["fixed"]),
               int(bool(rem) and rem["regression"]), json.dumps(rem) if rem else None,
               (rem or {}).get("seconds"), err, datetime.now().isoformat())
        con.execute("INSERT OR REPLACE INTO remediation_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
        con.commit()
        print(f"diagnosis {'OK ' if diag_ok else 'WRONG'} -> action={row[6]} fixed={bool(row[8])} "
              f"regression={bool(row[9])} {err or ''}")
    report(con)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
