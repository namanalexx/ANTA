"""The 11 ANTA diagnostic tools. Each returns a dataclass (see models.py); none returns raw terminal output."""
from __future__ import annotations

import json
import re
import shlex
import subprocess
import time
from typing import Optional

from .base import NODES, ToolError, check_node, check_target, cname, docker, run, tool
from .models import (
    ArpEntry, ArpTable, CaptureResult, DnsResult, FirewallChain, FirewallRule, FirewallState,
    Hop, Interface, InterfaceStatus, Link, LogEntry, LogResult, PingResult, Route, RouteTable,
    ServiceStatus, Topology, TracerouteResult,
)


# ----------------------------------------------------------------------------- helpers
def _ip_json(node: str, cmd: str) -> list:
    rc, out, _ = run(node, cmd)
    if rc != 0:
        raise ToolError(f"{node}: '{cmd}' failed")
    out = out.strip()
    if not out:
        return []
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        raise ToolError(f"{node}: could not parse '{cmd}' output")


def _own_ipv4(node: str) -> Optional[str]:
    for e in _ip_json(node, "ip -j -4 addr show scope global"):
        for a in e.get("addr_info", []):
            if a.get("family") == "inet":
                return a["local"]
    return None


# ----------------------------------------------------------------------------- 1. topology
@tool(Topology, "Discover nodes, L2 segments (links) and IP assignments of the lab network.")
def get_topology() -> Topology:
    try:
        containers = json.loads(docker("inspect", *[cname(n) for n in NODES]))
    except ValueError:
        raise ToolError("could not parse docker inspect output")
    by_name = {c["Name"].lstrip("/")[len(cname("")):]: c for c in containers}
    ip_assignments: dict[str, dict[str, str]] = {}
    members: dict[str, list[str]] = {}
    for n in NODES:
        c = by_name.get(n)
        if not c:
            continue
        ip_assignments[n] = {}
        for net, info in c["NetworkSettings"]["Networks"].items():
            ip_assignments[n][net] = info.get("IPAddress", "")
            members.setdefault(net, []).append(n)
    nets = sorted(members)
    subnets: dict[str, str] = {}
    if nets:
        try:
            for nd in json.loads(docker("network", "inspect", *nets)):
                cfg = nd.get("IPAM", {}).get("Config") or []
                subnets[nd["Name"]] = cfg[0]["Subnet"] if cfg else ""
        except ValueError:
            raise ToolError("could not parse docker network inspect output")
    links = [Link(network=n, subnet=subnets.get(n, ""), members=members[n]) for n in nets]
    return Topology(nodes=[n for n in NODES if n in by_name], links=links, ip_assignments=ip_assignments)


# ----------------------------------------------------------------------------- 2. interfaces
@tool(InterfaceStatus, "List a node's interfaces with link status, IPv4 address and MAC.")
def get_interface_status(node: str) -> InterfaceStatus:
    check_node(node)
    interfaces = []
    for e in _ip_json(node, "ip -j addr show"):
        if e.get("ifname") == "lo":
            continue
        flags = e.get("flags", [])
        up = "UP" in flags and "LOWER_UP" in flags
        ip = next((f"{a['local']}/{a['prefixlen']}" for a in e.get("addr_info", [])
                   if a.get("family") == "inet"), None)
        interfaces.append(Interface(name=e.get("ifname", ""), status="up" if up else "down",
                                    ip=ip, mac=e.get("address")))
    _, qout, _ = run(node, "tc qdisc show")
    netem = {}
    for line in qout.splitlines():
        m = re.match(r"qdisc netem \S+ dev (\S+) .*?\blimit \d+\s*(.*)$", line.strip())
        if m:
            netem[m.group(1)] = m.group(2).strip() or "netem"
    for i in interfaces:
        i.netem = netem.get(i.name)
    return InterfaceStatus(node=node, interfaces=interfaces)


# ----------------------------------------------------------------------------- 3. routes
@tool(RouteTable, "Show a node's IPv4 routing table (destination, gateway, interface, metric).")
def get_route_table(node: str) -> RouteTable:
    check_node(node)
    routes = [Route(dest=r.get("dst", "?"), gateway=r.get("gateway"), iface=r.get("dev"),
                    metric=r.get("metric")) for r in _ip_json(node, "ip -j route show")]
    return RouteTable(node=node, routes=routes)


