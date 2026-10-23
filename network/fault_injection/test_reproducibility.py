#!/usr/bin/env python3
"""Phase 1 gate: each fault must inject, show its expected symptoms, and restore cleanly, repeatedly."""
import contextlib
import io
import sys
import time

import inject_route, restore_route
import inject_firewall, restore_firewall
import inject_dns, restore_dns
import inject_service, restore_service
from common import sh

ROUNDS = 3


def ping(src: str, dst: str) -> bool:
    return sh(src, f"ping -c 1 -W 2 {dst}", check=False).returncode == 0


def dns_ok() -> bool:
    r = sh("client", "dig +short +time=2 +tries=1 @10.10.3.10 web.anta.local", check=False)
    return r.stdout.strip() == "10.10.3.20"


def http_state() -> str:
    r = sh("client", "curl -s -o /dev/null -w %{http_code} --max-time 3 http://10.10.3.20/", check=False)
    if r.returncode == 0 and r.stdout.strip() == "200":
        return "200"
    return {7: "connfail", 28: "timeout"}.get(r.returncode, f"rc{r.returncode}")


def probe() -> dict:
    return {
        "ping_fw": ping("client", "10.10.2.3"),
        "ping_web": ping("client", "10.10.3.20"),
        "ping_dns": ping("client", "10.10.3.10"),
        "dns": dns_ok(),
        "http": http_state(),
    }


BASE = {"ping_fw": True, "ping_web": True, "ping_dns": True, "dns": True, "http": "200"}

FAULTS = {
    "broken_route": (inject_route.inject, restore_route.restore,
                     {**BASE, "ping_web": False, "ping_dns": False, "dns": False, "http": "connfail"}),
    "firewall_block": (inject_firewall.inject, restore_firewall.restore,
                       {**BASE, "http": "timeout"}),
    "dns_failure": (inject_dns.inject, restore_dns.restore,
                    {**BASE, "dns": False}),
    "service_failure": (inject_service.inject, restore_service.restore,
                        {**BASE, "http": "connfail"}),
}


def quiet(fn) -> None:
    with contextlib.redirect_stdout(io.StringIO()):
        fn()


def main() -> int:
    start = probe()
    if start != BASE:
        print(f"ABORT: network not healthy before test: {start}")
        return 1
    failures = 0
    for name, (inject, restore, expected) in FAULTS.items():
        for rnd in range(1, ROUNDS + 1):
            try:
                quiet(inject)
                time.sleep(1)
                got = probe()
            finally:
                quiet(restore)
                time.sleep(1)
            after = probe()
            if got == expected and after == BASE:
                print(f"PASS  {name} round {rnd}")
            else:
                failures += 1
                print(f"FAIL  {name} round {rnd}")
                if got != expected:
                    print(f"      symptom expected {expected}\n      symptom got      {got}")
                if after != BASE:
                    print(f"      after restore    {after}")
    print(f"\nResult: {len(FAULTS) * ROUNDS - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
