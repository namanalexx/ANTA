"""Remediation action library: small, deterministic, reviewable fixes with explicit commands and rollbacks.
The LLM never writes commands. Facts come from the Phase 2 tools; fixes come from this playbook."""
from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from agent import ROOT
from agent.planner import _blocks_relevant_flow, build_context
from common import sh
from tools import TOOLS, get_interface_status, get_route_table, inspect_firewall, to_dict
from tools.base import cname, current_ip_map

GOLDEN = {  # known-good configs live in the repo and are the source of truth
    "dns-server": (ROOT / "network" / "devices" / "dns" / "dnsmasq.conf", "/etc/dnsmasq.conf"),
    "web-server": (ROOT / "network" / "devices" / "web" / "nginx.conf", "/etc/nginx/nginx.conf"),
}
START = {"nginx": "nginx -c /etc/nginx/nginx.conf", "dnsmasq": "dnsmasq -C /etc/dnsmasq.conf"}
RESTART = {
    "dns-server": "pkill -x dnsmasq; sleep 0.5; dnsmasq -C /etc/dnsmasq.conf",
    "web-server": "nginx -s reload || nginx -c /etc/nginx/nginx.conf",
}
PLAYBOOK = {  # hypothesis id -> action
    "H1": "restore_routes", "H2": "restore_routes", "H7": "restore_routes", "H8": "restore_routes",
    "H9": "restore_routes", "H3": "remove_blocking_rules", "H4": "remove_blocking_rules",
    "H5": "start_service", "H6": "start_service", "H10": "restore_config", "H11": "restore_config",
    "H12": "bring_interface_up", "H13": "bring_interface_up", "H14": "bring_interface_up",
    "H15": "bring_interface_up", "H16": "bring_interface_up",
    "H17": "clear_netem", "H18": "clear_netem", "H19": "clear_netem", "H20": "clear_netem", "H21": "clear_netem",
}
SERVICE_OF = {"H5": "dnsmasq", "H6": "nginx"}


@dataclass
class Step:
    container: str
    command: str
    description: str = ""
    host_path: str = ""       # set for docker cp steps
    container_path: str = ""


@dataclass
class Action:
    id: str
    hypothesis_id: str
    device: str
    description: str
    steps: list = field(default_factory=list)
    rollback: list = field(default_factory=list)
    touches: set = field(default_factory=set)         # snapshot keys this action is allowed to change
    free_keys: set = field(default_factory=set)       # keys where any change is expected (e.g. config hash)
    allowed_added: dict = field(default_factory=dict)
    allowed_removed: dict = field(default_factory=dict)

    def to_log(self) -> dict:
        cmds = [f"[docker cp] {s.host_path} -> {s.container}:{s.container_path}" if s.host_path
                else f"[{s.container}] {s.command}" for s in self.steps]
        return {"id": self.id, "hypothesis_id": self.hypothesis_id, "device": self.device,
                "description": self.description, "commands": cmds}


def _topo() -> dict:
    return to_dict(TOOLS["get_topology"]["fn"]())


def _plan_routes(hid: str, device: str) -> Action:
    topo = _topo()
    ctx = build_context(topo)
    ips = topo["ip_assignments"]
    missing = ctx.missing_routes(device, to_dict(get_route_table(device))["routes"])
    steps, rollback, added = [], [], []
    if len(ips[device]) == 1:  # endpoint: needs a default route via the gateway on its network
        net = next(iter(ips[device]))
        gw = next((ips[n][net] for n in ips if n != device and net in ips[n] and len(ips[n]) > 1), None)
        if missing and gw:
            steps.append(Step(device, f"ip route replace default via {gw}", f"restore default route via {gw}"))
            rollback.append(Step(device, "ip route del default", "remove default route"))
            added.append(f"default|{gw}")
    else:  # forwarder: needs a static route to each missing subnet via the neighbour that owns it
        for subnet in missing:
            hop = None
            for n in ips:
                if n == device or subnet not in ctx.attached.get(n, set()):
                    continue
                shared = [net for net in ips[device] if net in ips[n]]
                if shared:
                    hop = ips[n][shared[0]]
                    break
            if hop:
                steps.append(Step(device, f"ip route replace {subnet} via {hop}", f"restore route {subnet} via {hop}"))
                rollback.append(Step(device, f"ip route del {subnet}", f"remove route {subnet}"))
                added.append(f"{subnet}|{hop}")
    key = f"routes:{device}"
    return Action("restore_routes", hid, device, f"Restore {len(steps)} missing route(s) on {device}",
                  steps, rollback, {key}, set(), {key: added}, {})


def _plan_firewall(hid: str, device: str) -> Action:
    fw = to_dict(inspect_firewall(device))
    steps, rollback, added, removed = [], [], [], []
    for c in fw["chains"]:
        for r in c["rules"]:
            if r["target"] in ("DROP", "REJECT") and _blocks_relevant_flow(r):  # leave harmless rules alone
                steps.append(Step(device, f"iptables -D {c['name']} {r['spec']}", f"delete rule: {r['spec']}"))
                rollback.append(Step(device, f"iptables -I {c['name']} {r['spec']}", f"re-add rule: {r['spec']}"))
                removed.append(f"rule|{c['name']}|{r['spec']}")
        if c["policy"] in ("DROP", "REJECT") and c["name"] in ("INPUT", "FORWARD"):
            steps.append(Step(device, f"iptables -P {c['name']} ACCEPT", f"set {c['name']} policy to ACCEPT"))
            rollback.append(Step(device, f"iptables -P {c['name']} {c['policy']}", f"restore {c['name']} policy"))
            removed.append(f"policy|{c['name']}|{c['policy']}")
            added.append(f"policy|{c['name']}|ACCEPT")
    key = f"iptables:{device}"
    return Action("remove_blocking_rules", hid, device,
                  f"Remove {len(steps)} blocking firewall rule(s) on {device}",
                  steps, rollback, {key}, set(), {key: added}, {key: removed})


