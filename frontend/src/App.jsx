import React, { useEffect, useReducer, useState } from "react";
import Topology from "./components/Topology.jsx";
import Results from "./components/Results.jsx";
import { Card, GatePanel, Hypotheses, Timeline } from "./components/Panels.jsx";

const initial = { running: false, message: "Pick a scenario and press Run.", hyps: [], steps: [], diagnosis: null,
  gate: {}, truth: null, error: null, activeTest: null };

function reducer(state, ev) {
  switch (ev.type) {
    case "reset": return { ...initial, running: true, message: "Starting…" };
    case "stage": return { ...state, message: ev.message };
    case "hypotheses": return { ...state, hyps: ev.hypotheses };
    case "plan":
      return { ...state, activeTest: ev.test,
        steps: [...state.steps, { step: ev.step, test: ev.test, description: ev.description, reason: ev.reason, source: ev.source, evidence: null }] };
    case "evidence":
      return { ...state, activeTest: null,
        steps: state.steps.map((s) => (s.test === ev.test && !s.evidence ? { ...s, evidence: { id: ev.id, summary: ev.summary } } : s)) };
    case "diagnosis": return { ...state, diagnosis: ev, activeTest: null, truth: ev.truth || null };
    case "fix_proposed": return { ...state, gate: { ...state.gate, action: ev.action } };
    case "shadow": {
      const sh = { ...(state.gate.shadow || {}) };
      if (ev.phase === "cloning") sh.cloning = true;
      if (ev.phase === "cloned") { sh.cloning = false; sh.cloned = true; }
      if (ev.phase === "fidelity") sh.fidelity = ev;
      if (ev.phase === "tested") sh.tested = ev;
      return { ...state, gate: { ...state.gate, shadow: sh } };
    }
    case "decision": return { ...state, gate: { ...state.gate, decision: ev } };
    case "live": {
      const lv = { ...(state.gate.live || {}) };
      if (ev.phase === "applying") lv.applying = true;
      if (ev.phase === "result") { lv.applying = false; lv.result = ev; }
      if (ev.phase === "untouched") lv.untouched = ev.untouched;
      return { ...state, gate: { ...state.gate, live: lv } };
    }
    case "done": return { ...state, running: false, message: `Done in ${ev.t}s.` };
    case "error": return { ...state, running: false, error: ev.message };
    default: return state;
  }
}

