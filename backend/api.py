"""FastAPI backend: runs ANTA jobs and streams progress events (SSE) to the dashboard.
Run (from ~/ANTA, venv active): uvicorn backend.api:app --port 8000"""
from __future__ import annotations

import asyncio
import json
import math
import threading
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import agent  # noqa: F401  (adds network/ and network/fault_injection to sys.path)
from agent.anta import DEFAULT_SYMPTOM, Case, build_graph
from benchmark.evaluator import _agg, connect
from benchmark.runner import SCEN_DIR
from experiments.compare import wilson
from remediation.run_gate_eval import unsafe_cases
from remediation.safe_pipeline import remediate_gated
from scenario_faults import inject, reset_network
from tools import TOOLS, to_dict

TOPO: dict = {}
JOBS: dict = {}
STATE: dict = {"job": None}
LOCK = threading.Lock()


class Job:
    def __init__(self, job_id: str, params: dict):
        self.id, self.params = job_id, params
        self.events: list = []
        self.done = False
        self.started = time.time()

    def emit(self, type_: str, **data) -> None:
        self.events.append({"t": round(time.time() - self.started, 2), "type": type_, **data})


class RunRequest(BaseModel):
    mode: str = "diagnose"            # diagnose | gated | unsafe_demo
    scenario_id: Optional[str] = None
    symptom: Optional[str] = None
    unsafe_case: Optional[str] = None
    inject: bool = True


def _warm() -> None:
    """Load the model at start-up so the first click in the dashboard is not a 40 s freeze."""
    try:
        from agent import llm
        llm.chat_json("Reply with JSON only.", '{"ok": true}')
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        TOPO["live"] = to_dict(TOOLS["get_topology"]["fn"]())
    except Exception:
        pass
    threading.Thread(target=_warm, daemon=True).start()
    yield


