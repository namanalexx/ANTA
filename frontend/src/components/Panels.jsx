import React, { useEffect, useRef, useState } from "react";

export function Mark({ size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 18 18" aria-hidden="true">
      <path d="M5 9h2M11 9l3-4M11 9l3 4" stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinecap="round" />
      <circle cx="3" cy="9" r="2.2" fill="currentColor" /><circle cx="9" cy="9" r="2.2" fill="currentColor" />
      <circle cx="15" cy="4" r="2.2" fill="currentColor" /><circle cx="15" cy="14" r="2.2" fill="currentColor" />
    </svg>
  );
}

export function Card({ title, right, children }) {
  return (
    <section className="card">
      <div className="card-h"><h3>{title}</h3>{right}</div>
      {children}
    </section>
  );
}

const pc = (x) => `${Math.round(x * 100)}%`;

export function Hypotheses({ hyps }) {
  if (!hyps.length) return <p className="muted">No investigation yet. Pick a scenario and press Run.</p>;
  const sorted = [...hyps].sort((a, b) => b.confidence - a.confidence);
  const live = sorted.filter((h) => h.status !== "rejected");
  const out = sorted.filter((h) => h.status === "rejected");
  return (
    <div>
      {live.map((h, i) => (
        <div key={h.id} className={`hyp ${i === 0 ? "lead" : ""}`}>
          <div className="hyp-top">
            <span className="id">{h.id}</span>
            <span className="nm">{h.cause.replace(/_/g, " ")} <em>@ {h.device}</em></span>
            <span className="pc">{h.status === "confirmed" ? "✓ " : ""}{pc(h.confidence)}</span>
          </div>
          <div className="bar"><i style={{ width: `${Math.max(1, h.confidence * 100)}%` }} /></div>
          <div className="ds">{h.description}</div>
        </div>
      ))}
      {out.length > 0 && (
        <details className="out">
          <summary>Ruled out ({out.length})</summary>
          {out.map((h) => (
            <div key={h.id} className="out-row">
              <span className="mono small">{h.id}</span>
              <span className="nm">{h.cause.replace(/_/g, " ")} @ {h.device}</span>
              <span className="pc">{pc(h.confidence)}</span>
            </div>
          ))}
        </details>
      )}
    </div>
  );
}

export function Timeline({ steps, activeTest }) {
  const box = useRef(null);
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight; }, [steps.length, activeTest]);
  if (!steps.length) return <p className="muted">Each step shows what the LLM chose and why (italic), then what the tool measured.</p>;
  return (
    <ol className="tl" ref={box}>
      {steps.map((s, i) => (
        <li key={i}>
          <span className="n">{String(s.step).padStart(2, "0")}</span>
          <div>
            <div className="t">{s.test}
              <span className={`badge ${s.source}`}>{s.source === "confirm" ? "rule" : s.source}</span>
              {!s.evidence && activeTest === s.test && <span className="spin" />}
            </div>
            <div className="d">{s.description}</div>
            {s.reason && <div className="r">“{s.reason}”</div>}
            {s.evidence && <div className="e"><code>{s.evidence.id}</code>{s.evidence.summary}</div>}
          </div>
        </li>
      ))}
    </ol>
  );
}

export function GatePanel({ gate }) {
  const g = gate || {}, sh = g.shadow || {}, lv = g.live || {};
  const blocked = !!(g.decision && g.decision.decision.startsWith("blocked"));
  const applied = !!(lv.result && lv.result.fixed && !lv.result.regression);
  const items = [
    { label: "Fix proposed from the playbook", st: g.action ? "done" : "idle",
      detail: g.action && (<><div>{g.action.description}</div>{g.action.commands.map((c, i) => <code className="cmd" key={i}>{c}</code>)}</>) },
    { label: "Live state cloned onto the shadow network", st: sh.cloned ? "done" : sh.cloning ? "active" : "idle" },
    { label: "Shadow reproduces the live symptoms", st: sh.fidelity ? (sh.fidelity.ok ? "done" : "fail") : "idle",
      detail: sh.fidelity && !sh.fidelity.ok && "The shadow differs from live, so the verdict is inconclusive." },
    { label: "Fix tested on the shadow: verify and regression check",
      st: sh.tested ? (sh.tested.fixed && !sh.tested.regression ? "done" : "fail") : (sh.fidelity && !sh.fidelity.ok ? "skip" : "idle"),
      detail: sh.tested && `fixed: ${sh.tested.fixed} · regression: ${sh.tested.regression}${sh.tested.unintended.length ? " · " + sh.tested.unintended[0] : ""}` },
    { label: "Gate decision", st: g.decision ? (blocked ? "fail" : "done") : "idle",
      detail: g.decision && `${g.decision.decision}: ${g.decision.reason}` },
    { label: "Applied to live, verified, regression-checked",
      st: blocked ? "skip" : lv.result ? (applied ? "done" : "fail") : lv.applying ? "active" : "idle",
      detail: blocked ? `Skipped. Live network untouched: ${String(lv.untouched)}` : lv.result && `fixed: ${lv.result.fixed} · regression: ${lv.result.regression}` },
  ];
  const icon = { done: "✓", fail: "✕", skip: "–", idle: "", active: <span className="spin" /> };
  return (
    <div>
      <ul className="gate">
        {items.map((it, i) => (
          <li key={i} className={`s-${it.st}`}>
            <span className="mk">{icon[it.st]}</span>
            <div><div className="lb">{it.label}</div>{it.detail ? <div className="dt">{it.detail}</div> : null}</div>
          </li>
        ))}
      </ul>
      {blocked && <div className="verdict no">✕ Blocked by the shadow gate. The live network was never touched.</div>}
      {applied && <div className="verdict ok">✓ Fix applied and verified. No regression.</div>}
    </div>
  );
}