def _plan_service(hid: str, device: str) -> Action:
    proc = SERVICE_OF[hid]
    key = f"svc:{device}"
    return Action("start_service", hid, device, f"Start {proc} on {device}",
                  [Step(device, f"pgrep -x {proc} >/dev/null || {START[proc]}", f"start {proc}")],
                  [Step(device, f"pkill -x {proc}", f"stop {proc}")], {key}, set(),
                  {key: ["running=True", "port_open=True"]}, {key: ["running=False", "port_open=False"]})


def _plan_config(hid: str, device: str) -> Action:
    host, path = GOLDEN[device]
    key = f"config:{device}"
    return Action("restore_config", hid, device, f"Restore the known-good config of {device}",
                  [Step(device, f"cp {path} {path}.bak", "back up the current config"),
                   Step(device, "", "copy known-good config from the repo", str(host), path),
                   Step(device, RESTART[device], "reload with the known-good config")],
                  [Step(device, f"cp {path}.bak {path}; {RESTART[device]}", "restore the previous config")],
                  {key}, {key})


def _plan_iface_up(hid: str, device: str) -> Action:
    st = to_dict(get_interface_status(device))
    down = [i["name"] for i in st["interfaces"] if i["status"] != "up"]
    steps = [Step(device, f"ip link set {n} up", f"bring interface {n} up") for n in down]
    rollback = [Step(device, f"ip link set {n} down", f"take interface {n} down") for n in down]
    routes = _plan_routes(hid, device)  # static routes are dropped when a link goes down: restore them once it is up
    steps += routes.steps
    rollback += routes.rollback
    ikey, rkey = f"iface:{device}", f"routes:{device}"
    return Action("bring_interface_up", hid, device,
                  f"Bring {', '.join(down) or 'no'} interface(s) up on {device} and restore its routes",
                  steps, rollback, {ikey, rkey}, {rkey},
                  {ikey: [f"{n}|up|" for n in down], rkey: routes.allowed_added.get(rkey, [])},
                  {ikey: [f"{n}|down|" for n in down]})


def _plan_netem(hid: str, device: str) -> Action:
    st = to_dict(get_interface_status(device))
    shaped = [(i["name"], i["netem"]) for i in st["interfaces"] if i.get("netem")]
    steps = [Step(device, f"tc qdisc del dev {n} root", f"remove packet-loss/delay setting on {n}") for n, _ in shaped]
    rollback = [Step(device, f"tc qdisc replace dev {n} root netem {args}", f"restore setting on {n}")
                for n, args in shaped]
    key = f"iface:{device}"
    return Action("clear_netem", hid, device, f"Remove {len(shaped)} packet-loss/delay setting(s) on {device}",
                  steps, rollback, {key}, set(),
                  {key: [f"{n}|up|" for n, _ in shaped]}, {key: [f"{n}|up|{args}" for n, args in shaped]})


def plan_action(diagnosis: dict) -> Optional[Action]:
    """Map a diagnosis to an action. None means 'nothing to fix' (healthy network or no playbook entry)."""
    if diagnosis.get("cause") == "no_fault":
        return None
    kind = PLAYBOOK.get(diagnosis.get("hypothesis_id"))
    hid, device = diagnosis["hypothesis_id"], diagnosis["device"]
    if kind == "restore_routes":
        return _plan_routes(hid, device)
    if kind == "remove_blocking_rules":
        return _plan_firewall(hid, device)
    if kind == "start_service":
        return _plan_service(hid, device)
    if kind == "restore_config":
        return _plan_config(hid, device)
    if kind == "bring_interface_up":
        return _plan_iface_up(hid, device)
    if kind == "clear_netem":
        return _plan_netem(hid, device)
    return None


def _run_steps(steps: list) -> dict:
    log, ok = [], True
    for st in steps:
        if st.host_path:
            src, tmp = st.host_path, None
            ip_map = current_ip_map()
            if ip_map:  # shadow stack: render the golden config with the shadow IP plan
                with tempfile.NamedTemporaryFile("w", delete=False, suffix=".conf") as f:
                    f.write(Path(st.host_path).read_text().replace(ip_map[0], ip_map[1]))
                src = tmp = f.name
            rc = subprocess.run(["docker", "cp", src, f"{cname(st.container)}:{st.container_path}"],
                                capture_output=True, text=True).returncode
            if tmp:
                os.unlink(tmp)
        else:
            rc = sh(st.container, st.command, check=False).returncode
        log.append({"step": st.description, "rc": rc})
        if rc != 0:
            ok = False
            break
    return {"ok": ok, "log": log}


def apply_action(action: Action) -> dict:
    return _run_steps(action.steps)


def rollback_action(action: Action) -> dict:
    return _run_steps(list(reversed(action.rollback)))