# ----------------------------------------------------------------------------- 4. ARP
@tool(ArpTable, "Show a node's IPv4 neighbor (ARP) table with entry states.")
def get_arp_table(node: str) -> ArpTable:
    check_node(node)
    entries = []
    for e in _ip_json(node, "ip -j neigh show"):
        if ":" in e.get("dst", ""):
            continue
        state = e.get("state") or [""]
        entries.append(ArpEntry(ip=e.get("dst", ""), mac=e.get("lladdr"), iface=e.get("dev"),
                                state=state[0] if isinstance(state, list) else str(state)))
    return ArpTable(node=node, entries=entries)


# ----------------------------------------------------------------------------- 5. ping
@tool(PingResult, "Ping dst from src (3 probes). Reports loss, RTT and the failure mode "
                  "(timeout vs ICMP unreachable, and which device sent it).")
def ping(src: str, dst: str, count: int = 3, interval: float = 0.3) -> PingResult:
    check_node(src)
    check_target(dst, "destination")
    count = max(1, min(int(count), 50))
    interval = max(0.2, min(float(interval), 1.0))
    _, out, err = run(src, f"ping -c {count} -W 1 -i {interval} {dst}", timeout=40)
    text = out + "\n" + err
    m = re.search(r"(\d+) packets transmitted, (\d+) (?:packets )?received.*?([\d.]+)% packet loss", text)
    sent, recv, loss = (int(m.group(1)), int(m.group(2)), float(m.group(3))) if m else (0, 0, 100.0)
    rtt = re.search(r"=\s*[\d.]+/([\d.]+)/", text)
    u = re.search(r"From\s+(\S+?):?\s+icmp_seq=\d+\s+Destination\s+(Net|Host)\s+Unreachable", text)
    if recv > 0:
        mode = "none"
    elif "Network is unreachable" in text:
        mode = "local_no_route"
    elif u:
        mode = "net_unreachable" if u.group(2) == "Net" else "host_unreachable"
    else:
        mode = "timeout"
    return PingResult(
        src=src, dst=dst, reachable=recv > 0, packets_sent=sent, packets_received=recv,
        packet_loss_pct=loss, avg_rtt_ms=float(rtt.group(1)) if rtt else None,
        failure_mode=mode, error_from=u.group(1) if (u and recv == 0) else None,
    )


# ----------------------------------------------------------------------------- 6. traceroute
@tool(TracerouteResult, "Trace the path from src to dst (max 6 hops). Hops show IP, RTT, timeout or ICMP flag.")
def traceroute(src: str, dst: str) -> TracerouteResult:
    check_node(src)
    check_target(dst, "destination")
    _, out, _ = run(src, f"traceroute -n -w 1 -q 1 -m 6 {dst}", timeout=30)
    hops: list[Hop] = []
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(.*\S)\s*$", line)
        if not m:
            continue
        n, rest = int(m.group(1)), m.group(2)
        if rest.startswith("*"):
            hops.append(Hop(hop=n, timeout=True))
            continue
        mm = re.match(r"(\S+)\s+([\d.]+)\s+ms(?:\s+(![A-Z0-9]*))?", rest)
        if mm:
            hops.append(Hop(hop=n, ip=mm.group(1), rtt_ms=float(mm.group(2)), flag=mm.group(3)))
    reached = any(h.ip == dst and not h.flag for h in hops)
    return TracerouteResult(src=src, dst=dst, reached=reached, hops=hops)


# ----------------------------------------------------------------------------- 7. DNS
@tool(DnsResult, "Query a DNS server for a hostname (from a vantage node, default client). "
                 "Reports resolution, answer IP, latency and error type.")
