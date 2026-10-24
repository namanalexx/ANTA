"""Investigation strategy: test catalog, finding extraction, test ranking, LLM test selection."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from tools import TOOLS, to_dict

from . import llm

CAP_PATTERNS = ["tcp_syn_unanswered", "tcp_rst_seen", "tcp_handshake_seen", "no_traffic"]


@dataclass
class Test:
    id: str
    description: str
    tool: str
    args: dict
    keys: list
    meta: dict = field(default_factory=dict)


@dataclass
class Ctx:
    topo: dict
    ip_to_node: dict
    attached: dict
    all_subnets: list
    web_ip: str = ""

    def missing_routes(self, node: str, routes: list) -> list:
        dests = {r["dest"] for r in routes}
        if "default" in dests:
            return []
        mine = self.attached.get(node, set())
        return [s for s in self.all_subnets if s not in mine and s not in dests]


def build_context(topo: dict) -> Ctx:
    ips = topo["ip_assignments"]
    ip_to_node = {ip: n for n, nets in ips.items() for ip in nets.values() if ip}
    attached: dict = {n: set() for n in topo["nodes"]}
    for link in topo["links"]:
        for m in link["members"]:
            attached.setdefault(m, set()).add(link["subnet"])
    return Ctx(topo, ip_to_node, attached, [l["subnet"] for l in topo["links"]],
               next(iter(ips["web-server"].values()), ""))


def build_catalog(ctx: Ctx) -> dict:
    ips = ctx.topo["ip_assignments"]
    client_net = next(iter(ips["client"]))
    core_net = next(n for n in ips["router"] if n != client_net)
    targets = {
        "router": ips["router"][client_net],
        "firewall": ips["firewall"][core_net],
        "dns-server": next(iter(ips["dns-server"].values())),
        "web-server": next(iter(ips["web-server"].values())),
    }
    web, dns = targets["web-server"], targets["dns-server"]
    tests: list = []
    for label, ip in targets.items():
        k = f"client->{label}"
        tests.append(Test(f"ping_client_{label}", f"Ping {label} ({ip}) from client", "ping",
                          {"src": "client", "dst": ip},
                          [f"reach:{k}", f"unreach_from:{k}", f"unreach_mode:{k}"], {"label": label}))
    tests.append(Test("trace_client_web", "Traceroute from client to web-server", "traceroute",
                      {"src": "client", "dst": web},
                      ["trace_reached:client->web-server", "trace_last_hop:client->web-server"]))
    tests.append(Test("dns_query", "Ask the DNS server to resolve web.anta.local (from client)", "inspect_dns",
                      {"server": dns, "host": "web.anta.local", "src": "client"},
                      ["dns_resolves", "dns_error", "dns_ip_correct"]))
    for node in ("client", "router", "firewall", "dns-server", "web-server"):
        tests.append(Test(f"routes_{node}", f"Check the {node} routing table for missing routes",
                          "get_route_table", {"node": node}, [f"route_complete:{node}"], {"node": node}))
    for node in ("router", "firewall"):
        tests.append(Test(f"fw_{node}", f"Inspect {node} firewall rules and hit counters",
                          "inspect_firewall", {"node": node},
                          [f"fw_has_drop:{node}", f"fw_drop_hits:{node}"], {"node": node}))
    tests.append(Test("svc_web", "Check the web service on web-server", "check_service",
                      {"node": "web-server", "svc": "web"},
                      ["svc_up:web-server:web", "svc_local_ok:web-server"]))
    tests.append(Test("svc_dns", "Check the DNS service on dns-server", "check_service",
                      {"node": "dns-server", "svc": "dns"}, ["svc_up:dns-server:dns"]))
    probe = {"kind": "http", "src": "client", "dst": web}
    for node in ("firewall", "web-server"):
        tests.append(Test(f"cap_{node}_http", f"Capture packets on {node} while the client makes an HTTP request",
                          "capture_packets", {"node": node, "iface": "any", "duration_s": 6, "probe": probe},
                          [f"cap:{node}:{p}" for p in CAP_PATTERNS], {"node": node}))
    return {t.id: t for t in tests}


# ------------------------------------------------------------------ finding extractors
def _x_ping(t, r, ctx):
    k = f"{t.args['src']}->{t.meta['label']}"
    f = {f"reach:{k}": r["reachable"]}
    if r["reachable"]:
        return f"ping {k}: OK ({r['packet_loss_pct']:.0f}% loss, {r['avg_rtt_ms']} ms)", f
    frm = ctx.ip_to_node.get(r["error_from"], "none") if r["error_from"] else "none"
    f[f"unreach_mode:{k}"] = r["failure_mode"]
    f[f"unreach_from:{k}"] = frm
    extra = f", ICMP error from {frm}" if frm != "none" else ""
    return f"ping {k}: FAILED ({r['failure_mode']}{extra})", f


def _x_trace(t, r, ctx):
    k = f"{t.args['src']}->web-server"
    last = None
    for h in r["hops"]:
        if h["ip"]:
            last = ctx.ip_to_node.get(h["ip"], h["ip"])
    f = {f"trace_reached:{k}": r["reached"], f"trace_last_hop:{k}": last or "none"}
    state = "reached" if r["reached"] else "NOT reached"
    return f"traceroute {k}: {state}, last responding hop: {last or 'none'}", f


def _x_dns(t, r, ctx):
    f = {"dns_resolves": r["resolved"], "dns_error": r["error"] or "none"}
    if r["resolved"]:
        correct = r["ip"] == ctx.web_ip
        f["dns_ip_correct"] = correct
        note = "" if correct else f" (WRONG: web server is {ctx.web_ip})"
        return f"dns {r['host']} via {r['server']}: resolved to {r['ip']}{note}", f
    return f"dns {r['host']} via {r['server']}: FAILED ({r['error']})", f


def _x_routes(t, r, ctx):
    node = t.meta["node"]
    missing = ctx.missing_routes(node, r["routes"])
    f = {f"route_complete:{node}": not missing}
    if missing:
        return f"routes {node}: MISSING route to {', '.join(missing)}", f
    return f"routes {node}: complete (all subnets reachable)", f


_FLOWS = [("tcp", 80), ("udp", 53), ("icmp", None)]  # the flows this lab cares about: http, dns, ping


def _port_match(spec, port):
    if spec is None or port is None:
        return True
    try:
        if ":" in str(spec):
            lo, hi = str(spec).split(":", 1)
            return int(lo or 0) <= port <= int(hi or 65535)
        return int(spec) == port
    except ValueError:
        return False


def _blocks_relevant_flow(rule):
    for proto, port in _FLOWS:
        dport = None if proto == "icmp" else rule["dport"]
        if rule["protocol"] in ("all", proto) and _port_match(dport, port):
            return True
    return False


def _x_fw(t, r, ctx):
    node = t.meta["node"]
    drops = [(c["name"], x) for c in r["chains"] for x in c["rules"] if x["target"] in ("DROP", "REJECT")]
    relevant = [(c, x) for c, x in drops if _blocks_relevant_flow(x)]
    policy = [c["name"] for c in r["chains"]
              if c["policy"] in ("DROP", "REJECT") and c["name"] in ("INPUT", "FORWARD")]
    has_drop = bool(relevant or policy)
    f = {f"fw_has_drop:{node}": has_drop}
    if any(x["packets"] > 0 for _, x in relevant):
        f[f"fw_drop_hits:{node}"] = True  # zero hits is not evidence against a rule, so only emit when True
    ignored = len(drops) - len(relevant)
    note = f" ({ignored} other DROP/REJECT rule(s) do not affect http/dns/ping)" if ignored else ""
    if not has_drop:
        return f"firewall {node}: no rule blocks http/dns/ping, policies ACCEPT{note}", f
    parts = [f"{c}: {x['spec']} (hits {x['packets']})" for c, x in relevant] + [f"policy DROP on {c}" for c in policy]
    return f"firewall {node}: " + "; ".join(parts) + note, f


def _x_svc(t, r, ctx):
    node, svc = r["node"], r["service"]
    f = {f"svc_up:{node}:{svc}": bool(r["running"] and r["port_open"])}
    if svc == "web":
        f[f"svc_local_ok:{node}"] = r["response_code"] == "200"
    return (f"service {svc} on {node}: running={r['running']}, port_open={r['port_open']}, "
            f"local response={r['response_code']}"), f


def _x_cap(t, r, ctx):
    node = t.meta["node"]
    pats = set(r["patterns"])
    f = {f"cap:{node}:{p}": (p in pats) for p in CAP_PATTERNS}
    return (f"capture on {node} during client HTTP request: {r['packet_count']} packets; "
            f"patterns: {', '.join(r['patterns']) or 'none'}"), f


_EXTRACTORS = {
    "ping": _x_ping, "traceroute": _x_trace, "inspect_dns": _x_dns, "get_route_table": _x_routes,
    "inspect_firewall": _x_fw, "check_service": _x_svc, "capture_packets": _x_cap,
}


def run_test(test: Test, ctx: Ctx):
    """Run one test. Returns (summary, findings, raw_tool_result)."""
    result = to_dict(TOOLS[test.tool]["fn"](**test.args))
    if result.get("tool_error"):
        return f"{test.id}: tool error ({result['tool_error']})", {}, result
    summary, findings = _EXTRACTORS[test.tool](test, result, ctx)
    return summary, findings, result


# ------------------------------------------------------------------ ranking + LLM choice
def rank_tests(catalog: dict, executed: set, hyps: list) -> list:
    """Rank unexecuted tests by how well they split the active hypotheses (weighted by evidence strength)."""
    active = [h for h in hyps if h.status != "rejected"]
    total = sum(h.confidence for h in active) or 1.0
    scored = []
    for t in catalog.values():
        if t.id in executed:
            continue
        score = 0.0
        for key in t.keys:
            groups: dict = {}
            maxlr = 1.0
            for h in active:
                p = h.predictions.get(key)
                g = repr(p.expected) if p else "none"
                groups[g] = groups.get(g, 0.0) + h.confidence / total
                if p:
                    maxlr = max(maxlr, p.lr)
            score += (1 - sum(v * v for v in groups.values())) * math.log(maxlr + 1)
        scored.append((score, t))
    scored.sort(key=lambda x: -x[0])
    return scored


PLAN_SYSTEM = (
    "You are the planner of a network troubleshooting agent. Several hypotheses compete to explain a reported "
    "symptom. Pick the ONE next diagnostic test that best separates the leading hypotheses. "
    "Choose only from the candidate list. "
    'Reply with JSON only: {"test": "<candidate id>", "reason": "<one short sentence>"}'
)


def choose_test(symptom: str, hyps: list, evidence_lines: list, ranked: list, k: int = 6):
    """Returns (test, reason, llm_choice_was_valid)."""
    candidates = [t for _, t in ranked[:k]]
    leaders = sorted([h for h in hyps if h.status != "rejected"], key=lambda h: -h.confidence)
    prompt = "\n".join([
        f"Symptom: {symptom}",
        "Hypotheses (confidence computed from evidence so far):",
        *[f"  {h.id} {h.cause} at {h.device} ({h.layer}): {h.confidence:.0%}" for h in leaders],
        "Evidence so far:",
        *[f"  {line}" for line in evidence_lines],
        "Candidate tests:",
        *[f"  - {t.id}: {t.description}" for t in candidates],
    ])
    try:
        out = llm.chat_json(PLAN_SYSTEM, prompt)
    except llm.LLMError as e:
        return candidates[0], f"fallback (LLM unavailable: {e})", False
    tid = str(out.get("test", "")).strip()
    match = next((t for t in candidates if t.id == tid), None)
    if match:
        return match, str(out.get("reason", ""))[:200], True
    return candidates[0], f"fallback (LLM picked invalid test '{tid[:40]}')", False
