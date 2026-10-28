"""Shadow-gated remediation: diagnose -> propose -> test on the shadow -> apply to live only if the shadow agrees.
Usage (from ~/ANTA, venv active): python3 -m remediation.safe_pipeline ["symptom"] [--dry-run] [--no-apply]"""
from __future__ import annotations

import json
import sys
import time

from agent.anta import DEFAULT_SYMPTOM, run_agent
from agent.verifier import assess, health_fingerprint, state_snapshot, verification_tests

from . import shadow
from .actions import apply_action, plan_action, rollback_action


# findings that describe configuration state: identical on a faithful clone whatever the traffic does
STRUCTURAL = ("iface_up", "link_degraded", "route_complete", "fw_has_drop", "svc_up", "svc_local_ok", "dns_ip_correct")


def _comparable(anomalies: list, stochastic: bool = False) -> list:
    """Hit counters are not replayed by the clone, so ignore counter-derived findings when comparing.
    With packet loss or delay configured, few-probe symptom findings (ping, DNS query, traceroute) are random,
    so a faithful clone is judged on configuration-level findings only."""
    keep = [a for a in anomalies if not a.startswith("fw_drop_hits")]
    if stochastic:
        keep = [a for a in keep if a.split(":", 1)[0] in STRUCTURAL]
    return sorted(keep)


def _apply_and_assess(action, before_fp: dict, before_state: dict) -> dict:
    applied = apply_action(action)
    if not applied["ok"]:
        rollback_action(action)
    time.sleep(1)
    after_fp, after_state = health_fingerprint(), state_snapshot()
    verification = verification_tests()
    report = assess(action, before_fp, after_fp, before_state, after_state, verification)
    return {"applied": applied, "verification": verification, **report}


def remediate_gated(diagnosis: dict, action_factory=None, apply_live: bool = True, verbose: bool = True,
                    on_event=None) -> dict:
    """action_factory: zero-arg callable returning the Action; it is called once per stack so that the plan is
    built from that stack's own facts. Default: the playbook entry for the diagnosis.
    on_event(type, **data): optional progress hook (used by the dashboard)."""
    emit = on_event or (lambda *a, **k: None)
    t0 = time.time()
    factory = action_factory or (lambda: plan_action(diagnosis))
    live_fp, live_state = health_fingerprint(), state_snapshot()
    live_action = factory()
    out = {"decision": None, "reason": "", "action": live_action.to_log() if live_action else None,
           "shadow": None, "live": None, "live_untouched": None}

    if live_action is None:
        out.update(decision="no_action", reason="nothing to fix (no fault diagnosed or no playbook entry)")
        emit("decision", decision=out["decision"], reason=out["reason"])
    else:
        emit("fix_proposed", action=out["action"])
        shadow.up()
        emit("shadow", phase="cloning")
        clone = shadow.clone_live_to_shadow()
        emit("shadow", phase="cloned", summary=clone)
        with shadow.shadow_namespace():
            sh_fp, sh_state = health_fingerprint(), state_snapshot()
            stochastic = any(a.startswith("link_degraded:") for a in live_fp["anomalies"])
            fidelity = (_comparable(sh_fp["anomalies"], stochastic)
                        == _comparable(live_fp["anomalies"], stochastic))
            out["shadow"] = {"clone": clone, "fidelity": fidelity, "live_anomalies": live_fp["anomalies"],
                             "shadow_anomalies": sh_fp["anomalies"]}
            emit("shadow", phase="fidelity", ok=fidelity, live_anomalies=live_fp["anomalies"],
                 shadow_anomalies=sh_fp["anomalies"])
            if fidelity:
                res = _apply_and_assess(factory(), sh_fp, sh_state)
                out["shadow"].update(res)
                emit("shadow", phase="tested", fixed=res["fixed"], regression=res["regression"],
                     unintended=res["unintended_changes"] + res["newly_broken"], verification=res["verification"])
        sd = out["shadow"]
        if not fidelity:
            out.update(decision="blocked_inconclusive", reason="shadow did not reproduce the live symptoms")
        elif not sd["fixed"]:
            out.update(decision="blocked_failed_shadow", reason="fix did not restore service on the shadow")
        elif sd["regression"]:
            out.update(decision="blocked_failed_shadow",
                       reason="fix caused unintended changes on the shadow: " + "; ".join(sd["unintended_changes"][:2]))
        elif not apply_live:
            out.update(decision="approved_not_applied", reason="shadow validation passed (--no-apply)")
        else:
            out.update(decision="applied", reason="shadow validation passed")
        emit("decision", decision=out["decision"], reason=out["reason"])
        if out["decision"] == "applied":
            emit("live", phase="applying")
            out["live"] = _apply_and_assess(live_action, live_fp, live_state)
            emit("live", phase="result", fixed=out["live"]["fixed"], regression=out["live"]["regression"],
                 verification=out["live"]["verification"])
        else:
            out["live_untouched"] = state_snapshot() == live_state
            emit("live", phase="untouched", untouched=out["live_untouched"])
    out["seconds"] = round(time.time() - t0, 1)
    if verbose:
        _print(out)
    return out


def _print(out: dict) -> None:
    print("\n==================== SHADOW-GATED REMEDIATION ====================")
    print("Proposed fix :", out["action"]["description"] if out["action"] else "none")
    for c in (out["action"] or {}).get("commands", []):
        print("   ", c)
    sd = out["shadow"]
    if sd:
        print("Shadow       : fidelity (reproduces live symptoms) =", sd["fidelity"])
        if sd["fidelity"]:
            print("               shadow fixed =", sd["fixed"], "| regression =", sd["regression"],
                  sd["unintended_changes"] + sd["newly_broken"])
    print("DECISION     :", out["decision"], "-", out["reason"])
    if out["live"]:
        print("Live result  : fixed =", out["live"]["fixed"], "| regression =", out["live"]["regression"])
    if out["live_untouched"] is not None:
        print("Live network untouched:", out["live_untouched"])


def main(argv: list) -> int:
    args = [a for a in argv if not a.startswith("--")]
    res = run_agent(args[0] if args else DEFAULT_SYMPTOM, verbose=True)
    d = res["diagnosis"]
    print(f"\nANTA diagnosis: {d['cause']} on {d['device']} [{d['hypothesis_id']}, {d['status']}, {d['confidence']:.0%}]")
    if "--dry-run" in argv:
        action = plan_action(d)
        print("DRY RUN, planned action:", json.dumps(action.to_log() if action else None, indent=2))
        return 0
    remediate_gated(d, apply_live="--no-apply" not in argv)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