def inspect_dns(server: str, host: str, src: str = "client") -> DnsResult:
    check_node(src)
    check_target(server, "dns server")
    check_target(host, "hostname")
    _, out, err = run(src, f"dig +time=2 +tries=1 @{server} {host}")
    text = out + "\n" + err
    rc_m = re.search(r"status:\s*(\w+)", text)
    answers = re.findall(r"^\S+\s+\d+\s+IN\s+A\s+(\d+\.\d+\.\d+\.\d+)\s*$", text, re.M)
    qt = re.search(r"Query time:\s*(\d+)\s*msec", text)
    rcode = rc_m.group(1) if rc_m else None
    error: Optional[str]
    if rcode:
        if rcode == "NOERROR" and answers:
            error = None
        elif rcode == "NXDOMAIN":
            error = "nxdomain"
        elif rcode == "NOERROR":
            error = "no_answer"
        else:
            error = rcode.lower()
    else:
        low = text.lower()
        if "connection refused" in low:
            error = "refused"
        elif "unreachable" in low:
            error = "unreachable"
        elif "timed out" in low or "no servers could be reached" in low:
            error = "timeout"
        else:
            error = "no_response"
    return DnsResult(
        server=server, host=host, queried_from=src, resolved=error is None,
        ip=answers[0] if (answers and error is None) else None,
        response_time_ms=int(qt.group(1)) if qt else None, rcode=rcode, error=error,
    )


# ----------------------------------------------------------------------------- 8. firewall
def _parse_rule(number: int, spec: str, packets: int, nbytes: int) -> FirewallRule:
    toks = shlex.split(spec)
    r = FirewallRule(number=number, packets=packets, bytes=nbytes, spec=spec)
    i = 0
    while i < len(toks):
        t = toks[i]
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        if t in ("-p", "--protocol") and nxt:
            r.protocol = nxt; i += 2
        elif t in ("-s", "--source") and nxt:
            r.source = nxt; i += 2
        elif t in ("-d", "--destination") and nxt:
            r.destination = nxt; i += 2
        elif t in ("-i", "--in-interface") and nxt:
            r.in_iface = nxt; i += 2
        elif t in ("-o", "--out-interface") and nxt:
            r.out_iface = nxt; i += 2
        elif t == "--dport" and nxt:
            r.dport = nxt; i += 2
        elif t == "--sport" and nxt:
            r.sport = nxt; i += 2
        elif t in ("-j", "-g") and nxt:
            r.target = nxt; i += 2
        elif t == "-m" and nxt:
            i += 2
        else:
            i += 1
    return r


@tool(FirewallState, "Show a node's iptables filter table: chain policies and rules with hit counters.")
def inspect_firewall(node: str) -> FirewallState:
    check_node(node)
    rc, out, _ = run(node, "iptables-save -c -t filter")
    if rc != 0:
        raise ToolError(f"{node}: iptables-save failed")
    chains: dict[str, FirewallChain] = {}
    for line in out.splitlines():
        line = line.strip()
        m = re.match(r"^:(\S+)\s+(\S+)\s+\[(\d+):(\d+)\]", line)
        if m:
            chains[m.group(1)] = FirewallChain(name=m.group(1), policy=m.group(2),
                                               packets=int(m.group(3)), bytes=int(m.group(4)))
            continue
        m = re.match(r"^\[(\d+):(\d+)\]\s+-A\s+(\S+)\s+(.*)$", line)
        if m:
            chain = chains.setdefault(m.group(3), FirewallChain(name=m.group(3)))
            chain.rules.append(_parse_rule(len(chain.rules) + 1, m.group(4),
                                           int(m.group(1)), int(m.group(2))))
    return FirewallState(node=node, chains=list(chains.values()))


# ----------------------------------------------------------------------------- 9. capture
_PROBES = {
    "ping": "ping -c 3 -W 1 -i 0.3 {dst}",
    "http": "curl -s -o /dev/null --max-time 3 http://{dst}/",
    "dns": "dig +time=1 +tries=1 @{dst} web.anta.local",
}
_PROBE_FILTERS = {"ping": "icmp", "http": "tcp port 80 or icmp", "dns": "udp port 53 or icmp"}
_TS = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d+\s")
_DIR = re.compile(r"^\S+\s+\S+\s+(In|Out)\s")
_FLOW = re.compile(r"\bIP6?\s+(\S+)\s+>\s+(\S+?):")
_FLAGS = re.compile(r"Flags \[([A-Za-z.]+)\]")


