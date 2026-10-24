"""Metrics + SQLite store for the ANTA benchmark."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from . import ROOT

DB_PATH = ROOT / "experiments" / "results" / "anta_bench.sqlite"
COLUMNS = ["run_id", "system", "scenario_id", "split", "tier", "fault_type", "truth_cause", "truth_device",
           "truth_layer", "pred_cause", "pred_device", "pred_layer", "confidence", "status", "detection_ok",
           "cause_ok", "device_ok", "layer_ok", "rca_ok", "evidence_quality", "tool_calls", "llm_calls",
           "seconds", "error", "result_json", "ts"]
SCHEMA = """CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, system TEXT, scenario_id TEXT, split TEXT, tier TEXT, fault_type TEXT,
  truth_cause TEXT, truth_device TEXT, truth_layer TEXT, pred_cause TEXT, pred_device TEXT, pred_layer TEXT,
  confidence REAL, status TEXT, detection_ok INTEGER, cause_ok INTEGER, device_ok INTEGER, layer_ok INTEGER,
  rca_ok INTEGER, evidence_quality REAL, tool_calls INTEGER, llm_calls INTEGER, seconds REAL, error TEXT,
  result_json TEXT, ts TEXT)"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute(SCHEMA)
    return con


def evaluate(sc: dict, out, error, system: str, run_id: str) -> dict:
    gt = sc["ground_truth"]
    truth_fault = gt["cause"] != "no_fault"
    d = out["diagnosis"] if out else {}
    cause_ok = bool(out) and d.get("cause") == gt["cause"]
    device_ok = bool(out) and d.get("device") == gt["device"]
    layer_ok = bool(out) and d.get("layer") == gt["layer"]
    detection_ok = bool(out) and ((d.get("cause") != "no_fault") == truth_fault)
    req = gt.get("evidence_required") or []
    eq = None
    if req:
        found: set = set()
        if out:
            cited = set(out.get("evidence_ids", []))
            for e in out.get("evidence", []):
                if e["id"] in cited:
                    found |= set(e["findings"])
        eq = sum(k in found for k in req) / len(req)
    stats = (out or {}).get("stats", {})
    return {
        "run_id": run_id, "system": system, "scenario_id": sc["id"], "split": sc["split"], "tier": sc["tier"],
        "fault_type": gt["cause"], "truth_cause": gt["cause"], "truth_device": gt["device"],
        "truth_layer": gt["layer"], "pred_cause": d.get("cause"), "pred_device": d.get("device"),
        "pred_layer": d.get("layer"), "confidence": d.get("confidence"), "status": d.get("status", "error"),
        "detection_ok": int(detection_ok), "cause_ok": int(cause_ok), "device_ok": int(device_ok),
        "layer_ok": int(layer_ok), "rca_ok": int(cause_ok and device_ok), "evidence_quality": eq,
        "tool_calls": stats.get("tool_calls"), "llm_calls": stats.get("llm_calls"), "seconds": stats.get("seconds"),
        "error": error, "result_json": json.dumps(out) if out else None, "ts": datetime.now().isoformat(),
    }


def insert(con: sqlite3.Connection, row: dict) -> None:
    con.execute(f"INSERT OR REPLACE INTO runs ({','.join(COLUMNS)}) VALUES ({','.join('?' * len(COLUMNS))})",
                [row[c] for c in COLUMNS])
    con.commit()


def _agg(rows: list) -> dict:
    n = len(rows)
    eq = [r["evidence_quality"] for r in rows if r["evidence_quality"] is not None]
    calls = [r["tool_calls"] for r in rows if r["tool_calls"] is not None]
    secs = [r["seconds"] for r in rows if r["seconds"] is not None]
    mean = lambda xs: sum(xs) / len(xs) if xs else float("nan")
    return {"n": n, "detect": mean([r["detection_ok"] for r in rows]), "cause": mean([r["cause_ok"] for r in rows]),
            "device": mean([r["device_ok"] for r in rows]), "layer": mean([r["layer_ok"] for r in rows]),
            "rca": mean([r["rca_ok"] for r in rows]), "evid": mean(eq), "calls": mean(calls), "sec": mean(secs)}


def _print(title: str, groups: dict) -> None:
    print(f"\n{title}")
    print(f"  {'group':20s} {'n':>3s} {'detect':>7s} {'cause':>6s} {'device':>7s} {'layer':>6s} {'RCA':>5s} "
          f"{'evid':>5s} {'calls':>6s} {'sec':>6s}")
    for name, rows in groups.items():
        a = _agg(rows)
        print(f"  {name:20s} {a['n']:3d} {a['detect']:7.0%} {a['cause']:6.0%} {a['device']:7.0%} {a['layer']:6.0%} "
              f"{a['rca']:5.0%} {a['evid']:5.0%} {a['calls']:6.1f} {a['sec']:6.1f}")


def report(con: sqlite3.Connection, system: str) -> None:
    rows = [dict(r) for r in con.execute("SELECT * FROM runs WHERE system = ? ORDER BY scenario_id", (system,))]
    if not rows:
        print("no runs recorded")
        return

    def group(key):
        out: dict = {}
        for r in rows:
            out.setdefault(r[key], []).append(r)
        return dict(sorted(out.items()))

    print(f"\n==================== BENCHMARK REPORT: {system} ({len(rows)} runs) ====================")
    _print("OVERALL", {"all": rows})
    _print("BY SPLIT (report TEST as the headline number)", group("split"))
    _print("BY TIER", group("tier"))
    _print("BY TRUE FAULT TYPE", group("fault_type"))
    wrong = [r for r in rows if not r["rca_ok"]]
    print(f"\nMISSES ({len(wrong)}):")
    for r in wrong:
        print(f"  {r['scenario_id']} [{r['split']}/{r['tier']}] truth={r['truth_cause']}@{r['truth_device']}  "
              f"pred={r['pred_cause']}@{r['pred_device']} ({r['confidence'] if r['confidence'] is not None else '-'}) "
              f"{r['error'] or ''}")
