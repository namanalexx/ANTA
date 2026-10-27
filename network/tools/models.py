"""Result dataclasses for every ANTA tool.
All fields have defaults so a failed tool can still return a valid object with tool_error set."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Link:
    network: str = ""
    subnet: str = ""
    members: list[str] = field(default_factory=list)


@dataclass
class Topology:
    nodes: list[str] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    ip_assignments: dict[str, dict[str, str]] = field(default_factory=dict)
    tool_error: Optional[str] = None


@dataclass
class Interface:
    name: str = ""
    status: str = "down"
    ip: Optional[str] = None
    mac: Optional[str] = None
    netem: Optional[str] = None  # packet-loss / delay emulation configured on the interface


@dataclass
class InterfaceStatus:
    node: str = ""
    interfaces: list[Interface] = field(default_factory=list)
    tool_error: Optional[str] = None


@dataclass
class Route:
    dest: str = ""
    gateway: Optional[str] = None
    iface: Optional[str] = None
    metric: Optional[int] = None


@dataclass
class RouteTable:
    node: str = ""
    routes: list[Route] = field(default_factory=list)
    tool_error: Optional[str] = None


@dataclass
class ArpEntry:
    ip: str = ""
    mac: Optional[str] = None
    iface: Optional[str] = None
    state: str = ""


@dataclass
class ArpTable:
    node: str = ""
    entries: list[ArpEntry] = field(default_factory=list)
    tool_error: Optional[str] = None


@dataclass
class PingResult:
    src: str = ""
    dst: str = ""
    reachable: bool = False
    packets_sent: int = 0
    packets_received: int = 0
    packet_loss_pct: float = 100.0
    avg_rtt_ms: Optional[float] = None
    failure_mode: str = "none"  # none | timeout | net_unreachable | host_unreachable | local_no_route
    error_from: Optional[str] = None  # IP of the device that sent an ICMP unreachable
    tool_error: Optional[str] = None


@dataclass
class Hop:
    hop: int = 0
    ip: Optional[str] = None
    rtt_ms: Optional[float] = None
    timeout: bool = False
    flag: Optional[str] = None  # e.g. !N (net unreachable), !H (host unreachable)


@dataclass
class TracerouteResult:
    src: str = ""
    dst: str = ""
    reached: bool = False
    hops: list[Hop] = field(default_factory=list)
    tool_error: Optional[str] = None


@dataclass
class DnsResult:
    server: str = ""
    host: str = ""
    queried_from: str = ""
    resolved: bool = False
    ip: Optional[str] = None
    response_time_ms: Optional[int] = None
    rcode: Optional[str] = None
    error: Optional[str] = None  # timeout | refused | unreachable | nxdomain | no_answer | ...
    tool_error: Optional[str] = None


@dataclass
class FirewallRule:
    number: int = 0
    target: Optional[str] = None
    protocol: str = "all"
    source: str = "any"
    destination: str = "any"
    in_iface: Optional[str] = None
    out_iface: Optional[str] = None
    sport: Optional[str] = None
    dport: Optional[str] = None
    packets: int = 0
    bytes: int = 0
    spec: str = ""


@dataclass
class FirewallChain:
    name: str = ""
    policy: str = "ACCEPT"
    packets: int = 0
    bytes: int = 0
    rules: list[FirewallRule] = field(default_factory=list)


@dataclass
class FirewallState:
    node: str = ""
    chains: list[FirewallChain] = field(default_factory=list)
    tool_error: Optional[str] = None


@dataclass
class CaptureResult:
    node: str = ""
    interface: str = ""
    packet_count: int = 0
    summary: dict[str, int] = field(default_factory=dict)
    patterns: list[str] = field(default_factory=list)
    tool_error: Optional[str] = None


@dataclass
class ServiceStatus:
    node: str = ""
    service: str = ""
    running: bool = False
    port_open: bool = False
    response_code: Optional[str] = None  # "200" for web, DNS rcode like "NOERROR" for dns
    tool_error: Optional[str] = None


@dataclass
class LogEntry:
    timestamp: str = ""
    level: str = "info"
    message: str = ""
    source: str = ""


@dataclass
class LogResult:
    node: str = ""
    entries: list[LogEntry] = field(default_factory=list)
    tool_error: Optional[str] = None
