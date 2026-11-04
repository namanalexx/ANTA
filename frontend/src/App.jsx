import React, { useEffect, useReducer, useRef, useState } from "react";
import DotHero from "./components/DotHero.jsx";
import Topology from "./components/Topology.jsx";
import Results from "./components/Results.jsx";
import { Card, GatePanel, Hypotheses, Mark, Timeline } from "./components/Panels.jsx";

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

const groupOf = (s) => (s.split === "final" ? "Final held-out batch" : s.split === "stress" || s.split === "stress_test" ? "Interface and link faults" : "Main benchmark");

export default function App() {
  const [view, setView] = useState("live");
  const [scrolled, setScrolled] = useState(false);
  const [topo, setTopo] = useState(null);
  const [scenarios, setScenarios] = useState([]);
  const [scenarioId, setScenarioId] = useState("");
  const [mode, setMode] = useState("gated");
  const [unsafeCase, setUnsafeCase] = useState("overbroad_flush");
  const [state, dispatch] = useReducer(reducer, initial);
  const wsRef = useRef(null);

  useEffect(() => {
    fetch("/api/topology").then((r) => (r.ok ? r.json() : null)).then(setTopo).catch(() => {});
    fetch("/api/scenarios").then((r) => r.json()).then((list) => {
      setScenarios(list);
      if (list.length) setScenarioId((list.find((s) => s.id === "s03") || list[0]).id);
    }).catch(() => {});
    const onScroll = () => setScrolled(window.scrollY > 40);
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const go = (v) => {
    setView(v);
    setTimeout(() => wsRef.current && wsRef.current.scrollIntoView({ behavior: "smooth", block: "start" }), 30);
  };

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
  const groups = {};
  scenarios.forEach((s) => { (groups[groupOf(s)] = groups[groupOf(s)] || []).push(s); });

  return (
    <div id="top">
      <header className={`nav ${scrolled ? "scrolled" : ""}`}>
        <a className="brand" href="#top"><Mark />ANTA</a>
        <button className={`navlink ${view === "live" ? "on" : ""}`} onClick={() => go("live")}>Investigate</button>
        <button className={`navlink ${view === "results" ? "on" : ""}`} onClick={() => go("results")}>Results</button>
        <button className="pill" onClick={resetLab} disabled={state.running}>Reset lab</button>
      </header>

      <section className="hero">
        <DotHero running={state.running} />
        <div className="copy">
          <h1><span className="g">Autonomous network</span>troubleshooting.</h1>
          <p>Evidence-driven diagnosis. Every fix proven on a shadow network first.</p>
          <div className="cta"><button onClick={() => go("live")}>Run an investigation</button></div>
        </div>
      </section>

      <section id="workspace" className="ws" ref={wsRef}>
        <div className="ws-head">
          <h2><span className="g">{view === "live" ? "Live" : "Benchmark"}</span> {view === "live" ? "investigation" : "results"}</h2>
          <p>{view === "live"
            ? "Hypotheses compete on evidence measured by real tools. The LLM chooses tests and explains; it never sets confidence."
            : "Every number comes from the automated benchmark database. Whiskers are 95% confidence intervals."}</p>
        </div>

        {view === "results" ? <Results /> : (
          <>
            <div className="controls">
              <select value={mode} onChange={(e) => setMode(e.target.value)} disabled={state.running}>
                <option value="diagnose">Diagnose only</option>
                <option value="gated">Diagnose and shadow-gated fix</option>
                <option value="unsafe_demo">Unsafe-fix demo (the gate must block it)</option>
              </select>
              {mode === "unsafe_demo" ? (
                <select value={unsafeCase} onChange={(e) => setUnsafeCase(e.target.value)} disabled={state.running}>
                  <option value="overbroad_flush">Over-broad fix: flushes the whole firewall chain</option>
                  <option value="collateral_route_delete">Collateral damage: deletes the client's default route</option>
                  <option value="bad_config_push">Bad config push: breaks the web server config</option>
                </select>
              ) : (
                <select value={scenarioId} onChange={(e) => setScenarioId(e.target.value)} disabled={state.running}>
                  {Object.entries(groups).map(([g, list]) => (
                    <optgroup key={g} label={g}>{list.map((s) => <option key={s.id} value={s.id}>{s.id} · {s.description}</option>)}</optgroup>
                  ))}
                </select>
              )}
              <div className={`cta ${state.running ? "off" : ""}`} style={{ marginTop: 0 }}>
                <button onClick={run} disabled={state.running}>{state.running ? "Running…" : "Run"}</button>
              </div>
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
                      <div className="dx">
                        {dg.cause === "no_fault" ? <>No known fault <em>found</em></> : <>{dg.cause.replace(/_/g, " ")} <em>on {dg.device} ({dg.layer})</em></>}
                      </div>
                      <div className="chips">
                        <span className={`chip-pill ${dg.status === "confirmed" ? "solid" : "line"}`}>{dg.status === "confirmed" ? "Confirmed" : "Best guess"}</span>
                        <span className="meta">{Math.round(dg.confidence * 100)}% confidence · {state.diagnosis.stats.tool_calls} tool calls · {state.diagnosis.stats.seconds}s</span>
                      </div>
                      {dg.cause === "no_fault" && <div className="note">No fault in ANTA's library explains the evidence. This is not proof the network is healthy.</div>}
                      {state.truth && <div className="truth">Injected fault (hidden from ANTA): {state.truth.cause} on {state.truth.device} <b>{truthOk ? "✓ match" : "✕ mismatch"}</b></div>}
                      <h4>Evidence <span>measured by tools</span></h4>
                      <ul className="ev">{state.diagnosis.evidence_shows.map((e, i) => {
                        const k = e.indexOf(":");
                        return <li key={i}><code>{e.slice(0, k)}</code><span>{e.slice(k + 1).trim()}</span></li>;
                      })}</ul>
                      <h4>Explanation <span>LLM output, citations validated</span></h4>
                      <p className="expl">{state.diagnosis.explanation}</p>
                    </div>
                  )}
                </Card>
                <Card title="Hypotheses: confidence computed from evidence, never guessed by the LLM"><Hypotheses hyps={state.hyps} /></Card>
                <Card title="Investigation timeline"><Timeline steps={state.steps} activeTest={state.activeTest} /></Card>
              </div>
            </main>
          </>
        )}
      </section>
    </div>
  );
}
