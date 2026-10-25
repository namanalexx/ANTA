"""Remediation pipeline: plan -> apply -> verify -> regression check.
Usage (from ~/ANTA, venv active):
  python3 -m remediation.pipeline ["symptom"] [--dry-run]   # diagnose the live network with ANTA, then fix it"""
from __future__ import annotations

import json
import sys
import time

from agent.anta import DEFAULT_SYMPTOM, run_agent
from agent.verifier import assess, health_fingerprint, state_snapshot, verification_tests

from .actions import apply_action, plan_action, rollback_action


def remediate(diagnosis: dict, verbose: bool = True) -> dict:
    t0 = time.time()
    before_fp, before_state = health_fingerprint(), state_snapshot()
    action = plan_action(diagnosis)
    applied = {"ok": True, "log": []}
    if action is not None:
        applied = apply_action(action)
        if not applied["ok"]:
            rollback_action(action)
    time.sleep(1)
    after_fp, after_state = health_fingerprint(), state_snapshot()
    verification = verification_tests()
    report = assess(action, before_fp, after_fp, before_state, after_state, verification)
    out = {"action": action.to_log() if action else None, "applied": applied, "verification": verification,
           **report, "seconds": round(time.time() - t0, 1)}
    if verbose:
        print("\n==================== REMEDIATION ====================")
        print("Action      :", out["action"]["description"] if out["action"] else "none (no fault diagnosed)")
        for c in (out["action"] or {}).get("commands", []):
            print("   ", c)
        print("Applied OK  :", applied["ok"])
        print("Verification:", verification)
        print("Fixed       :", out["fixed"], "| residual anomalies:", out["residual_anomalies"])
        print("Regression  :", out["regression"], out["unintended_changes"] + out["newly_broken"])
    return out


def main(argv: list) -> int:
    dry = "--dry-run" in argv
    args = [a for a in argv if not a.startswith("--")]
    res = run_agent(args[0] if args else DEFAULT_SYMPTOM, verbose=True)
    d = res["diagnosis"]
    print(f"\nANTA diagnosis: {d['cause']} on {d['device']} [{d['hypothesis_id']}, {d['status']}, {d['confidence']:.0%}]")
    if dry:
        action = plan_action(d)
        print("DRY RUN, planned action:", json.dumps(action.to_log() if action else None, indent=2))
        return 0
    remediate(d, verbose=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
