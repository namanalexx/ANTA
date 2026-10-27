"""Shadow network: a second Docker Compose stack (10.20.x.x) that mirrors the lab.
It is a *static clone*: a snapshot of the live state is replayed onto it at proposal time, never kept in sync."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time

from agent import ROOT
from scenario_faults import reset_network
from tools.base import NODES, namespace

COMPOSE = ROOT / "network" / "topology" / "docker-compose.shadow.yml"
PREFIX = "shadow-"
IP_MAP = ("10.10.", "10.20.")
SERVICES = [("dns-server", "dnsmasq", "dnsmasq -C /etc/dnsmasq.conf"),
            ("web-server", "nginx", "nginx -c /etc/nginx/nginx.conf")]
CONFIGS = [("dns-server", "/etc/dnsmasq.conf", "pkill -x dnsmasq; sleep 0.5; dnsmasq -C /etc/dnsmasq.conf"),
           ("web-server", "/etc/nginx/nginx.conf", "nginx -s reload || nginx -c /etc/nginx/nginx.conf")]


def shadow_namespace():
    """Context manager: every tool / verifier call inside it targets the shadow stack."""
    return namespace(PREFIX, IP_MAP)


def _dx(container: str, cmd: str, stdin=None) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "exec", "-i", container, "sh", "-c", cmd],
                          input=stdin, capture_output=True, text=True)


def _tr(text: str) -> str:
    return text.replace(IP_MAP[0], IP_MAP[1])


def is_up() -> bool:
    names = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True).stdout.split()
    return all(f"{PREFIX}{n}" in names for n in NODES)


def up() -> None:
    if is_up():
        return
    r = subprocess.run(["docker", "compose", "-f", str(COMPOSE), "up", "-d"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"cannot start shadow stack: {r.stderr[-300:]}")
    time.sleep(6)


def down() -> None:
    subprocess.run(["docker", "compose", "-f", str(COMPOSE), "down"], capture_output=True, text=True)


def reset() -> None:
    """Return the shadow to its healthy baseline."""
    with shadow_namespace():
        reset_network("10.20.")


def clone_live_to_shadow() -> dict:
    """Replay the live lab's CURRENT state (firewall rules, routes, services, configs) onto a fresh shadow."""
    reset()
    summary: dict = {"iptables": [], "routes": [], "configs": [], "services": [], "interfaces": []}

    for node in ("router", "firewall"):  # firewall rules and chain policies
        dump = _dx(node, "iptables-save -t filter").stdout
        r = _dx(f"{PREFIX}{node}", "iptables-restore", stdin=_tr(dump))
        summary["iptables"].append(f"{node}:rc={r.returncode}")

    for node in NODES:  # interface state and packet-loss/delay settings (matched by IP, names differ per stack)
        live_if = json.loads(_dx(node, "ip -j addr show").stdout or "[]")
        shad_if = json.loads(_dx(f"{PREFIX}{node}", "ip -j addr show").stdout or "[]")
        by_ip = {a["local"]: e["ifname"] for e in shad_if for a in e.get("addr_info", []) if a.get("family") == "inet"}
        qdisc = _dx(node, "tc qdisc show").stdout
        for e in live_if:
            ip = next((a["local"] for a in e.get("addr_info", []) if a.get("family") == "inet"), None)
            target = by_ip.get(_tr(ip)) if ip else None
            if not target or e.get("ifname") == "lo":
                continue
            m = re.search(rf"qdisc netem \S+ dev {re.escape(e['ifname'])} .*?\blimit \d+\s*(.*)$", qdisc, re.M)
            if m:
                args = m.group(1).strip()
                _dx(f"{PREFIX}{node}", f"tc qdisc replace dev {target} root netem {args}")
                summary["interfaces"].append(f"{node}: {target} netem {args}")
            if "UP" not in e.get("flags", []):
                _dx(f"{PREFIX}{node}", f"ip link set {target} down")
                summary["interfaces"].append(f"{node}: {target} down")
    for node in NODES:  # routes: make the shadow's static routes match live
        live = json.loads(_dx(node, "ip -j route").stdout or "[]")
        shad = json.loads(_dx(f"{PREFIX}{node}", "ip -j route").stdout or "[]")
        live_t = {(_tr(x.get("dst", "")), _tr(x["gateway"]) if x.get("gateway") else None) for x in live}
        shad_t = {(x.get("dst", ""), x.get("gateway")) for x in shad}
        for dst, gw in shad_t - live_t:
            if gw or dst == "default":
                _dx(f"{PREFIX}{node}", f"ip route del {dst}")
                summary["routes"].append(f"{node}: del {dst}")
        for dst, gw in live_t - shad_t:
            if gw:
                _dx(f"{PREFIX}{node}", f"ip route replace {dst} via {gw}")
                summary["routes"].append(f"{node}: add {dst} via {gw}")

    for node, path, restart in CONFIGS:  # configs (translated to the shadow IP plan)
        want = _tr(_dx(node, f"cat {path}").stdout)
        if want != _dx(f"{PREFIX}{node}", f"cat {path}").stdout:
            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".conf") as f:
                f.write(want)
            subprocess.run(["docker", "cp", f.name, f"{PREFIX}{node}:{path}"], capture_output=True, text=True)
            os.unlink(f.name)
            _dx(f"{PREFIX}{node}", restart)
            summary["configs"].append(f"{node}:{path}")

    for node, proc, start in SERVICES:  # service up/down state
        live_up = _dx(node, f"pgrep -x {proc}").returncode == 0
        shadow_up = _dx(f"{PREFIX}{node}", f"pgrep -x {proc}").returncode == 0
        if live_up and not shadow_up:
            _dx(f"{PREFIX}{node}", start)
            summary["services"].append(f"{node}: started {proc}")
        elif not live_up and shadow_up:
            _dx(f"{PREFIX}{node}", f"pkill -x {proc}; sleep 0.5")
            summary["services"].append(f"{node}: stopped {proc}")
    return summary


if __name__ == "__main__":
    from agent.verifier import health_fingerprint
    up()
    reset()
    with shadow_namespace():
        fp = health_fingerprint()
    print("shadow healthy:", not fp["anomalies"], fp["anomalies"])
