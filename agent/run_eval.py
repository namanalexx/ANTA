"""Phase 3 gate: inject each fault, let ANTA diagnose it, score against ground truth, restore.
Usage (from ~/ANTA, venv active): python3 -m agent.run_eval [--rounds N] [--faults broken_route,dns_failure]"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import time
from datetime import datetime

import inject_dns, restore_dns  # noqa: E402
import inject_firewall, restore_firewall  # noqa: E402
import inject_route, restore_route  # noqa: E402
import inject_service, restore_service  # noqa: E402
from tools import check_service, inspect_dns, ping  # noqa: E402

from . import ROOT, llm  # noqa: E402
from .anta import DEFAULT_SYMPTOM, run_agent  # noqa: E402

FAULTS = {
    "broken_route": (inject_route.inject, restore_route.restore),
    "firewall_block": (inject_firewall.inject, restore_firewall.restore),
    "dns_failure": (inject_dns.inject, restore_dns.restore),
    "service_failure": (inject_service.inject, restore_service.restore),
}
GROUND_TRUTH = {
    "broken_route": {"device": "router", "layer": "L3", "cause": "broken_route"},
    "firewall_block": {"device": "firewall", "layer": "L4", "cause": "firewall_block"},
    "dns_failure": {"device": "dns-server", "layer": "APP", "cause": "dns_failure"},
    "service_failure": {"device": "web-server", "layer": "L7", "cause": "service_failure"},
}


def quiet(fn) -> None:
    with contextlib.redirect_stdout(io.StringIO()):
        fn()


def healthy() -> bool:
    return (ping("client", "10.10.3.20").reachable
            and inspect_dns("10.10.3.10", "web.anta.local").resolved
            and check_service("web-server", "web").response_code == "200")


def main(argv: list) -> int:
    rounds, names = 1, list(FAULTS)
    if "--rounds" in argv:
        rounds = int(argv[argv.index("--rounds") + 1])
    if "--faults" in argv:
        names = argv[argv.index("--faults") + 1].split(",")
    if not healthy():
        print("ABORT: lab is not healthy. Run ./verify_topology.sh from ~/ANTA/network first.")
        return 1

    runs = []
    for name in names:
        inject, restore = FAULTS[name]
        gt = GROUND_TRUTH[name]
        for rnd in range(1, rounds + 1):
            print(f"\n######## {name} round {rnd}/{rounds} ########", flush=True)
            res, err = None, None
            try:
                quiet(inject)
                time.sleep(1)
                res = run_agent(DEFAULT_SYMPTOM, verbose=True)
            except Exception as e:  # keep the eval going; always restore
                err = f"{type(e).__name__}: {e}"
            finally:
                quiet(restore)
                time.sleep(1)
            if res:
                d = res["diagnosis"]
                row = {
                    "fault": name, "round": rnd, "truth": gt, "predicted": d,
                    "cause_ok": d["cause"] == gt["cause"] and d["device"] == gt["device"],
                    "device_ok": d["device"] == gt["device"], "layer_ok": d["layer"] == gt["layer"],
                    "confirmed": d["status"] == "confirmed", "stats": res["stats"],
                    "evidence_ids": res["evidence_ids"], "error": None,
                }
            else:
                row = {"fault": name, "round": rnd, "truth": gt, "cause_ok": False, "device_ok": False,
                       "layer_ok": False, "confirmed": False, "stats": {}, "error": err}
            row["restored_ok"] = healthy()
            runs.append(row)

    print("\n==================== PHASE 3 RESULTS ====================")
    for r in runs:
        p = r.get("predicted") or {}
        print(f"{r['fault']:16s} r{r['round']}: predicted {p.get('cause', '-')}@{p.get('device', '-')} "
              f"({p.get('layer', '-')}) {p.get('confidence', 0):.0%} [{p.get('status', r['error'])}]  "
              f"RCA {'OK' if r['cause_ok'] else 'WRONG'} | device {'OK' if r['device_ok'] else 'WRONG'} | "
              f"layer {'OK' if r['layer_ok'] else 'WRONG'} | calls {r['stats'].get('tool_calls', '-')} | "
              f"{r['stats'].get('seconds', '-')}s | restored {'yes' if r['restored_ok'] else 'NO'}")
    diagnosed = 0
    for name in names:
        mine = [r for r in runs if r["fault"] == name]
        if mine and sum(r["cause_ok"] for r in mine) / len(mine) >= 0.5:
            diagnosed += 1
    n_ok = sum(r["cause_ok"] for r in runs)
    avg_calls = sum(r["stats"].get("tool_calls", 0) for r in runs) / max(len(runs), 1)
    print(f"\nRCA correct: {n_ok}/{len(runs)} runs | fault types diagnosed: {diagnosed}/{len(names)} | "
          f"avg tool calls: {avg_calls:.1f} | model: {llm.MODEL}")
    gate = diagnosed >= 3
    print("PHASE 3 GATE (>= 3 of 4 fault types diagnosed): " + ("PASS" if gate else "FAIL - fix before benchmark"))

    out_dir = ROOT / "experiments" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"phase3_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps({"model": llm.MODEL, "runs": runs}, indent=2))
    print(f"saved: {path}")
    return 0 if gate else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
