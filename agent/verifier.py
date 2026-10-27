"""Post-remediation verification, health fingerprint and regression detection."""
from __future__ import annotations

from common import sh
from tools import (TOOLS, check_service, get_interface_status, get_route_table, inspect_dns, inspect_firewall,
                   ping, to_dict)

from .hypotheses import healthy_value
from .planner import build_catalog, build_context, run_test

NODES = ["client", "router", "firewall", "dns-server", "web-server"]


def _context():
    topo = to_dict(TOOLS["get_topology"]["fn"]())
    ctx = build_context(topo)
    dns_ip = next(iter(topo["ip_assignments"]["dns-server"].values()))
    return ctx, build_catalog(ctx), dns_ip


def verification_tests() -> dict:
    """The three scenario-level checks: ping, HTTP 200 and DNS."""
    ctx, _, dns_ip = _context()
    p = ping("client", ctx.web_ip)
    d = inspect_dns(dns_ip, "web.anta.local")
    http = sh("client", f"curl -s -o /dev/null -w %{{http_code}} --max-time 3 http://{ctx.web_ip}/", check=False)
    return {"ping_success": bool(p.reachable), "http_200": http.stdout.strip() == "200",
            "dns_resolves": bool(d.resolved and d.ip == ctx.web_ip)}


def health_fingerprint(include_capture: bool = False) -> dict:
    """Run the standard checks and list every finding that differs from a healthy network."""
    ctx, catalog, _ = _context()
    findings: dict = {}
    for t in catalog.values():
        if t.tool == "capture_packets" and not include_capture:
            continue
        _, f, _ = run_test(t, ctx)
        findings.update(f)
    anomalies = sorted(k for k, v in findings.items()
                       if healthy_value(k) is not None and v != healthy_value(k))
    return {"findings": findings, "anomalies": anomalies}


def state_snapshot() -> dict:
    """Comparable view of everything a fix could touch: routes, firewall rules, services, configs."""
    snap: dict = {}
    for n in NODES:
        r = to_dict(get_route_table(n))
        snap[f"routes:{n}"] = sorted(f"{x['dest']}|{x['gateway'] or ''}" for x in r["routes"])
    for n in NODES:
        st = to_dict(get_interface_status(n))
        snap[f"iface:{n}"] = sorted(f"{i['name']}|{i['status']}|{i['netem'] or ''}" for i in st["interfaces"])
    for n in ("router", "firewall"):
        fw = to_dict(inspect_firewall(n))
        items = []
        for c in fw["chains"]:
            items.append(f"policy|{c['name']}|{c['policy']}")
            items += [f"rule|{c['name']}|{x['spec']}" for x in c["rules"]]
        snap[f"iptables:{n}"] = sorted(items)
    for n, svc in (("web-server", "web"), ("dns-server", "dns")):
        s = to_dict(check_service(n, svc))
        snap[f"svc:{n}"] = sorted([f"running={s['running']}", f"port_open={s['port_open']}"])
    for n, path in (("web-server", "/etc/nginx/nginx.conf"), ("dns-server", "/etc/dnsmasq.conf")):
        snap[f"config:{n}"] = [sh(n, f"md5sum {path} | cut -d' ' -f1", check=False).stdout.strip()]
    return snap


def unintended_changes(before: dict, after: dict, action) -> list:
    """Anything that changed beyond what the action declared it would change."""
    touches = getattr(action, "touches", set())
    free = getattr(action, "free_keys", set())
    ok_add = getattr(action, "allowed_added", {})
    ok_rem = getattr(action, "allowed_removed", {})
    bad = []
    for key in sorted(set(before) | set(after)):
        b, a = set(before.get(key, [])), set(after.get(key, []))
        if b == a or key in free:
            continue
        added, removed = a - b, b - a
        if key not in touches:
            bad.append(f"{key}: unexpected change (+{sorted(added)} -{sorted(removed)})")
            continue
        extra_add = added - set(ok_add.get(key, []))
        extra_rem = removed - set(ok_rem.get(key, []))
        if extra_add or extra_rem:
            bad.append(f"{key}: beyond declared change (+{sorted(extra_add)} -{sorted(extra_rem)})")
    return bad


def assess(action, before_fp: dict, after_fp: dict, before_state: dict, after_state: dict,
           verification: dict) -> dict:
    residual = list(after_fp["anomalies"])
    newly_broken = [k for k in residual if k not in before_fp["anomalies"]]
    unintended = unintended_changes(before_state, after_state, action)
    return {
        "fixed": bool(all(verification.values()) and not residual),
        "regression": bool(newly_broken or unintended),
        "residual_anomalies": residual, "newly_broken": newly_broken, "unintended_changes": unintended,
    }