export default function App() {
  const [tab, setTab] = useState("live");
  const [topo, setTopo] = useState(null);
  const [scenarios, setScenarios] = useState([]);
  const [scenarioId, setScenarioId] = useState("");
  const [mode, setMode] = useState("gated");
  const [unsafeCase, setUnsafeCase] = useState("overbroad_flush");
  const [state, dispatch] = useReducer(reducer, initial);

  useEffect(() => {
    fetch("/api/topology").then((r) => (r.ok ? r.json() : null)).then(setTopo).catch(() => {});
    fetch("/api/scenarios").then((r) => r.json()).then((list) => {
      setScenarios(list);
      if (list.length) setScenarioId((list.find((s) => s.id === "s03") || list[0]).id);
    }).catch(() => {});
  }, []);

  const run = async () => {
    dispatch({ type: "reset" });
    const body = { mode, scenario_id: mode === "unsafe_demo" ? null : scenarioId, unsafe_case: unsafeCase };
    const res = await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      dispatch({ type: "error", message: d.detail || "could not start the job" });
      return;
    }
    const { job_id } = await res.json();
    const es = new EventSource(`/api/jobs/${job_id}/events`);
    es.onmessage = (m) => {
      const ev = JSON.parse(m.data);
      dispatch(ev);
      if (ev.type === "done" || ev.type === "error") es.close();
    };
    es.onerror = () => es.close();
  };

  const resetLab = async () => {
    dispatch({ type: "stage", message: "Resetting the lab…" });
    const res = await fetch("/api/reset", { method: "POST" });
    dispatch({ type: "stage", message: res.ok ? "Lab reset to a healthy baseline." : "Cannot reset while a job is running." });
  };

  const dg = state.diagnosis && state.diagnosis.diagnosis;
  const truthOk = dg && state.truth && dg.cause === state.truth.cause && dg.device === state.truth.device;

  return (
    <div>
      <header>
        <h1><span>ANTA</span> · Autonomous Network Troubleshooting Agent</h1>
        <div className="tabs">
          <button className={tab === "live" ? "on" : ""} onClick={() => setTab("live")}>Live investigation</button>
          <button className={tab === "results" ? "on" : ""} onClick={() => setTab("results")}>Benchmark results</button>
        </div>
      </header>

      {tab === "results" ? <Results /> : (
        <>
          <div className="controls">
            <select value={mode} onChange={(e) => setMode(e.target.value)} disabled={state.running}>
              <option value="diagnose">Diagnose only</option>
              <option value="gated">Diagnose + shadow-gated fix</option>
              <option value="unsafe_demo">Unsafe-fix demo (the gate must block it)</option>
            </select>
            {mode === "unsafe_demo" ? (
              <select value={unsafeCase} onChange={(e) => setUnsafeCase(e.target.value)} disabled={state.running}>
                <option value="overbroad_flush">Over-broad fix: flushes the whole firewall chain</option>
                <option value="collateral_route_delete">Collateral damage: deletes the client's default route</option>
                <option value="bad_config_push">Bad config push: breaks the web server config</option>
              </select>
            ) : (
              <select value={scenarioId} onChange={(e) => setScenarioId(e.target.value)} disabled={state.running} style={{ maxWidth: 420 }}>
                {scenarios.map((s) => <option key={s.id} value={s.id}>{s.id} · {s.description} ({s.tier})</option>)}
              </select>
            )}
            <button className="btn primary" onClick={run} disabled={state.running}>Run</button>
            <button className="btn" onClick={resetLab} disabled={state.running}>Reset lab</button>
            <span className={`status ${state.error ? "err" : ""}`}>{state.error || state.message}</span>
          </div>

          <main className="grid">
            <div className="col">
              <Card title="Network"><Topology topo={topo} hyps={state.hyps} diagnosis={state.diagnosis} gate={state.gate} activeTest={state.activeTest} /></Card>
              <Card title="Shadow-gated remediation"><GatePanel gate={state.gate} /></Card>
            </div>
            <div className="col">
              <Card title="Diagnosis">
                {!dg ? <p className="muted">Waiting for the investigation to conclude.</p> : (
                  <div>
                    <div className={`diag-h ${dg.cause === "no_fault" ? "ok" : "bad"}`}>
                      {dg.cause === "no_fault" ? "No fault found: the network is healthy" : `${dg.cause} on ${dg.device} (${dg.layer})`}
                    </div>
                    <div className="kv">{dg.status} · confidence {(dg.confidence * 100).toFixed(0)}% · {state.diagnosis.stats.tool_calls} tool calls · {state.diagnosis.stats.seconds}s</div>
                    {state.truth && <div className="kv">Injected fault (hidden from ANTA): {state.truth.cause} on {state.truth.device} {truthOk ? "✓ match" : "✗ mismatch"}</div>}
                    <p><b>Evidence shows</b> <span className="muted small">(measured by tools)</span></p>
                    <ul>{state.diagnosis.evidence_shows.map((e, i) => <li key={i} className="small">{e}</li>)}</ul>
                    <p><b>LLM explanation</b> <span className="muted small">(model output, citations validated)</span></p>
                    <p className="small" style={{ color: "#a5b4fc" }}>{state.diagnosis.explanation}</p>
                  </div>
                )}
              </Card>
              <Card title="Hypotheses (confidence computed from evidence, never guessed by the LLM)"><Hypotheses hyps={state.hyps} /></Card>
              <Card title="Investigation timeline"><Timeline steps={state.steps} activeTest={state.activeTest} /></Card>
            </div>
          </main>
        </>
      )}
    </div>
  );
}
