"""Hypothesis + evidence state model for ANTA.

Confidence is computed from evidence (log-odds updates using the likelihood ratios in each hypothesis'
prediction table), never guessed by the LLM. The LLM only chooses tests and writes the explanation;
every claim it makes must cite evidence IDs that exist in the store.

Scoring rule (healthy readings are NOT evidence for a hypothesis):
  - anomalous observation that matches a prediction        -> score up by ln(lr)   (supporting evidence)
  - any observation that contradicts a prediction          -> score down by ln(lr) (contradicting evidence)
  - healthy observation matching a 'stays healthy' claim   -> neutral (cited only for no_fault)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

CONFIRM_THRESHOLD = 0.90
DECISIVE_LR = 10.0


@dataclass
class Evidence:
    id: str
    test_id: str
    tool: str
    args: dict
    summary: str
    findings: dict
    raw: dict = field(default_factory=dict)


class EvidenceStore:
    def __init__(self) -> None:
        self._items: dict[str, Evidence] = {}

    def add(self, test_id: str, tool: str, args: dict, summary: str, findings: dict, raw: dict) -> Evidence:
        ev = Evidence(f"E{len(self._items) + 1}", test_id, tool, args, summary, findings, raw)
        self._items[ev.id] = ev
        return ev

    def get(self, eid: str) -> Optional[Evidence]:
        return self._items.get(eid)

    def all(self) -> list:
        return list(self._items.values())


@dataclass
class Prediction:
    key: str
    expected: Any
    lr: float


@dataclass
class EvidenceLink:
    evidence_id: str
    key: str
    observed: Any
    expected: Any
    lr: float


@dataclass
class Hypothesis:
    id: str
    cause: str
    device: str
    layer: str
    description: str
    predictions: dict = field(default_factory=dict)
    supporting_evidence: list = field(default_factory=list)
    contradicting_evidence: list = field(default_factory=list)
    status: str = "active"  # active | confirmed | rejected
    confidence: float = 0.0
    tests_remaining: list = field(default_factory=list)
    log_score: float = 0.0
    observed_keys: set = field(default_factory=set)


def healthy_value(key: str):
    """The value a finding key has on a healthy network. None = no known baseline."""
    head = key.split(":", 1)[0]
    if head in ("reach", "route_complete", "svc_up", "svc_local_ok", "trace_reached", "iface_up", "path_ok"):
        return True
    if key in ("dns_resolves", "dns_ip_correct"):
        return True
    if head in ("fw_has_drop", "fw_drop_hits", "link_degraded"):
        return False
    if key == "dns_error" or head in ("unreach_mode", "unreach_from"):
        return "none"
    if head == "cap":
        return key.rsplit(":", 1)[1] == "tcp_handshake_seen"
    return None


def _h(hid: str, cause: str, device: str, layer: str, desc: str, preds: list) -> Hypothesis:
    return Hypothesis(hid, cause, device, layer, desc, {k: Prediction(k, exp, lr) for k, exp, lr in preds})


def build_hypotheses() -> list:
    T, F = True, False
    hyps = [
        _h("H1", "broken_route", "router", "L3", "Router is missing the route to the server subnet", [
            ("route_complete:router", F, 30),
            ("iface_up:router", T, 30),
            ("reach:client->router", T, 2),
            ("reach:client->firewall", T, 4),
            ("reach:client->dns-server", F, 3),
            ("reach:client->web-server", F, 3),
            ("unreach_from:client->web-server", "router", 8),
            ("dns_resolves", F, 2),
            ("dns_error", "unreachable", 4),
            ("route_complete:firewall", T, 2),
            ("trace_reached:client->web-server", F, 2),
            ("cap:firewall:no_traffic", T, 5),
            ("cap:web-server:no_traffic", T, 3),
        ]),
        _h("H2", "broken_route", "firewall", "L3", "Firewall is missing the return route to the client subnet", [
            ("route_complete:firewall", F, 30),
            ("iface_up:firewall", T, 30),
            ("reach:client->router", T, 2),
            ("reach:client->firewall", F, 4),
            ("reach:client->dns-server", F, 3),
            ("reach:client->web-server", F, 3),
            ("unreach_mode:client->web-server", "timeout", 3),
            ("dns_resolves", F, 2),
            ("dns_error", "timeout", 3),
            ("route_complete:router", T, 2),
            ("trace_reached:client->web-server", F, 2),
        ]),
        _h("H3", "firewall_block", "firewall", "L4", "Firewall has a rule blocking http, dns or ping traffic", [
            ("fw_has_drop:firewall", T, 30),
            ("fw_has_drop:router", F, 8),
            ("fw_drop_hits:firewall", T, 4),
            ("cap:firewall:tcp_syn_unanswered", T, 8),
            ("cap:firewall:no_traffic", F, 3),
            ("cap:web-server:no_traffic", T, 6),
            ("reach:client->web-server", T, 4),
            ("reach:client->dns-server", T, 3),
            ("reach:client->firewall", T, 2),
            ("route_complete:router", T, 3),
            ("route_complete:firewall", T, 3),
            ("svc_local_ok:web-server", T, 3),
            ("trace_reached:client->web-server", T, 2),
        ]),
        _h("H4", "firewall_block", "router", "L4", "Router has a rule blocking http, dns or ping traffic", [
            ("fw_has_drop:router", T, 30),
            ("fw_has_drop:firewall", F, 8),
            ("fw_drop_hits:router", T, 4),
            ("cap:firewall:no_traffic", T, 5),
            ("cap:web-server:no_traffic", T, 4),
            ("reach:client->web-server", T, 4),
            ("reach:client->dns-server", T, 3),
            ("reach:client->firewall", T, 2),
            ("route_complete:router", T, 3),
            ("route_complete:firewall", T, 3),
            ("svc_local_ok:web-server", T, 3),
            ("trace_reached:client->web-server", T, 2),
        ]),
        _h("H5", "dns_failure", "dns-server", "APP", "DNS service on the DNS server is down", [
            ("svc_up:dns-server:dns", F, 30),
            ("dns_resolves", F, 5),
            ("dns_error", "refused", 8),
            ("reach:client->dns-server", T, 3),
            ("reach:client->web-server", T, 3),
            ("svc_local_ok:web-server", T, 2),
            ("route_complete:router", T, 3),
            ("route_complete:firewall", T, 3),
            ("cap:web-server:tcp_handshake_seen", T, 4),
            ("trace_reached:client->web-server", T, 2),
        ]),
        _h("H6", "service_failure", "web-server", "L7", "Web service on the web server is stopped", [
            ("svc_up:web-server:web", F, 30),
            ("cap:web-server:tcp_rst_seen", T, 8),
            ("cap:web-server:tcp_handshake_seen", F, 4),
            ("cap:web-server:no_traffic", F, 4),
            ("cap:firewall:tcp_rst_seen", T, 4),
            ("reach:client->web-server", T, 4),
            ("reach:client->dns-server", T, 2),
            ("dns_resolves", T, 3),
            ("route_complete:router", T, 3),
            ("route_complete:firewall", T, 3),
            ("trace_reached:client->web-server", T, 2),
            ("fw_has_drop:firewall", F, 3),
        ]),
        _h("H7", "broken_route", "client", "L3", "Client has lost its default route", [
            ("route_complete:client", F, 30),
            ("iface_up:client", T, 30),
            ("reach:client->router", T, 2),
            ("reach:client->firewall", F, 4),
            ("reach:client->dns-server", F, 3),
            ("reach:client->web-server", F, 3),
            ("unreach_mode:client->web-server", "local_no_route", 8),
            ("dns_resolves", F, 2),
            ("dns_error", "unreachable", 3),
            ("route_complete:router", T, 2),
            ("route_complete:firewall", T, 2),
        ]),
        _h("H8", "broken_route", "web-server", "L3", "Web server has lost its default route (replies cannot return)", [
            ("route_complete:web-server", F, 30),
            ("iface_up:web-server", T, 30),
            ("reach:client->web-server", F, 3),
            ("unreach_mode:client->web-server", "timeout", 3),
            ("reach:client->firewall", T, 3),
            ("reach:client->dns-server", T, 3),
            ("dns_resolves", T, 3),
            ("svc_up:web-server:web", T, 3),
            ("svc_local_ok:web-server", T, 3),
            ("route_complete:router", T, 2),
            ("route_complete:firewall", T, 2),
        ]),
        _h("H9", "broken_route", "dns-server", "L3", "DNS server has lost its default route (replies cannot return)", [
            ("route_complete:dns-server", F, 30),
            ("iface_up:dns-server", T, 30),
            ("reach:client->dns-server", F, 4),
            ("dns_resolves", F, 3),
            ("dns_error", "timeout", 3),
            ("reach:client->web-server", T, 3),
            ("reach:client->firewall", T, 3),
            ("svc_up:dns-server:dns", T, 4),
            ("route_complete:router", T, 2),
            ("route_complete:firewall", T, 2),
        ]),
        _h("H10", "service_failure", "web-server", "L7", "Web service is running but returns HTTP errors", [
            ("svc_local_ok:web-server", F, 30),
            ("svc_up:web-server:web", T, 4),
            ("reach:client->web-server", T, 3),
            ("dns_resolves", T, 3),
            ("cap:web-server:tcp_handshake_seen", T, 3),
            ("route_complete:router", T, 2),
            ("route_complete:firewall", T, 2),
            ("fw_has_drop:firewall", F, 3),
        ]),
        _h("H11", "dns_failure", "dns-server", "APP", "DNS server answers with the wrong address", [
            ("dns_ip_correct", F, 30),
            ("dns_resolves", T, 3),
            ("svc_up:dns-server:dns", T, 4),
            ("reach:client->dns-server", T, 3),
            ("reach:client->web-server", T, 3),
        ]),
        _h("H12", "interface_down", "router", "L2", "A network interface on the router is down", [
            ("iface_up:router", F, 30),
            ("reach:client->web-server", F, 3),
            ("reach:client->dns-server", F, 3),
            ("dns_resolves", F, 2),
            ("route_complete:client", T, 2),
            ("route_complete:firewall", T, 2),
            ("link_degraded:router", F, 3),
        ]),
        _h("H13", "interface_down", "firewall", "L2", "A network interface on the firewall is down", [
            ("iface_up:firewall", F, 30),
            ("reach:client->web-server", F, 3),
            ("reach:client->dns-server", F, 3),
            ("reach:client->router", T, 2),
            ("dns_resolves", F, 2),
            ("link_degraded:firewall", F, 3),
        ]),
        _h("H14", "interface_down", "web-server", "L2", "The web server's network interface is down", [
            ("iface_up:web-server", F, 30),
            ("reach:client->web-server", F, 4),
            ("reach:client->dns-server", T, 3),
            ("reach:client->firewall", T, 3),
            ("dns_resolves", T, 3),
            ("svc_local_ok:web-server", T, 3),
        ]),
        _h("H15", "interface_down", "dns-server", "L2", "The DNS server's network interface is down", [
            ("iface_up:dns-server", F, 30),
            ("reach:client->dns-server", F, 4),
            ("dns_resolves", F, 4),
            ("reach:client->web-server", T, 3),
            ("reach:client->firewall", T, 3),
        ]),
        _h("H16", "interface_down", "client", "L2", "The client's network interface is down", [
            ("iface_up:client", F, 30),
            ("reach:client->router", F, 4),
            ("reach:client->firewall", F, 3),
            ("reach:client->dns-server", F, 3),
            ("reach:client->web-server", F, 3),
        ]),
        _h("H17", "link_degradation", "router", "L3", "A router link drops or delays packets", [
            ("link_degraded:router", T, 30),
            ("iface_up:router", T, 8),
            ("route_complete:router", T, 3),
        ]),
        _h("H18", "link_degradation", "firewall", "L3", "A firewall link drops or delays packets", [
            ("link_degraded:firewall", T, 30),
            ("iface_up:firewall", T, 8),
            ("route_complete:firewall", T, 3),
        ]),
        _h("H19", "link_degradation", "web-server", "L3", "The web server's link drops or delays packets", [
            ("link_degraded:web-server", T, 30),
            ("iface_up:web-server", T, 8),
            ("route_complete:web-server", T, 3),
            ("svc_up:web-server:web", T, 3),
        ]),
        _h("H20", "link_degradation", "dns-server", "L3", "The DNS server's link drops or delays packets", [
            ("link_degraded:dns-server", T, 30),
            ("iface_up:dns-server", T, 8),
            ("route_complete:dns-server", T, 3),
            ("svc_up:dns-server:dns", T, 3),
        ]),
        _h("H21", "link_degradation", "client", "L3", "The client's link drops or delays packets", [
            ("link_degraded:client", T, 30),
            ("iface_up:client", T, 8),
            ("route_complete:client", T, 3),
        ]),
        _h("H0", "no_fault", "none", "-", "No fault: the network and services are healthy", [
            ("reach:client->router", T, 6),
            ("reach:client->firewall", T, 6),
            ("reach:client->dns-server", T, 6),
            ("reach:client->web-server", T, 6),
            ("dns_resolves", T, 6),
            ("dns_ip_correct", T, 10),
            ("route_complete:client", T, 10),
            ("route_complete:router", T, 10),
            ("route_complete:firewall", T, 10),
            ("route_complete:dns-server", T, 10),
            ("route_complete:web-server", T, 10),
            ("svc_up:web-server:web", T, 10),
            ("svc_up:dns-server:dns", T, 10),
            ("svc_local_ok:web-server", T, 10),
            ("fw_has_drop:router", F, 10),
            ("fw_has_drop:firewall", F, 10),
            ("cap:web-server:tcp_handshake_seen", T, 6),
            ("cap:firewall:tcp_handshake_seen", T, 6),
            ("cap:web-server:no_traffic", F, 6),
            ("cap:firewall:no_traffic", F, 6),
            ("cap:firewall:tcp_syn_unanswered", F, 6),
            ("cap:web-server:tcp_rst_seen", F, 6),
            ("trace_reached:client->web-server", T, 4),
            ("iface_up:client", T, 10), ("iface_up:router", T, 10), ("iface_up:firewall", T, 10),
            ("iface_up:dns-server", T, 10), ("iface_up:web-server", T, 10),
            ("link_degraded:client", F, 10), ("link_degraded:router", F, 10), ("link_degraded:firewall", F, 10),
            ("link_degraded:dns-server", F, 10), ("link_degraded:web-server", F, 10),
            ("path_ok:client->router", T, 6), ("path_ok:client->firewall", T, 6),
            ("path_ok:client->dns-server", T, 6), ("path_ok:client->web-server", T, 6),
        ]),
    ]
    recompute(hyps)
    return hyps


def recompute(hyps: list) -> None:
    """Confidence = normalized evidence score over the hypotheses that are still alive. A hypothesis whose own
    decisive prediction (likelihood ratio >= 10) was observed to be false is eliminated, not just down-weighted."""
    alive = [h for h in hyps if not _decisively_contradicted(h)] or list(hyps)
    alive_ids = {id(h) for h in alive}
    m = max(h.log_score for h in alive)
    weights = [math.exp(h.log_score - m) if id(h) in alive_ids else 0.0 for h in hyps]
    total = sum(weights)
    for h, w in zip(hyps, weights):
        h.confidence = w / total
        if h.status == "confirmed":
            continue
        h.status = ("rejected" if (id(h) not in alive_ids or (h.confidence < 0.03 and h.contradicting_evidence))
                    else "active")


def apply_findings(hyps: list, evidence_id: str, findings: dict) -> None:
    for h in hyps:
        for key, observed in findings.items():
            p = h.predictions.get(key)
            if p is None:
                continue
            h.observed_keys.add(key)
            link = EvidenceLink(evidence_id, key, observed, p.expected, p.lr)
            healthy = healthy_value(key)
            anomalous = healthy is None or observed != healthy
            if observed == p.expected:
                if anomalous:
                    h.supporting_evidence.append(link)
                    h.log_score += math.log(p.lr)
                elif h.cause == "no_fault":
                    h.supporting_evidence.append(link)  # cited as proof of health, but no score bonus
                # a healthy reading matching a 'stays healthy' prediction is neutral
            else:
                h.contradicting_evidence.append(link)
                h.log_score -= math.log(p.lr)
    recompute(hyps)


def refresh_tests_remaining(hyps: list, catalog: dict, executed: set) -> None:
    for h in hyps:
        h.tests_remaining = [t.id for t in catalog.values()
                             if t.id not in executed and any(k in h.predictions for k in t.keys)]


def leader(hyps: list) -> Hypothesis:
    pool = [h for h in hyps if h.status != "rejected"] or hyps
    return max(pool, key=lambda h: h.confidence)


def unverified_preconditions(h: Hypothesis) -> list:
    """Strong 'this part stays healthy' claims that were never checked, e.g. a missing route is only the
    root cause if the interface under it is up."""
    return [p.key for p in h.predictions.values()
            if p.lr >= DECISIVE_LR and healthy_value(p.key) is not None
            and p.expected == healthy_value(p.key) and p.key not in h.observed_keys]


def _decisively_contradicted(h: Hypothesis) -> bool:
    return any(l.lr >= DECISIVE_LR for l in h.contradicting_evidence)


def ready_to_conclude(hyps: list) -> bool:
    top = leader(hyps)
    if top.cause == "no_fault":
        # 'healthy' is proven by elimination: nothing anomalous was seen and every fault hypothesis
        # has been decisively ruled out
        return (top.confidence >= 0.5 and not top.contradicting_evidence
                and all(_decisively_contradicted(h) for h in hyps if h is not top))
    if top.confidence < CONFIRM_THRESHOLD:
        return False
    return (any(l.lr >= DECISIVE_LR for l in top.supporting_evidence) and not _decisively_contradicted(top)
            and not unverified_preconditions(top))
