"""Phase 2 gate: every tool returns valid JSON on the healthy network and under each fault,
with the fingerprint we expect. Run: python3 -m tools.gate  (from ~/ANTA/network)"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fault_injection"))
import inject_route, restore_route  # noqa: E402
import inject_firewall, restore_firewall  # noqa: E402
import inject_dns, restore_dns  # noqa: E402
import inject_service, restore_service  # noqa: E402

from .base import TOOLS, to_json  # noqa: E402
from .diagnostics import (  # noqa: E402
    capture_packets, check_service, get_arp_table, get_interface_status, get_logs,
    get_route_table, get_topology, inspect_dns, inspect_firewall, ping, traceroute,
)

RESULTS: list[bool] = []
WEB, DNS = "10.10.3.20", "10.10.3.10"
HTTP_PROBE = {"kind": "http", "src": "client", "dst": WEB}


def check(name: str, cond, detail=None) -> None:
    ok_ = bool(cond)
    RESULTS.append(ok_)
    print(("PASS  " if ok_ else "FAIL  ") + name + ("" if ok_ else f"\n        -> {detail}"))


def valid(label: str, r):
    try:
        json.loads(to_json(r))
        good = True
    except Exception:
        good = False
    check(f"{label}: valid JSON, no tool_error", good and r.tool_error is None, r.tool_error)
    return r


def quiet(fn) -> None:
    with contextlib.redirect_stdout(io.StringIO()):
        fn()


def drop_rule(fw):
    return next((r for c in fw.chains if c.name == "FORWARD" for r in c.rules
                 if r.target == "DROP" and r.dport == "80"), None)


def healthy() -> None:
    print("== healthy network ==")
    check("11 tools registered", len(TOOLS) == 11, list(TOOLS))
    t = valid("get_topology", get_topology())
    check("topology: 5 nodes, 3 segments, router on 2 networks",
          len(t.nodes) == 5 and len(t.links) == 3 and len(t.ip_assignments.get("router", {})) == 2, t)
    i = valid("get_interface_status(router)", get_interface_status("router"))
    check("router: 2 interfaces, both up", len(i.interfaces) == 2 and all(x.status == "up" for x in i.interfaces), i)
    rt = valid("get_route_table(router)", get_route_table("router"))
    check("router route 10.10.3.0/24 via 10.10.2.3",
          any(r.dest == "10.10.3.0/24" and r.gateway == "10.10.2.3" for r in rt.routes), rt)
    p = valid("ping(client->web)", ping("client", WEB))
    check("ping reachable, 0% loss", p.reachable and p.packet_loss_pct == 0.0 and p.failure_mode == "none", p)
    a = valid("get_arp_table(client)", get_arp_table("client"))
    check("client ARP has router 10.10.1.2 with a MAC", any(e.ip == "10.10.1.2" and e.mac for e in a.entries), a)
    tr = valid("traceroute(client->web)", traceroute("client", WEB))
    check("traceroute path router -> firewall -> web", tr.reached and
          [h.ip for h in tr.hops] == ["10.10.1.2", "10.10.2.3", WEB], tr)
    d = valid("inspect_dns", inspect_dns(DNS, "web.anta.local"))
    check("dns resolves web.anta.local -> 10.10.3.20", d.resolved and d.ip == WEB and d.error is None, d)
    fw = valid("inspect_firewall(firewall)", inspect_firewall("firewall"))
    fwd = next((c for c in fw.chains if c.name == "FORWARD"), None)
    check("firewall FORWARD policy ACCEPT, no DROP rules",
          fwd is not None and fwd.policy == "ACCEPT" and not any(r.target == "DROP" for r in fwd.rules), fw)
    w = valid("check_service(web-server, web)", check_service("web-server", "web"))
    check("web: running, port open, 200", w.running and w.port_open and w.response_code == "200", w)
    s = valid("check_service(dns-server, dns)", check_service("dns-server", "dns"))
    check("dns: running, port open, NOERROR", s.running and s.port_open and s.response_code == "NOERROR", s)
    c = valid("capture_packets(firewall)", capture_packets("firewall", "any", 6, probe=HTTP_PROBE))
    check("capture sees completed TCP handshake", c.packet_count > 0 and "tcp_handshake_seen" in c.patterns, c)
    lw = valid("get_logs(web-server)", get_logs("web-server"))
    check("web logs contain a GET request", any("GET" in e.message for e in lw.entries), lw)
    ld = valid("get_logs(dns-server)", get_logs("dns-server"))
    check("dns logs contain a web.anta.local query", any("web.anta.local" in e.message for e in ld.entries), ld)


def run_fault(name: str, inject, restore, assertions) -> None:
    print(f"== fault: {name} ==")
    try:
        quiet(inject)
        time.sleep(1)
        assertions()
    finally:
        quiet(restore)
        time.sleep(1)
    r, d, s = ping("client", WEB), inspect_dns(DNS, "web.anta.local"), check_service("web-server", "web")
    check(f"{name}: restored to healthy", r.reachable and d.resolved and s.response_code == "200", (r, d, s))


def a_route() -> None:
    p = ping("client", WEB)
    check("ping fails with net_unreachable reported by router 10.10.1.2",
          not p.reachable and p.failure_mode == "net_unreachable" and p.error_from == "10.10.1.2", p)
    rt = get_route_table("router")
    check("router has no route to 10.10.3.0/24", not any(r.dest == "10.10.3.0/24" for r in rt.routes), rt)
    check("traceroute does not reach web-server", not traceroute("client", WEB).reached)
    d = inspect_dns(DNS, "web.anta.local")
    check("dns fails (unreachable/timeout)", not d.resolved and d.error in ("unreachable", "timeout"), d)


def a_firewall() -> None:
    p = ping("client", WEB)
    check("ping still works", p.reachable, p)
    w = check_service("web-server", "web")
    check("web-server itself is healthy (running, 200 locally)", w.running and w.port_open and w.response_code == "200", w)
    check("dns still resolves", inspect_dns(DNS, "web.anta.local").resolved)
    c = capture_packets("firewall", "any", 6, probe=HTTP_PROBE)
    check("capture: SYNs unanswered", "tcp_syn_unanswered" in c.patterns, c)
    rule = drop_rule(inspect_firewall("firewall"))
    check("firewall has DROP tcp/80 rule in FORWARD", rule is not None and rule.protocol == "tcp", rule)
    check("DROP rule hit counter > 0", rule is not None and rule.packets > 0, rule)


def a_dns() -> None:
    d = inspect_dns(DNS, "web.anta.local")
    check("dns query refused", not d.resolved and d.error == "refused", d)
    s = check_service("dns-server", "dns")
    check("dns service not running, port closed", not s.running and not s.port_open, s)
    check("dns-server still pingable", ping("client", DNS).reachable)


def a_service() -> None:
    w = check_service("web-server", "web")
    check("web service down, port closed, no local response",
          not w.running and not w.port_open and w.response_code is None, w)
    c = capture_packets("web-server", "any", 6, probe=HTTP_PROBE)
    check("capture: server answers SYN with RST", "tcp_rst_seen" in c.patterns, c)
    check("web-server still pingable", ping("client", WEB).reachable)
    check("dns still resolves", inspect_dns(DNS, "web.anta.local").resolved)


def main() -> int:
    healthy()
    run_fault("broken_route", inject_route.inject, restore_route.restore, a_route)
    run_fault("firewall_block", inject_firewall.inject, restore_firewall.restore, a_firewall)
    run_fault("dns_failure", inject_dns.inject, restore_dns.restore, a_dns)
    run_fault("service_failure", inject_service.inject, restore_service.restore, a_service)
    passed = sum(RESULTS)
    print(f"\nResult: {passed} passed, {len(RESULTS) - passed} failed")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
