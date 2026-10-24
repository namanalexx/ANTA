"""Shared helpers for the baselines: Ollama chat with message history, answer normalization, output shaping."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from agent import llm

CAUSES = ["broken_route", "firewall_block", "dns_failure", "service_failure", "no_fault"]
NODES = ["client", "router", "firewall", "dns-server", "web-server"]
LAYER = {"broken_route": "L3", "firewall_block": "L4", "dns_failure": "APP", "service_failure": "L7", "no_fault": "-"}

NETWORK_DESCRIPTION = """NETWORK (5 Linux containers, IPv4):
- client 10.10.1.10: default route via the router (10.10.1.2).
- router: 10.10.1.2 (client side) and 10.10.2.2 (core side). Forwards traffic; static route to the server subnet 10.10.3.0/24 via the firewall (10.10.2.3). Has iptables, FORWARD policy ACCEPT.
- firewall: 10.10.2.3 (core side) and 10.10.3.2 (server side). Forwards traffic; static route to the client subnet 10.10.1.0/24 via the router (10.10.2.2). Has iptables, FORWARD policy ACCEPT.
- dns-server 10.10.3.10: dnsmasq answers web.anta.local = 10.10.3.20. Default route via the firewall (10.10.3.2).
- web-server 10.10.3.20: nginx on tcp/80 returns HTTP 200. Default route via the firewall (10.10.3.2).
Normal behaviour: the client resolves web.anta.local through dns-server and loads http://web.anta.local from web-server."""

ANSWER_HELP = """POSSIBLE CAUSES (pick exactly one):
- broken_route: a routing-table entry is missing on some device (device = the device missing the route)
- firewall_block: an iptables rule or policy on the router or firewall drops or rejects traffic (device = router or firewall)
- dns_failure: the DNS service is down or gives wrong answers (device = dns-server)
- service_failure: the web service is stopped or returns errors (device = web-server)
- no_fault: nothing is broken (device = none)
DEVICES: client, router, firewall, dns-server, web-server, none"""


def chat(messages: list, max_tokens: int = 400, num_ctx: int = 8192, retries: int = 1) -> dict:
    payload = {
        "model": llm.MODEL, "messages": messages, "stream": False, "format": "json", "keep_alive": "10m",
        "options": {"temperature": 0, "num_ctx": num_ctx, "num_predict": max_tokens},
    }
    last = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(f"{llm.OLLAMA_URL}/api/chat", data=json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=240) as resp:
                body = json.loads(resp.read())
            data = json.loads(body["message"]["content"])
            if isinstance(data, dict):
                return data
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as e:
            last = e
    raise llm.LLMError(f"chat failed: {last}")


def norm_cause(c) -> str:
    v = str(c or "").strip().lower().replace("-", "_").replace(" ", "_")
    if v in CAUSES:
        return v
    if "no" in v and "fault" in v:
        return "no_fault"
    for needle, cause in (("route", "broken_route"), ("rout", "broken_route"), ("firewall", "firewall_block"),
                          ("acl", "firewall_block"), ("dns", "dns_failure"), ("service", "service_failure"),
                          ("web", "service_failure")):
        if needle in v:
            return cause
    return v or "unknown"


def norm_device(d) -> str:
    v = str(d or "").strip().lower().replace("_", "-").replace(" ", "-")
    if v in NODES or v == "none":
        return v
    for needle, dev in (("dns", "dns-server"), ("web", "web-server"), ("fire", "firewall"),
                        ("rout", "router"), ("client", "client")):
        if needle in v:
            return dev
    return v or "none"


def shape(symptom: str, cause: str, device: str, cited: list, evidence: list, explanation: str, stats: dict) -> dict:
    """Build the same result structure ANTA returns, so the benchmark evaluator can score any system."""
    stats = {"tool_calls": 0, "llm_calls": 0, "llm_fallbacks": 0, "citations_repaired": False, "steps": 0,
             "seconds": 0.0, "model": llm.MODEL, "concluded_by": "answered", **stats}
    return {
        "symptom": symptom,
        "diagnosis": {"hypothesis_id": "-", "cause": cause, "device": device, "layer": LAYER.get(cause, "-"),
                      "confidence": None, "status": "answered"},
        "evidence_ids": cited, "evidence": evidence, "llm_explanation": explanation, "stats": stats,
    }
