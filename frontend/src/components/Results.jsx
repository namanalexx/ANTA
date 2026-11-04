import React, { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import { Card } from "./Panels.jsx";

const NAMES = { llm_only: "LLM-only", react: "ReAct", anta: "ANTA" };
const FILL = { llm_only: "#d4d4cf", react: "#9a9a9a", anta: "#111111" };
const pct = (x) => (x == null ? "-" : `${Math.round(x * 100)}%`);
const SPLITS = { test: "Held-out test (19)", final: "Final held-out (10)" };

function Stat({ n, label }) {
  return <div className="stat"><div className="num">{n}</div><div className="lab">{label}</div></div>;
}

export default function Results() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(false);
  const [split, setSplit] = useState("test");
  const ref = useRef(null);

  const load = () => {
    setErr(false); setData(null);
    fetch("/api/results").then((r) => (r.ok ? r.json() : Promise.reject())).then(setData).catch(() => setErr(true));
  };
  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (!data || !ref.current) return;
    const rows = ["llm_only", "react", "anta"].map((k) => data.systems.find((s) => s.system === k)).filter((s) => s && s[split])
      .map((s) => ({ system: s.system, rca: s[split].rca, ci: s[split].ci, n: s[split].n }));
    const svg = d3.select(ref.current);
    svg.selectAll("*").remove();
    if (!rows.length) return;
    const W = 560, H = 300, m = { t: 30, r: 16, b: 50, l: 46 };
    const x = d3.scaleBand().domain(rows.map((r) => r.system)).range([m.l, W - m.r]).padding(0.42);
    const y = d3.scaleLinear().domain([0, 1]).range([H - m.b, m.t]);
    const ticks = [0, 0.25, 0.5, 0.75, 1];
    svg.append("g").selectAll("line").data(ticks).join("line")
      .attr("x1", m.l).attr("x2", W - m.r).attr("y1", (d) => y(d)).attr("y2", (d) => y(d))
      .attr("stroke", "#e0e0db").attr("stroke-dasharray", "1 5").attr("stroke-linecap", "round");
    svg.append("g").selectAll("text").data(ticks).join("text")
      .attr("x", m.l - 10).attr("y", (d) => y(d) + 4).attr("text-anchor", "end").attr("fill", "#9a9a9a").attr("font-size", 11).text((d) => `${d * 100}%`);
    svg.selectAll("rect.bar").data(rows).join("rect").attr("class", "bar")
      .attr("x", (r) => x(r.system)).attr("width", x.bandwidth()).attr("y", y(0)).attr("height", 0).attr("rx", 3).attr("fill", (r) => FILL[r.system])
      .transition().duration(800).attr("y", (r) => y(r.rca)).attr("height", (r) => y(0) - y(r.rca));
    const cx = (r) => x(r.system) + x.bandwidth() / 2;
    svg.selectAll("line.ci").data(rows).join("line").attr("class", "ci").attr("stroke", "#111").attr("stroke-width", 1.5)
      .attr("x1", cx).attr("x2", cx).attr("y1", (r) => y(r.ci[0])).attr("y2", (r) => y(r.ci[1]));
    svg.selectAll("line.cap").data(rows.flatMap((r) => [[r, r.ci[0]], [r, r.ci[1]]])).join("line").attr("class", "cap").attr("stroke", "#111").attr("stroke-width", 1.5)
      .attr("x1", (d) => cx(d[0]) - 6).attr("x2", (d) => cx(d[0]) + 6).attr("y1", (d) => y(d[1])).attr("y2", (d) => y(d[1]));
    svg.selectAll("text.val").data(rows).join("text").attr("class", "val").attr("text-anchor", "middle").attr("fill", "#111").attr("font-weight", 600).attr("font-size", 14)
      .attr("x", cx).attr("y", (r) => y(r.ci[1]) - 9).text((r) => pct(r.rca));
    svg.selectAll("text.lab").data(rows).join("text").attr("class", "lab").attr("text-anchor", "middle").attr("fill", "#111").attr("font-size", 12.5).attr("font-weight", 500)
      .attr("x", cx).attr("y", H - m.b + 20).text((r) => NAMES[r.system]);
    svg.selectAll("text.nn").data(rows).join("text").attr("class", "nn").attr("text-anchor", "middle").attr("fill", "#9a9a9a").attr("font-size", 11)
      .attr("x", cx).attr("y", H - m.b + 35).text((r) => `n = ${r.n}`);
  }, [data, split]);

  if (err) {
    return (
      <div className="results"><Card title="Results">
        <div className="err-box">Could not load the results. Is the backend running on port 8000?
          <button className="pill" onClick={load}>Retry</button></div>
      </Card></div>
    );
  }
  if (!data) return <div className="results"><Card title="Results"><p className="muted">Loading…</p></Card></div>;
  const g = data.gate, rem = data.remediation;
  return (
    <div className="results">
      <Card title="Root-cause accuracy (whiskers: 95% CI)" right={
        <div className="seg">{Object.entries(SPLITS).map(([k, v]) => (
          <button key={k} className={split === k ? "on" : ""} onClick={() => setSplit(k)}>{v}</button>))}</div>}>
        <svg ref={ref} viewBox="0 0 560 300" style={{ width: "100%", height: "auto" }} />
      </Card>
      <Card title="All metrics">
        <table>
          <thead><tr><th>System</th><th>Split</th><th>n</th><th>Detect</th><th>RCA</th><th>Calls</th></tr></thead>
          <tbody>
            {data.systems.flatMap((s) => ["test", "final", "all"].filter((k) => s[k]).map((k) => (
              <tr key={s.system + k}><td>{NAMES[s.system]}</td><td>{k}</td><td>{s[k].n}</td><td>{pct(s[k].detect)}</td>
                <td><b>{pct(s[k].rca)}</b></td><td>{s[k].calls == null ? "-" : s[k].calls.toFixed(1)}</td></tr>
            )))}
          </tbody>
        </table>
      </Card>
      {rem && (
        <Card title="Remediation (verified and regression-checked)">
          <div className="stats">
            <Stat n={`${rem.fixed}/${rem.faults}`} label="faults repaired and verified" />
            <Stat n={rem.regressions} label="regressions" />
            <Stat n={`${rem.wrongly_acted}/${rem.healthy_cases}`} label="actions on healthy networks" />
          </div>
        </Card>
      )}
      {g && (
        <Card title="Shadow-network gate">
          <div className="stats">
            <Stat n={`${g.correct[0]}/${g.correct[1]}`} label="correct fixes applied" />
            <Stat n={`${g.wrong[0]}/${g.wrong[1]}`} label="wrong diagnoses blocked" />
            <Stat n={`${g.unsafe[0]}/${g.unsafe[1]}`} label={`unsafe fixes blocked (ungated: ${g.ungated_harmful}/${g.unsafe[1]} caused harm)`} />
            <Stat n={`${g.fidelity[0]}/${g.fidelity[1]}`} label="shadow reproduced the live symptoms" />
          </div>
        </Card>
      )}
      {data.stress && (
        <Card title="Interface and link faults: before vs after the extension">
          <table>
            <thead><tr><th>Agent</th><th>Scenarios</th><th>Correct</th><th>Confidently wrong</th></tr></thead>
            <tbody>
              {[["v1", "Before: no hypotheses for these faults"], ["v2", "After: extended"]].filter(([k]) => data.stress[k]).map(([k, name]) => (
                <tr key={k}><td>{name}</td><td>{data.stress[k].n}</td><td><b>{data.stress[k].correct}</b></td><td>{data.stress[k].confidently_wrong}</td></tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      {data.ablations && data.ablations.length > 0 && (
        <Card title="Ablations: what carries accuracy and efficiency?">
          <table>
            <thead><tr><th>Variant</th><th>RCA</th><th>Conf. wrong</th><th>Calls</th><th>Sec</th></tr></thead>
            <tbody>
              {data.ablations.map((a) => (
                <tr key={a.variant}><td>{a.description}</td><td><b>{Math.round(a.rca * 100)}%</b></td><td>{a.confidently_wrong}</td><td>{a.calls}</td><td>{a.sec}</td></tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
