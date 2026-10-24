"""Hypothesis + evidence state model for ANTA.

Confidence is computed from evidence (log-odds updates using the likelihood ratios in each hypothesis'
prediction table), never guessed by the LLM. The LLM only chooses tests and writes the explanation;
every claim it makes must cite evidence IDs that exist in the store."""
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


def _h(hid: str, cause: str, device: str, layer: str, desc: str, preds: list) -> Hypothesis:
    return Hypothesis(hid, cause, device, layer, desc, {k: Prediction(k, exp, lr) for k, exp, lr in preds})


def build_hypotheses() -> list:
    T, F = True, False
    hyps = [
        _h("H1", "broken_route", "router", "L3", "Router is missing the route to the server subnet", [
            ("route_complete:router", F, 30),
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
        _h("H3", "firewall_block", "firewall", "L4", "Firewall has a rule dropping HTTP traffic", [
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
            ("dns_resolves", T, 2),
            ("svc_local_ok:web-server", T, 3),
            ("trace_reached:client->web-server", T, 2),
        ]),
        _h("H4", "firewall_block", "router", "L4", "Router has a rule dropping HTTP traffic", [
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
            ("dns_resolves", T, 2),
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
        _h("H6", "service_failure", "web-server", "L7", "Web service on the web server is down", [
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
        _h("H0", "no_fault", "none", "-", "No fault: the network and services are healthy", [
            ("reach:client->router", T, 2),
            ("reach:client->firewall", T, 3),
            ("reach:client->dns-server", T, 4),
            ("reach:client->web-server", T, 6),
            ("dns_resolves", T, 6),
            ("route_complete:router", T, 4),
            ("route_complete:firewall", T, 4),
            ("svc_up:web-server:web", T, 12),
            ("svc_up:dns-server:dns", T, 12),
            ("svc_local_ok:web-server", T, 6),
            ("fw_has_drop:firewall", F, 4),
            ("fw_has_drop:router", F, 4),
            ("cap:web-server:tcp_handshake_seen", T, 8),
            ("cap:firewall:tcp_handshake_seen", T, 4),
            ("trace_reached:client->web-server", T, 3),
        ]),
    ]
    recompute(hyps)
    return hyps


def recompute(hyps: list) -> None:
    m = max(h.log_score for h in hyps)
    weights = [math.exp(h.log_score - m) for h in hyps]
    total = sum(weights)
    for h, w in zip(hyps, weights):
        h.confidence = w / total
        if h.status == "confirmed":
            continue
        h.status = "rejected" if (h.confidence < 0.03 and h.contradicting_evidence) else "active"


def apply_findings(hyps: list, evidence_id: str, findings: dict) -> None:
    for h in hyps:
        for key, observed in findings.items():
            p = h.predictions.get(key)
            if p is None:
                continue
            link = EvidenceLink(evidence_id, key, observed, p.expected, p.lr)
            if observed == p.expected:
                h.supporting_evidence.append(link)
                h.log_score += math.log(p.lr)
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


def ready_to_conclude(hyps: list) -> bool:
    top = leader(hyps)
    return (top.confidence >= CONFIRM_THRESHOLD
            and any(l.lr >= DECISIVE_LR for l in top.supporting_evidence)
            and not any(l.lr >= DECISIVE_LR for l in top.contradicting_evidence))
