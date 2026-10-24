"""Automated benchmark pipeline: reset -> inject -> run system -> evaluate -> log.
Usage (from ~/ANTA, venv active):
  python3 -m benchmark.runner --system anta [--split dev|test|all] [--scenarios s01,s02] [--reps N] [--force]
  python3 -m benchmark.runner --inject-only          # sanity-check injection + reset, no agent"""
from __future__ import annotations

import json
import sys
import time

import agent  # noqa: F401  (sets up sys.path)
from agent.anta import run_agent
from scenario_faults import inject, reset_network
from tools import check_service, inspect_dns, ping

from . import ROOT
from .evaluator import connect, evaluate, insert, report

SCEN_DIR = ROOT / "benchmark" / "scenarios"
SYSTEMS = {"anta": lambda symptom: run_agent(symptom, verbose=False)}


def healthy() -> bool:
    return (ping("client", "10.10.3.20").reachable
            and inspect_dns("10.10.3.10", "web.anta.local").resolved
            and check_service("web-server", "web").response_code == "200")


def parse(argv: list) -> dict:
    o = {"system": "anta", "split": "all", "scenarios": None, "reps": 1, "force": False, "inject_only": False}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--system":
            o["system"] = argv[i + 1]; i += 2
        elif a == "--split":
            o["split"] = argv[i + 1]; i += 2
        elif a == "--scenarios":
            o["scenarios"] = argv[i + 1].split(","); i += 2
        elif a == "--reps":
            o["reps"] = int(argv[i + 1]); i += 2
        elif a == "--force":
            o["force"] = True; i += 1
        elif a == "--inject-only":
            o["inject_only"] = True; i += 1
        else:
            raise SystemExit(f"unknown option {a}")
    return o


def main(argv: list) -> int:
    o = parse(argv)
    scenarios = [json.loads(p.read_text()) for p in sorted(SCEN_DIR.glob("s*.json"))]
    if not scenarios:
        print("no scenarios found. Run: python3 -m benchmark.make_scenarios")
        return 1
    if o["split"] != "all":
        scenarios = [s for s in scenarios if s["split"] == o["split"]]
    if o["scenarios"]:
        scenarios = [s for s in scenarios if s["id"] in o["scenarios"]]

    if o["inject_only"]:
        for sc in scenarios:
            f = sc["injected_fault"]
            reset_network(); time.sleep(1)
            inject(f); time.sleep(1)
            r, d, w = ping("client", "10.10.3.20"), inspect_dns("10.10.3.10", "web.anta.local"), check_service("web-server", "web")
            print(f"{sc['id']} {sc['description'][:52]:52s} -> ping_web={r.reachable!s:5s} "
                  f"dns={(d.ip if d.resolved else d.error)!s:12s} web_local={w.response_code}")
            reset_network(); time.sleep(1)
            if not healthy():
                print(f"   !! network NOT healthy after reset ({sc['id']})")
        print("\ninject-only pass finished; every line should be followed by a healthy reset (no '!!' lines).")
        return 0

    system = o["system"]
    if system not in SYSTEMS:
        print(f"unknown system '{system}' (available: {', '.join(SYSTEMS)})")
        return 1
    con = connect()
    for sc in scenarios:
        for rep in range(1, o["reps"] + 1):
            run_id = f"{system}:{sc['id']}:{rep}"
            if not o["force"] and con.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone():
                print(f"skip {run_id} (already recorded)")
                continue
            f = sc["injected_fault"]
            print(f"\n=== {run_id} | {sc['tier']} | {sc['split']} | {f['type']} on {f.get('device')} ===", flush=True)
            out, err = None, None
            try:
                reset_network(); time.sleep(1)
                if not healthy():
                    raise RuntimeError("baseline not healthy after reset")
                inject(f); time.sleep(1)
                out = SYSTEMS[system](sc["symptom"])
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
            finally:
                try:
                    reset_network()
                except Exception as e2:
                    err = (err or "") + f" | reset failed: {e2}"
            row = evaluate(sc, out, err, system, run_id)
            insert(con, row)
            tag = "OK " if row["rca_ok"] else "MISS"
            print(f"{tag} truth={row['truth_cause']}@{row['truth_device']}  pred={row['pred_cause']}@{row['pred_device']} "
                  f"conf={row['confidence']} [{row['status']}] calls={row['tool_calls']} {row['seconds']}s {err or ''}")
    report(con, system)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
