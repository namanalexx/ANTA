"""Parameterized fault injection + idempotent network reset for benchmark scenarios."""
from __future__ import annotations

from common import sh

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


def _start_dns() -> None:
    sh("dns-server", f"pkill -x dnsmasq; {_WAIT_GONE.format(p='dnsmasq')}; dnsmasq -C {DNS_CONF}")


def reset_network() -> None:
    """Return every device to its baseline state (safe to call any number of times)."""
    for node, routes in BASELINE_ROUTES.items():
        for r in routes:
            sh(node, f"ip route replace {r}")
    for node in ("router", "firewall"):
        sh(node, "iptables -F; iptables -X; iptables -P INPUT ACCEPT; "
                 "iptables -P FORWARD ACCEPT; iptables -P OUTPUT ACCEPT")
    sh("web-server", f"sed -i 's/return 503/return 200/' {NGINX_CONF}; "
                     f"if pgrep -x nginx >/dev/null; then nginx -s reload; else nginx -c {NGINX_CONF}; fi")
    sh("dns-server", f"sed -i 's#^address=/web.anta.local/.*#address=/web.anta.local/10.10.3.20#' {DNS_CONF}")
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
