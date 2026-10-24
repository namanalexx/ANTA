"""ANTA main LangGraph agent.
Usage (from ~/ANTA, venv active):  python3 -m agent.anta "symptom" [--max-steps N] [--quiet] [--json]"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Optional, TypedDict

from langgraph.graph import END, StateGraph
from tools import TOOLS, to_dict

from . import llm
from .hypotheses import (
    CONFIRM_THRESHOLD, DECISIVE_LR, EvidenceStore, apply_findings, build_hypotheses, leader,
    ready_to_conclude, refresh_tests_remaining,
)
from .planner import build_catalog, build_context, choose_test, rank_tests, run_test

DEFAULT_SYMPTOM = "Users on the client cannot load the web server at web.anta.local."


@dataclass
class Case:
    symptom: str
    max_steps: int = 20
    verbose: bool = True
    store: EvidenceStore = field(default_factory=EvidenceStore)
    hyps: list = field(default_factory=list)
    ctx: Any = None
    catalog: dict = field(default_factory=dict)
    executed: set = field(default_factory=set)
    pending: Any = None
    pending_reason: str = ""
    pending_llm: bool = False
    last_ev: Any = None
    trace: list = field(default_factory=list)
    tool_calls: int = 0
    llm_calls: int = 0
    llm_fallbacks: int = 0
    citations_repaired: bool = False
    result: Optional[dict] = None
    started: float = field(default_factory=time.time)


class State(TypedDict, total=False):
    case: Any
    decision: str


def _say(case: Case, text: str) -> None:
    if case.verbose:
        print(text, flush=True)


def _top_line(case: Case, n: int = 3) -> str:
    hs = sorted(case.hyps, key=lambda h: -h.confidence)[:n]
    return " | ".join(f"{h.id} {h.cause}@{h.device} {h.confidence:.0%}" for h in hs)


# ------------------------------------------------------------------ graph nodes
def node_init(state: State) -> dict:
    case = state["case"]
    topo = to_dict(TOOLS["get_topology"]["fn"]())
    case.tool_calls += 1
    if topo.get("tool_error"):
        raise RuntimeError(f"cannot read topology: {topo['tool_error']}")
    case.ctx = build_context(topo)
    case.catalog = build_catalog(case.ctx)
    case.hyps = build_hypotheses()
    refresh_tests_remaining(case.hyps, case.catalog, case.executed)
    ev = case.store.add("topology", "get_topology", {},
                        f"topology: {len(topo['nodes'])} nodes, {len(topo['links'])} segments", {}, topo)
    _say(case, f"symptom: {case.symptom}")
    _say(case, f"{ev.id} {ev.summary}; {len(case.hyps)} hypotheses, {len(case.catalog)} available tests")
    return {"case": case}


def node_decide(state: State) -> dict:
    case = state["case"]
    remaining = any(t.id not in case.executed for t in case.catalog.values())
    if ready_to_conclude(case.hyps) or len(case.executed) >= case.max_steps or not remaining:
        decision = "conclude"
    else:
        decision = "plan"
    return {"case": case, "decision": decision}


def _confirmation_test(case):
    """Leader >= threshold but not yet provable: return the unrun test that settles it fastest."""
    top = leader(case.hyps)
    if top.confidence < CONFIRM_THRESHOLD:
        return None
    unrun = [t for t in case.catalog.values() if t.id not in case.executed]
    best = None
    if top.cause == "no_fault":
        # prove 'healthy' by decisively ruling out every remaining fault hypothesis
        open_h = [h for h in case.hyps if h is not top
                  and not any(l.lr >= DECISIVE_LR for l in h.contradicting_evidence)]
        for t in unrun:
            n = sum(1 for h in open_h
                    if any(k in h.predictions and h.predictions[k].lr >= DECISIVE_LR for k in t.keys))
            if n and (best is None or n > best[0]):
                best = (n, t)
    else:
        if any(l.lr >= DECISIVE_LR for l in top.supporting_evidence):
            return None
        for t in unrun:
            lr = max((top.predictions[k].lr for k in t.keys if k in top.predictions), default=0)
            if lr >= DECISIVE_LR and (best is None or lr > best[0]):
                best = (lr, t)
    return best[1] if best else None


def node_plan(state: State) -> dict:
    case = state["case"]
    confirm = _confirmation_test(case)
    if confirm:
        case.pending, case.pending_llm = confirm, False
        case.pending_reason = "confirm leading hypothesis with its most decisive test (rule-based)"
        return {"case": case}
    ranked = rank_tests(case.catalog, case.executed, case.hyps)
    lines = [f"{e.id}: {e.summary}" for e in case.store.all()]
    test, reason, used = choose_test(case.symptom, case.hyps, lines, ranked)
    case.llm_calls += 1
    if not used:
        case.llm_fallbacks += 1
    case.pending, case.pending_reason, case.pending_llm = test, reason, used
    return {"case": case}


def node_act(state: State) -> dict:
    case = state["case"]
    t = case.pending
    summary, findings, raw = run_test(t, case.ctx)
    case.last_ev = case.store.add(t.id, t.tool, t.args, summary, findings, raw)
    case.executed.add(t.id)
    case.tool_calls += 1
    return {"case": case}


def node_update(state: State) -> dict:
    case = state["case"]
    ev = case.last_ev
    apply_findings(case.hyps, ev.id, ev.findings)
    refresh_tests_remaining(case.hyps, case.catalog, case.executed)
    step = len(case.executed)
    case.trace.append({
        "step": step, "test": ev.test_id, "reason": case.pending_reason, "llm_choice": case.pending_llm,
        "evidence_id": ev.id, "confidences": {h.id: round(h.confidence, 4) for h in case.hyps},
    })
    who = "confirm" if case.pending_reason.startswith("confirm") else ("LLM" if case.pending_llm else "fallback")
    _say(case, f"\n[{step}] plan ({who}): {ev.test_id}" + (f"  - {case.pending_reason}" if case.pending_reason else ""))
    _say(case, f"    {ev.id} {ev.summary}")
    _say(case, f"    top: {_top_line(case)}")
    return {"case": case}


CONCLUDE_SYSTEM = (
    "You are a senior network engineer writing a short diagnosis report. Use ONLY the evidence provided; "
    "do not invent facts. "
    'Reply with JSON only: {"explanation": "<2-3 sentences>", "evidence_ids": ["E#", ...], '
    '"suggested_fix": "<one sentence>"}. evidence_ids must come from the supporting evidence list.'
)


def _conclude_prompt(case: Case, top, allowed: list) -> str:
    lines = [
        f"Symptom: {case.symptom}",
        f"System conclusion: {top.cause} on {top.device} ({top.layer}), confidence {top.confidence:.0%}.",
        "Supporting evidence:",
    ]
    for eid in allowed[:6]:
        lines.append(f"  {eid}: {case.store.get(eid).summary}")
    rejected = [h for h in case.hyps if h.status == "rejected"]
    if rejected:
        lines.append("Ruled out:")
        for h in rejected:
            ids = ", ".join(dict.fromkeys(l.evidence_id for l in h.contradicting_evidence))
            lines.append(f"  {h.id} {h.cause} on {h.device} (contradicted by {ids})")
    return "\n".join(lines)


def node_conclude(state: State) -> dict:
    case = state["case"]
    top = leader(case.hyps)
    ready = ready_to_conclude(case.hyps)
    if ready:
        top.status = "confirmed"
    allowed = list(dict.fromkeys(l.evidence_id for l in sorted(top.supporting_evidence, key=lambda l: -l.lr)))
    explanation, fix, cited = "", "", []
    case.llm_calls += 1
    try:
        out = llm.chat_json(CONCLUDE_SYSTEM, _conclude_prompt(case, top, allowed))
        explanation = str(out.get("explanation", ""))[:600]
        fix = str(out.get("suggested_fix", ""))[:300]
        raw_ids = out.get("evidence_ids", [])
        raw_ids = raw_ids if isinstance(raw_ids, list) else []
        cited = [str(i) for i in raw_ids if str(i) in allowed]
        if len(cited) != len(raw_ids) or not cited:
            case.citations_repaired = True
    except llm.LLMError as e:
        case.llm_fallbacks += 1
        case.citations_repaired = True
        explanation = f"(LLM unavailable: {e}) Conclusion derived from evidence only."
    cited = list(dict.fromkeys(cited)) or allowed[:3]

    case.result = {
        "symptom": case.symptom,
        "diagnosis": {
            "hypothesis_id": top.id, "cause": top.cause, "device": top.device, "layer": top.layer,
            "confidence": round(top.confidence, 4), "status": "confirmed" if ready else "best_guess",
        },
        "evidence_ids": cited,
        "evidence_shows": [f"{i}: {case.store.get(i).summary}" for i in cited],
        "llm_explanation": explanation,
        "suggested_fix": fix,
        "hypotheses": [{
            "id": h.id, "cause": h.cause, "device": h.device, "layer": h.layer, "status": h.status,
            "confidence": round(h.confidence, 4),
            "supporting": list(dict.fromkeys(l.evidence_id for l in h.supporting_evidence)),
            "contradicting": list(dict.fromkeys(l.evidence_id for l in h.contradicting_evidence)),
        } for h in case.hyps],
        "evidence": [{"id": e.id, "test": e.test_id, "summary": e.summary, "findings": e.findings}
                     for e in case.store.all()],
        "trace": case.trace,
        "stats": {
            "tool_calls": case.tool_calls, "llm_calls": case.llm_calls, "llm_fallbacks": case.llm_fallbacks,
            "citations_repaired": case.citations_repaired, "steps": len(case.executed),
            "seconds": round(time.time() - case.started, 1), "model": llm.MODEL,
            "concluded_by": "evidence_threshold" if ready else "budget_or_tests_exhausted",
        },
    }
    return {"case": case}


# ------------------------------------------------------------------ graph assembly
def build_graph():
    g = StateGraph(State)
    g.add_node("init", node_init)
    g.add_node("decide", node_decide)
    g.add_node("plan", node_plan)
    g.add_node("act", node_act)
    g.add_node("update", node_update)
    g.add_node("conclude", node_conclude)
    g.set_entry_point("init")
    g.add_edge("init", "decide")
    g.add_conditional_edges("decide", lambda s: s["decision"], {"plan": "plan", "conclude": "conclude"})
    g.add_edge("plan", "act")
    g.add_edge("act", "update")
    g.add_edge("update", "decide")
    g.add_edge("conclude", END)
    return g.compile()


_APP = None


def run_agent(symptom: str = DEFAULT_SYMPTOM, max_steps: int = 20, verbose: bool = True) -> dict:
    global _APP
    if _APP is None:
        _APP = build_graph()
    case = Case(symptom=symptom, max_steps=max_steps, verbose=verbose)
    _APP.invoke({"case": case}, config={"recursion_limit": 200})
    return case.result


def print_report(res: dict) -> None:
    d, s = res["diagnosis"], res["stats"]
    print("\n==================== DIAGNOSIS ====================")
    print(f"Root cause : {d['cause']} on {d['device']} ({d['layer']})  [{d['status']}, {d['confidence']:.0%}]")
    print("Evidence shows (from tools):")
    for line in res["evidence_shows"]:
        print(f"  {line}")
    print(f"LLM explanation : {res['llm_explanation']}")
    print(f"LLM suggested fix: {res['suggested_fix']}")
    print(f"Stats: {s['tool_calls']} tool calls, {s['llm_calls']} LLM calls ({s['llm_fallbacks']} fallbacks), "
          f"citations repaired: {s['citations_repaired']}, {s['seconds']}s")


def main(argv: list) -> int:
    args = list(argv)
    verbose = "--quiet" not in args
    as_json = "--json" in args
    max_steps = 20
    if "--max-steps" in args:
        i = args.index("--max-steps")
        max_steps = int(args[i + 1])
        del args[i:i + 2]
    args = [a for a in args if not a.startswith("--")]
    res = run_agent(args[0] if args else DEFAULT_SYMPTOM, max_steps, verbose)
    print(json.dumps(res, indent=2) if as_json else "", end="" if not as_json else "\n")
    if not as_json:
        print_report(res)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