app = FastAPI(title="ANTA", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _scenarios() -> list:
    return [json.loads(p.read_text()) for p in sorted(SCEN_DIR.glob("s*.json"))]


def _hyps(case) -> list:
    return [{"id": h.id, "cause": h.cause, "device": h.device, "layer": h.layer, "description": h.description,
             "confidence": round(h.confidence, 4), "status": h.status} for h in case.hyps]


def _run_diagnosis(job: Job, symptom: str, truth: Optional[dict]) -> dict:
    case = Case(symptom=symptom, verbose=False)
    job.emit("stage", stage="diagnose", message="ANTA is investigating the symptom")
    for update in build_graph().stream({"case": case}, config={"recursion_limit": 200}, stream_mode="updates"):
        node = next(iter(update))
        if node == "init":
            job.emit("hypotheses", step=0, hypotheses=_hyps(case))
        elif node == "plan":
            t = case.pending
            src = "confirm" if case.pending_reason.startswith("confirm") else ("LLM" if case.pending_llm else "fallback")
            job.emit("plan", step=len(case.executed) + 1, test=t.id, description=t.description,
                     reason=case.pending_reason, source=src)
        elif node == "update":
            ev = case.last_ev
            job.emit("evidence", id=ev.id, test=ev.test_id, summary=ev.summary, step=len(case.executed))
            job.emit("hypotheses", step=len(case.executed), hypotheses=_hyps(case))
        elif node == "conclude":
            res = case.result
            job.emit("hypotheses", step=len(case.executed), hypotheses=_hyps(case))
            job.emit("diagnosis", diagnosis=res["diagnosis"], explanation=res["llm_explanation"],
                     suggested_fix=res["suggested_fix"], evidence_shows=res["evidence_shows"],
                     stats=res["stats"], truth=truth)
    return case.result["diagnosis"]


def _worker(job: Job) -> None:
    p = job.params
    try:
        sc = next((s for s in _scenarios() if s["id"] == p.get("scenario_id")), None)
        symptom = p.get("symptom") or (sc["symptom"] if sc else DEFAULT_SYMPTOM)
        truth = None
        if p["mode"] == "unsafe_demo":
            name = p.get("unsafe_case") or "overbroad_flush"
            _, fault, setup, action, _ = next(c for c in unsafe_cases() if c[0] == name)
            job.emit("stage", stage="inject", message=f"Resetting the lab, injecting a fault, and preparing a BUGGY fix ({name})")
            reset_network(); time.sleep(1)
            inject(fault); time.sleep(1)
            if setup:
                setup()
            diag = _run_diagnosis(job, symptom, None)
            job.emit("stage", stage="remediate", message="A buggy fix is proposed. The shadow gate must catch it.")
            remediate_gated(diag, action_factory=lambda: action, on_event=job.emit, verbose=False)
        else:
            if sc and p.get("inject", True):
                job.emit("stage", stage="reset", message="Resetting the lab to a healthy baseline")
                reset_network(); time.sleep(1)
                job.emit("stage", stage="inject", message=f"Injecting a fault ({sc['tier']}). The diagnosis is hidden from ANTA.")
                inject(sc["injected_fault"]); time.sleep(1)
                truth = {k: sc["ground_truth"][k] for k in ("cause", "device", "layer")}
            diag = _run_diagnosis(job, symptom, truth)
            if p["mode"] == "gated":
                job.emit("stage", stage="remediate", message="Proposing a fix and validating it on the shadow network")
                remediate_gated(diag, on_event=job.emit, verbose=False)
        job.emit("done")
    except Exception as e:  # report to the UI instead of dying silently
        job.emit("error", message=f"{type(e).__name__}: {e}")
    finally:
        job.done = True


@app.get("/api/status")
def status():
    j = STATE["job"]
    return {"busy": bool(j and not j.done), "job_id": j.id if j else None}


@app.get("/api/topology")
def topology():
    if "live" not in TOPO:
        raise HTTPException(503, "topology not available (is the lab running?)")
    return TOPO["live"]


@app.get("/api/scenarios")
def scenarios():
    return [{"id": s["id"], "description": s["description"], "tier": s["tier"], "split": s["split"],
             "symptom": s["symptom"]} for s in _scenarios()]


@app.post("/api/run")
def run(req: RunRequest):
    with LOCK:
        if STATE["job"] and not STATE["job"].done:
            raise HTTPException(409, "a job is already running")
        job = Job(uuid.uuid4().hex[:8], req.model_dump())
        STATE["job"] = job
        JOBS[job.id] = job
    threading.Thread(target=_worker, args=(job,), daemon=True).start()
    return {"job_id": job.id}


@app.post("/api/reset")
def reset():
    with LOCK:
        if STATE["job"] and not STATE["job"].done:
            raise HTTPException(409, "a job is running")
        reset_network()
    return {"ok": True}


@app.get("/api/jobs/{job_id}/events")
async def events(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job")

    async def gen():
        i = 0
        while True:
            while i < len(job.events):
                yield f"data: {json.dumps(job.events[i])}\n\n"
                i += 1
            if job.done and i >= len(job.events):
                break
            await asyncio.sleep(0.15)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _num(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else x


@app.get("/api/results")
def results():
    con = connect()
    out: dict = {"systems": [], "remediation": None, "gate": None}
    for s in ("llm_only", "react", "anta"):
        rows = [dict(r) for r in con.execute("SELECT * FROM runs WHERE system = ?", (s,))]
        if not rows:
            continue
        entry: dict = {"system": s}
        for label, pick in (("test", lambda r: r["split"] == "test"), ("all", lambda r: r["split"] not in ("stress", "stress_test"))):
            sub = [r for r in rows if pick(r)]
            if sub:
                a = _agg(sub)
                lo, hi = wilson(sum(r["rca_ok"] for r in sub), len(sub))
                entry[label] = {"n": a["n"], "rca": _num(a["rca"]), "detect": _num(a["detect"]),
                                "calls": _num(a["calls"]), "sec": _num(a["sec"]), "ci": [_num(lo), _num(hi)]}
        out["systems"].append(entry)
    try:
        rem = [dict(r) for r in con.execute("SELECT * FROM remediation_runs")]
        faults = [r for r in rem if r["fault_type"] != "no_fault"]
        if faults:
            out["remediation"] = {"faults": len(faults), "fixed": sum(r["fixed"] for r in faults),
                                  "regressions": sum(r["regression"] for r in faults),
                                  "healthy_cases": len(rem) - len(faults),
                                  "wrongly_acted": sum(1 for r in rem if r["fault_type"] == "no_fault" and r["action_id"])}
        g = [dict(r) for r in con.execute("SELECT * FROM gate_runs")]
        if g:
            by = lambda k: [r for r in g if r["kind"] == k]
            out["gate"] = {
                "correct": [sum(r["ok"] for r in by("correct_diagnosis")), len(by("correct_diagnosis"))],
                "wrong": [sum(r["ok"] for r in by("wrong_diagnosis")), len(by("wrong_diagnosis"))],
                "unsafe": [sum(r["ok"] for r in by("unsafe_action")), len(by("unsafe_action"))],
                "ungated_harmful": sum(1 for r in by("unsafe_action") if r["ungated_regression"] or not r["ungated_fixed"]),
                "fidelity": [sum(r["fidelity"] for r in g), len(g)]}
    except Exception:
        pass
    try:  # before/after on the unseen fault types
        st: dict = {}
        for label, system in (("v1", "anta_v1"), ("v2", "anta")):
            rows = [dict(r) for r in con.execute(
                "SELECT * FROM runs WHERE system = ? AND split IN ('stress', 'stress_test')", (system,))]
            if rows:
                st[label] = {"n": len(rows), "correct": sum(r["rca_ok"] for r in rows),
                             "confidently_wrong": sum(1 for r in rows if not r["rca_ok"] and r["status"] == "confirmed")}
        out["stress"] = st or None
    except Exception:
        out["stress"] = None
    try:  # ablation table, if the ablation report has been generated
        import csv as _csv
        path = agent.ROOT / "experiments" / "results" / "ablations.csv"
        out["ablations"] = ([{**r, "rca": float(r["rca"]), "confidently_wrong": int(r["confidently_wrong"]),
                              "calls": float(r["calls"]), "sec": float(r["sec"])}
                             for r in _csv.DictReader(path.open())] if path.exists() else [])
    except Exception:
        out["ablations"] = []
    return out
