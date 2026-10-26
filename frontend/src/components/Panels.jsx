import React from "react";

export function Card({ title, children, right }) {
  return (
    <section className="card">
      <div className="card-h"><h3>{title}</h3>{right}</div>
      {children}
    </section>
  );
}

export function Hypotheses({ hyps }) {
  if (!hyps.length) return <p className="muted">No investigation yet. Pick a scenario and press Run.</p>;
  const sorted = [...hyps].sort((a, b) => b.confidence - a.confidence);
  return (
    <div>
      {sorted.map((h) => (
        <div key={h.id} className={`hyp ${h.status}`}>
          <div className="hyp-top">
            <span className="chip">{h.id}</span>
            <span className="hyp-name">{h.cause} <em>@ {h.device}</em></span>
            <span className="pct">{(h.confidence * 100).toFixed(0)}%</span>
          </div>
          <div className="bar"><div className="fill" style={{ width: `${Math.max(1, h.confidence * 100)}%` }} /></div>
          <div className="hyp-desc">{h.description}</div>
        </div>
      ))}
    </div>
  );
}

export function Timeline({ steps, activeTest }) {
  if (!steps.length) return <p className="muted">Each step shows what the LLM chose and why (italic), then what the tool measured (green).</p>;
  return (
    <ol className="timeline">
      {steps.map((s, i) => (
        <li key={i}>
          <div className="t-top">
            <b>{s.step}. {s.test}</b>
            <span className={`badge ${s.source}`}>{s.source === "confirm" ? "rule: confirm" : s.source}</span>
            {!s.evidence && activeTest === s.test && <span className="spin" />}
          </div>
          <div className="muted small">{s.description}</div>
          {s.reason && <div className="reason">LLM: “{s.reason}”</div>}
          {s.evidence && <div className="evidence"><code>{s.evidence.id}</code> {s.evidence.summary}</div>}
        </li>
      ))}
    </ol>
  );
}

function stateOf(done, active, fail, skip) {
  return fail ? "fail" : done ? "done" : active ? "active" : skip ? "skip" : "idle";
}

export function GatePanel({ gate }) {
  const g = gate || {};
  const sh = g.shadow || {};
  const lv = g.live || {};
  const blocked = g.decision && g.decision.decision.startsWith("blocked");
  const items = [
    { label: "Fix proposed (from the playbook)", st: stateOf(!!g.action),
      detail: g.action && (<><span>{g.action.description}</span>{g.action.commands.map((c, i) => <code className="cmd" key={i}>{c}</code>)}</>) },
    { label: "Live state cloned onto the shadow stack", st: stateOf(sh.cloned, sh.cloning) },
    { label: "Shadow reproduces the live symptoms", st: stateOf(sh.fidelity && sh.fidelity.ok, false, sh.fidelity && !sh.fidelity.ok),
      detail: sh.fidelity && !sh.fidelity.ok && <span>Shadow anomalies differ from live: the verdict is inconclusive.</span> },
    { label: "Fix tested on the shadow (verify + regression check)",
      st: stateOf(sh.tested && sh.tested.fixed && !sh.tested.regression, false, sh.tested && !(sh.tested.fixed && !sh.tested.regression), sh.fidelity && !sh.fidelity.ok),
      detail: sh.tested && (<span>fixed: {String(sh.tested.fixed)} · regression: {String(sh.tested.regression)} {sh.tested.unintended.length ? "· " + sh.tested.unintended[0] : ""}</span>) },
    { label: "Gate decision", st: stateOf(g.decision && !blocked, false, blocked),
      detail: g.decision && <span>{g.decision.decision}: {g.decision.reason}</span> },
    { label: "Applied to live, verified, regression-checked",
      st: stateOf(lv.result && lv.result.fixed && !lv.result.regression, lv.applying, lv.result && !(lv.result.fixed && !lv.result.regression), blocked),
      detail: blocked ? <span>Skipped. Live network untouched: {String(lv.untouched)}</span>
        : lv.result && <span>fixed: {String(lv.result.fixed)} · regression: {String(lv.result.regression)}</span> },
  ];
  const icon = { idle: "○", active: "◔", done: "✓", fail: "✗", skip: "–" };
  return (
    <div>
      <ul className="gate">
        {items.map((it, i) => (
          <li key={i} className={`s-${it.st}`}>
            <span className="ico">{icon[it.st]}</span>
            <div><div>{it.label}</div><div className="muted small">{it.detail}</div></div>
          </li>
        ))}
      </ul>
      {blocked && <div className="verdict good">Blocked by the shadow gate. The live network was never touched.</div>}
      {lv.result && lv.result.fixed && !lv.result.regression && <div className="verdict good">Fix applied and verified. No regression.</div>}
    </div>
  );
}
