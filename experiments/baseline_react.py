"""Baseline 2: ReAct. Same 11 tools (JSON outputs) and network description as ANTA's setting, but no hypothesis
tracking or evidence scoring: the model thinks, picks a tool, reads the observation, repeats, then answers."""
from __future__ import annotations

import json
import time

from agent import llm
from agent.planner import _EXTRACTORS, build_catalog, build_context
from tools import TOOLS, to_dict

from .common import ANSWER_HELP, NETWORK_DESCRIPTION, chat, norm_cause, norm_device, shape

MAX_STEPS = 15
OBS_CHARS = 700

TOOL_HELP = """TOOLS (all return JSON):
- get_topology()
- get_interface_status(node)
- get_route_table(node)
- get_arp_table(node)
- ping(src, dst)                                    # dst is an IP address
- traceroute(src, dst)
- inspect_dns(server, host, src)                    # src defaults to "client"
- inspect_firewall(node)                            # iptables rules and hit counters
- capture_packets(node, iface, duration_s, probe)   # probe = {"kind": "ping|http|dns", "src": node, "dst": ip}
- check_service(node, svc)                          # svc is "web" or "dns"
- get_logs(node)
Node names: client, router, firewall, dns-server, web-server."""

SYSTEM = (
    "You are a network engineer diagnosing a problem in a small lab network using diagnostic tools. "
    "Each turn reply with ONE JSON object, either\n"
    '  {"thought": "<reasoning>", "action": "<tool name>", "args": {<tool arguments>}}\n'
    "to run a tool (you will receive an Observation), or, when you are confident,\n"
    '  {"final": {"cause": "<cause>", "device": "<device>", "evidence": [<observation numbers>], '
    '"explanation": "<2 sentences>"}}.\n\n'
    f"{NETWORK_DESCRIPTION}\n\n{TOOL_HELP}\n\n{ANSWER_HELP}"
)


def _compact(result: dict) -> str:
    s = json.dumps(result, separators=(",", ":"))
    return s if len(s) <= OBS_CHARS else s[:OBS_CHARS] + "...(truncated)"


def _call(action: str, args: dict):
    try:
        return to_dict(TOOLS[action]["fn"](**args))
    except Exception as e:  # bad arguments from the model are an observation, not a crash
        return {"tool_error": f"bad arguments for {action}: {type(e).__name__}"}


def _match(catalog: dict, tool: str, args: dict):
    """Map a free-form tool call onto one of ANTA's standard checks (used only to score evidence quality)."""
    a = dict(args)
    if tool == "inspect_dns":
        a.setdefault("src", "client")
    for t in catalog.values():
        if t.tool != tool:
            continue
        if tool == "capture_packets":
            probe = a.get("probe") or {}
            if (a.get("node") == t.meta["node"] and isinstance(probe, dict)
                    and probe.get("kind") == "http" and probe.get("dst") == t.args["probe"]["dst"]):
                return t
        elif t.args == a:
            return t
    return None


def run_react(symptom: str) -> dict:
    t0 = time.time()
    # Used ONLY to map tool calls onto findings for evidence-quality scoring. Never shown to the model.
    ctx = build_context(to_dict(TOOLS["get_topology"]["fn"]()))
    catalog = build_catalog(ctx)

    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"Symptom: {symptom}\nBegin."}]
    evidence: list = []
    llm_calls = 0
    final = None
    for _ in range(MAX_STEPS * 2):  # extra turns tolerate malformed replies
        if len(evidence) >= MAX_STEPS:
            break
        try:
            step = chat(messages)
            llm_calls += 1
        except llm.LLMError:
            break
        messages.append({"role": "assistant", "content": json.dumps(step)})
        if isinstance(step.get("final"), dict):
            final = step["final"]
            break
        action = step.get("action")
        if action not in TOOLS:
            messages.append({"role": "user", "content": f"Invalid action. Use one of: {', '.join(TOOLS)}."})
            continue
        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        result = _call(action, args)
        findings = {}
        test = _match(catalog, action, args)
        if test and not result.get("tool_error"):
            try:
                _, findings = _EXTRACTORS[action](test, result, ctx)
            except Exception:
                findings = {}
        n = len(evidence) + 1
        evidence.append({"id": f"E{n}", "test": action, "summary": f"{action}({json.dumps(args)})",
                         "findings": findings})
        messages.append({"role": "user", "content": f"Observation E{n}: {_compact(result)}"})

    if final is None:  # out of budget: force an answer
        messages.append({"role": "user", "content":
                         'Stop investigating. Give your final answer now as {"final": {"cause": ..., "device": ..., '
                         '"evidence": [...], "explanation": ...}}.'})
        try:
            step = chat(messages)
            llm_calls += 1
            final = step["final"] if isinstance(step.get("final"), dict) else step
        except llm.LLMError:
            final = {}

    cited = []
    for ref in final.get("evidence", []) if isinstance(final.get("evidence"), list) else []:
        digits = "".join(ch for ch in str(ref) if ch.isdigit())
        if digits and 1 <= int(digits) <= len(evidence) and f"E{int(digits)}" not in cited:
            cited.append(f"E{int(digits)}")
    return shape(symptom, norm_cause(final.get("cause")), norm_device(final.get("device")), cited, evidence,
                 str(final.get("explanation", ""))[:400],
                 {"tool_calls": len(evidence), "llm_calls": llm_calls, "steps": len(evidence),
                  "seconds": round(time.time() - t0, 1)})
