"""Parameterized fault injection + idempotent network reset for benchmark scenarios."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from common import cname, sh

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "devices"
_IFACES_UP = ('for i in $(ls /sys/class/net); do [ "$i" = lo ] || '
              '{ ip link set "$i" up; tc qdisc del dev "$i" root 2>/dev/null; }; done; true')


def _iface_for(device: str, prefix: str) -> str:
    """Name of the interface carrying an address that starts with prefix (names are not stable across restarts)."""
    for e in json.loads(sh(device, "ip -j -4 addr show").stdout or "[]"):
        for a in e.get("addr_info", []):
            if a.get("local", "").startswith(prefix):
                return e["ifname"]
    raise RuntimeError(f"no interface on {device} with an address starting {prefix}")

BASELINE_ROUTES = {
    "client": ["default via 10.10.1.2"],
    "router": ["10.10.3.0/24 via 10.10.2.3"],
    "firewall": ["10.10.1.0/24 via 10.10.2.2"],
    "dns-server": ["default via 10.10.3.2"],
    "web-server": ["default via 10.10.3.2"],
}
NGINX_CONF = "/etc/nginx/nginx.conf"
DNS_CONF = "/etc/dnsmasq.conf"
_WAIT_GONE = "for i in 1 2 3 4 5 6 7 8 9 10; do pgrep -x {p} >/dev/null || break; sleep 0.2; done"


def _stop(device: str, proc: str) -> None:
    sh(device, f"pkill -x {proc}; {_WAIT_GONE.format(p=proc)}; ! pgrep -x {proc} >/dev/null")


def _push_config(node: str, rel: str, container_path: str, ip_prefix: str) -> None:
    """Copy the repo's known-good config into a container, rendered for that stack's IP plan."""
    text = (GOLDEN_DIR / rel).read_text().replace("10.10.", ip_prefix)
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".conf") as f:
        f.write(text)
    os.chmod(f.name, 0o644)
    subprocess.run(["docker", "cp", f.name, f"{cname(node)}:{container_path}"], check=True, capture_output=True)
    os.unlink(f.name)


def _start_dns() -> None:
    sh("dns-server", f"pkill -x dnsmasq; {_WAIT_GONE.format(p='dnsmasq')}; dnsmasq -C {DNS_CONF}")


def reset_network(ip_prefix: str = "10.10.") -> None:
    """Return every device to its baseline state (safe to call any number of times)."""
    for node in BASELINE_ROUTES:  # interfaces up and netem cleared before routes are restored
        sh(node, _IFACES_UP, check=False)
    for node, routes in BASELINE_ROUTES.items():
        routes = [r.replace("10.10.", ip_prefix) for r in routes]
        for r in routes:
            sh(node, f"ip route replace {r}")
    for node in ("router", "firewall"):
        sh(node, "iptables -F; iptables -X; iptables -P INPUT ACCEPT; "
                 "iptables -P FORWARD ACCEPT; iptables -P OUTPUT ACCEPT")
    _push_config("web-server", "web/nginx.conf", NGINX_CONF, ip_prefix)
    sh("web-server", f"if pgrep -x nginx >/dev/null; then nginx -s reload; else nginx -c {NGINX_CONF}; fi")
    _push_config("dns-server", "dns/dnsmasq.conf", DNS_CONF, ip_prefix)
    _start_dns()


def inject(fault: dict) -> None:
    mech = fault.get("mechanism", "none")
    dev = fault.get("device")
    if mech == "none":
        return
    if mech == "route_delete":
        sh(dev, f"ip route del {fault['dest']}")
    elif mech == "iptables":
        action = fault.get("action", "DROP")
        spec = f"-p {fault['protocol']}"
        if fault.get("port"):
            spec += f" --dport {fault['port']}"
        spec += f" -j {action}"
        if action == "REJECT" and fault["protocol"] == "tcp":
            spec += " --reject-with tcp-reset"
        sh(dev, f"iptables -I FORWARD {spec}")
    elif mech == "iface_down":
        sh(dev, f"ip link set {_iface_for(dev, fault['subnet'])} down")
    elif mech == "netem":
        spec = ""
        if fault.get("delay_ms"):
            spec += f" delay {fault['delay_ms']}ms"
        if fault.get("loss_pct"):
            spec += f" loss {fault['loss_pct']}%"
        sh(dev, f"tc qdisc replace dev {_iface_for(dev, fault['subnet'])} root netem{spec}")
    elif mech == "iptables_policy":
        sh(dev, f"iptables -P {fault.get('chain', 'FORWARD')} DROP")
    elif mech == "service_stop":
        _stop(dev, fault["process"])
    elif mech == "nginx_503":
        sh(dev, f"sed -i 's/return 200/return 503/' {NGINX_CONF}; nginx -s reload")
    elif mech == "dns_wrong_ip":
        sh(dev, f"sed -i 's#^address=/web.anta.local/.*#address=/web.anta.local/{fault['wrong_ip']}#' {DNS_CONF}")
        _start_dns()
    else:
        raise ValueError(f"unknown mechanism '{mech}'")
