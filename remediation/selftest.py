"""Self-test of the regression detector: deliberately BAD fixes must be flagged, good ones must not.
Usage (from ~/ANTA, venv active): python3 -m remediation.selftest"""
from __future__ import annotations

import sys
import time

from common import sh
from scenario_faults import inject, reset_network

from . import pipeline as P
from .actions import Action, Step, plan_action

FW_DROP = {"mechanism": "iptables", "device": "firewall", "protocol": "tcp", "port": 80, "action": "DROP"}
DNS_STOP = {"mechanism": "service_stop", "device": "dns-server", "process": "dnsmasq"}
WEB_STOP = {"mechanism": "service_stop", "device": "web-server", "process": "nginx"}
RESULTS: list = []


def run_case(name, fault, setup, action, diagnosis, expect_fixed, expect_regression, expect_in=None) -> None:
    reset_network(); time.sleep(1)
    inject(fault); time.sleep(1)
    if setup:
        setup()
    P.plan_action = lambda d: action  # force the action under test
    rem = P.remediate(diagnosis, verbose=False)
    checks = [("fixed", rem["fixed"] == expect_fixed), ("regression", rem["regression"] == expect_regression)]
    if expect_in:
        checks.append((f"flags '{expect_in}'", any(expect_in in u for u in rem["unintended_changes"])))
    ok = all(c for _, c in checks)
    RESULTS.append(ok)
    print(("PASS  " if ok else "FAIL  ") + name + "   " + " ".join(f"{n}={'ok' if c else 'WRONG'}" for n, c in checks))
    if not ok:
        print("      got:", {k: rem[k] for k in ("fixed", "regression", "unintended_changes",
                                                  "newly_broken", "residual_anomalies")})


def main() -> int:
    # A. over-broad fix: flushes the chain, removing the real block AND an unrelated harmless rule
    flush = Action("overbroad_flush", "H3", "firewall", "flush the whole FORWARD chain",
                   steps=[Step("firewall", "iptables -F FORWARD", "flush FORWARD chain")],
                   touches={"iptables:firewall"},
                   allowed_removed={"iptables:firewall": ["rule|FORWARD|-p tcp -m tcp --dport 80 -j DROP"]})
    run_case("over-broad fix is flagged (removes a harmless rule)", FW_DROP,
             lambda: sh("firewall", "iptables -I FORWARD -p tcp --dport 8080 -j DROP"), flush,
             {"cause": "firewall_block", "hypothesis_id": "H3", "device": "firewall"},
             expect_fixed=True, expect_regression=True, expect_in="iptables:firewall")

    # B. collateral damage: correct DNS fix plus a bug that deletes the client's default route
    dns_fix = plan_action({"cause": "dns_failure", "hypothesis_id": "H5", "device": "dns-server"})
    dns_fix.steps.append(Step("client", "ip route del default", "(bug) remove client default route"))
    run_case("collateral damage is flagged (client loses its route)", DNS_STOP, None, dns_fix,
             {"cause": "dns_failure", "hypothesis_id": "H5", "device": "dns-server"},
             expect_fixed=False, expect_regression=True, expect_in="routes:client")

    # C. a fix that does nothing: not fixed, but also not a regression
    noop = Action("noop", "H6", "web-server", "does nothing")
    run_case("do-nothing fix is not fixed and not a regression", WEB_STOP, None, noop,
             {"cause": "service_failure", "hypothesis_id": "H6", "device": "web-server"},
             expect_fixed=False, expect_regression=False)

    # D. the correct fix: fixed and clean (no false alarm)
    good = plan_action({"cause": "service_failure", "hypothesis_id": "H6", "device": "web-server"})
    run_case("correct fix is fixed and clean", WEB_STOP, None, good,
             {"cause": "service_failure", "hypothesis_id": "H6", "device": "web-server"},
             expect_fixed=True, expect_regression=False)

    reset_network()
    print(f"\nResult: {sum(RESULTS)}/{len(RESULTS)} passed")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