@tool(CaptureResult, "Capture packets on a node for a few seconds (optionally while generating a probe: "
                     "kind ping|http|dns from a source node to a destination) and report traffic patterns.")
def capture_packets(node: str, iface: str = "any", duration_s: int = 6, bpf: str = "",
                    probe: Optional[dict] = None) -> CaptureResult:
    check_node(node)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", iface or ""):
        raise ToolError(f"invalid interface '{iface}'")
    duration_s = max(2, min(int(duration_s), 15))
    if probe:
        if probe.get("kind") not in _PROBES:
            raise ToolError(f"unknown probe kind (valid: {', '.join(_PROBES)})")
        check_node(probe.get("src", ""))
        check_target(probe.get("dst", ""), "probe destination")
    if probe and not bpf:
        bpf = _PROBE_FILTERS[probe["kind"]]  # ignore background noise such as ARP
    cmd = f"timeout {duration_s} tcpdump -l -nn -i {iface} -c 300"
    if bpf:
        cmd += " " + shlex.quote(bpf)
    proc = subprocess.Popen(["docker", "exec", cname(node), "sh", "-c", cmd],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        time.sleep(1.0)  # let tcpdump start listening
        if probe:
            run(probe["src"], _PROBES[probe["kind"]].format(dst=probe["dst"]), timeout=duration_s + 10)
        try:
            out, err = proc.communicate(timeout=duration_s + 5)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
    finally:
        if proc.poll() is None:
            proc.kill()
    if "listening on" not in err:
        raise ToolError(f"capture failed on {node}:{iface}")

    summary = {k: 0 for k in ("tcp_syn", "tcp_syn_in", "tcp_syn_out", "tcp_synack", "tcp_rst",
                              "icmp_echo_request", "icmp_echo_reply", "icmp_unreachable",
                              "dns_queries", "dns_responses")}
    syn_seen: dict[tuple, int] = {}
    count = 0
    for line in out.splitlines():
        if not _TS.match(line):
            continue
        count += 1
        d = _DIR.match(line)
        direction = d.group(1).lower() if d else "na"
        if "ICMP" in line:
            if "echo request" in line:
                summary["icmp_echo_request"] += 1
            elif "echo reply" in line:
                summary["icmp_echo_reply"] += 1
            elif "unreachable" in line:
                summary["icmp_unreachable"] += 1
            continue
        f = _FLAGS.search(line)
        if f:
            flags = f.group(1)
            if flags == "S":
                summary["tcp_syn"] += 1
                if direction == "in":
                    summary["tcp_syn_in"] += 1
                elif direction == "out":
                    summary["tcp_syn_out"] += 1
                fl = _FLOW.search(line)
                key = (direction, fl.group(1), fl.group(2)) if fl else (direction,)
                syn_seen[key] = syn_seen.get(key, 0) + 1
            elif flags == "S.":
                summary["tcp_synack"] += 1
            elif "R" in flags:
                summary["tcp_rst"] += 1
            continue
        if re.search(r">\s+\S+\.53:\s", line):
            summary["dns_queries"] += 1
        elif re.search(r"\S+\.53\s+>\s", line):
            summary["dns_responses"] += 1

    patterns: list[str] = []
    if count == 0:
        patterns.append("no_traffic")
    if summary["tcp_syn"] and not summary["tcp_synack"] and not summary["tcp_rst"]:
        patterns.append("tcp_syn_unanswered")
    if any(v >= 2 for v in syn_seen.values()):
        patterns.append("tcp_syn_retransmissions")
    if summary["tcp_rst"]:
        patterns.append("tcp_rst_seen")
    if summary["tcp_synack"]:
        patterns.append("tcp_handshake_seen")
    if summary["icmp_echo_request"] and not summary["icmp_echo_reply"]:
        patterns.append("icmp_echo_unanswered")
    if summary["icmp_unreachable"]:
        patterns.append("icmp_unreachable_seen")
    if summary["dns_queries"] and not summary["dns_responses"]:
        patterns.append("dns_query_unanswered")
    return CaptureResult(node=node, interface=iface, packet_count=count, summary=summary, patterns=patterns)


# ----------------------------------------------------------------------------- 10. service
_SERVICES = {
    "web": {"proc": "nginx", "port": 80, "ss": "-H -ltn"},
    "dns": {"proc": "dnsmasq", "port": 53, "ss": "-H -lun"},
}
_ALIASES = {"web": "web", "nginx": "web", "http": "web", "dns": "dns", "dnsmasq": "dns"}


@tool(ServiceStatus, "Check a service on a node (web|nginx|http or dns|dnsmasq): process running, "
                     "port listening, and local response (HTTP code or DNS rcode).")
def check_service(node: str, svc: str) -> ServiceStatus:
    check_node(node)
    key = _ALIASES.get((svc or "").lower())
    if not key:
        raise ToolError(f"unknown service '{svc}' (valid: {', '.join(sorted(_ALIASES))})")
    spec = _SERVICES[key]
    running = run(node, f"pgrep -x {spec['proc']}")[0] == 0
    port_open = run(node, f"ss {spec['ss']} 'sport = :{spec['port']}' | grep -q .")[0] == 0
    code: Optional[str] = None
    if key == "web":
        rc, out, _ = run(node, "curl -s -o /dev/null -w %{http_code} --max-time 2 http://127.0.0.1:80/")
        code = out.strip() if rc == 0 else None
    else:
        ip = _own_ipv4(node)
        if ip:
            _, out, err = run(node, f"dig +time=1 +tries=1 @{ip} web.anta.local")
            m = re.search(r"status:\s*(\w+)", out + err)
            code = m.group(1) if m else None
    return ServiceStatus(node=node, service=key, running=running, port_open=port_open, response_code=code)


# ----------------------------------------------------------------------------- 11. logs
_LOG_FILES = {
    "dns-server": [("/var/log/dnsmasq.log", "dnsmasq")],
    "web-server": [("/var/log/nginx/access.log", "nginx-access"),
                   ("/var/log/nginx/error.log", "nginx-error")],
}


def _parse_log_line(kind: str, line: str) -> LogEntry:
    if kind == "dnsmasq":
        m = re.match(r"^(\w{3}\s+\d+\s+[\d:]{8})\s+dnsmasq\[\d+\]:\s+(.*)$", line)
        if m:
            return LogEntry(m.group(1), "info", m.group(2), kind)
    elif kind == "nginx-access":
        m = re.match(r'^(\S+) \S+ \S+ \[([^\]]+)\] "([^"]*)" (\d{3}) ', line)
        if m:
            status = int(m.group(4))
            level = "error" if status >= 500 else "warn" if status >= 400 else "info"
            return LogEntry(m.group(2), level, f"{m.group(1)} {m.group(3)} -> {status}", kind)
    elif kind == "nginx-error":
        m = re.match(r"^(\d{4}/\d\d/\d\d \d\d:\d\d:\d\d) \[(\w+)\] (.*)$", line)
        if m:
            lvl = {"crit": "error", "alert": "error", "emerg": "error", "notice": "info"}.get(m.group(2), m.group(2))
            return LogEntry(m.group(1), lvl, m.group(3), kind)
    elif kind == "container":
        m = re.match(r"^(\S+Z)\s+(.*)$", line)
        if m:
            return LogEntry(m.group(1), "info", m.group(2), kind)
    return LogEntry("", "info", line.strip(), kind)


@tool(LogResult, "Read recent log entries for a node (container output plus dnsmasq / nginx logs where applicable).")
def get_logs(node: str, limit: int = 40) -> LogResult:
    check_node(node)
    limit = max(1, min(int(limit), 200))
    entries: list[LogEntry] = []
    for line in docker("logs", "--tail", str(limit), "-t", cname(node), merge_stderr=True).splitlines():
        if line.strip():
            entries.append(_parse_log_line("container", line))
    for path, kind in _LOG_FILES.get(node, []):
        _, out, _ = run(node, f"tail -n {limit} {path} 2>/dev/null")
        for line in out.splitlines():
            if line.strip():
                entries.append(_parse_log_line(kind, line))
    return LogResult(node=node, entries=entries[-limit:])
