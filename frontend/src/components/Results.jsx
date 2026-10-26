import React, { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import { Card } from "./Panels.jsx";

const NAMES = { llm_only: "LLM-only", react: "ReAct", anta: "ANTA" };
const COLORS = { llm_only: "#64748b", react: "#f59e0b", anta: "#22c55e" };
const pct = (x) => (x == null ? "-" : `${Math.round(x * 100)}%`);

export default function Results() {
  const [data, setData] = useState(null);
  const ref = useRef(null);

  useEffect(() => {
    fetch("/api/results").then((r) => r.json()).then(setData).catch(() => setData({ systems: [] }));
  }, []);

  useEffect(() => {
    if (!data || !ref.current) return;
    const rows = data.systems.filter((s) => s.test).map((s) => ({ system: s.system, rca: s.test.rca, ci: s.test.ci }));
    const svg = d3.select(ref.current);
    svg.selectAll("*").remove();
    const W = 520, H = 290, m = { t: 24, r: 20, b: 40, l: 54 };
    const x = d3.scaleBand().domain(rows.map((r) => NAMES[r.system])).range([m.l, W - m.r]).padding(0.35);
    const y = d3.scaleLinear().domain([0, 1]).range([H - m.b, m.t]);
    svg.append("g").attr("transform", `translate(0,${H - m.b})`).call(d3.axisBottom(x));
    svg.append("g").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(5).tickFormat(d3.format(".0%")));
    svg.selectAll("text").attr("fill", "#cbd5e1");
    svg.selectAll("path,line").attr("stroke", "#475569");
    svg.selectAll("rect.bar").data(rows).join("rect").attr("class", "bar")
      .attr("x", (r) => x(NAMES[r.system])).attr("width", x.bandwidth()).attr("y", y(0)).attr("height", 0)
      .attr("fill", (r) => COLORS[r.system])
      .transition().duration(800).attr("y", (r) => y(r.rca)).attr("height", (r) => y(0) - y(r.rca));
    svg.selectAll("line.ci").data(rows).join("line").attr("class", "ci").attr("stroke", "#e2e8f0").attr("stroke-width", 2)
      .attr("x1", (r) => x(NAMES[r.system]) + x.bandwidth() / 2).attr("x2", (r) => x(NAMES[r.system]) + x.bandwidth() / 2)
      .attr("y1", (r) => y(r.ci[0])).attr("y2", (r) => y(r.ci[1]));
    svg.selectAll("text.val").data(rows).join("text").attr("class", "val").attr("fill", "#f8fafc").attr("text-anchor", "middle")
      .attr("font-weight", 700).attr("x", (r) => x(NAMES[r.system]) + x.bandwidth() / 2)
      .attr("y", (r) => y(r.ci[1]) - 6).text((r) => pct(r.rca));
  }, [data]);

  if (!data) return <div className="results"><Card title="Loading">Fetching results…</Card></div>;
  const g = data.gate, rem = data.remediation;
  return (
    <div className="results">
      <Card title="Root-cause accuracy on the held-out test split (whiskers: 95% CI)">
        <svg ref={ref} viewBox="0 0 520 290" style={{ width: "100%", height: "auto" }} />
      </Card>
      <Card title="All metrics">
        <table>
          <thead><tr><th>System</th><th>Split</th><th>n</th><th>Detect</th><th>RCA</th><th>Tool calls</th></tr></thead>
          <tbody>
            {data.systems.flatMap((s) => ["test", "all"].filter((k) => s[k]).map((k) => (
              <tr key={s.system + k}><td>{NAMES[s.system]}</td><td>{k}</td><td>{s[k].n}</td><td>{pct(s[k].detect)}</td>
                <td><b>{pct(s[k].rca)}</b></td><td>{s[k].calls == null ? "-" : s[k].calls.toFixed(1)}</td></tr>
            )))}
          </tbody>
        </table>
      </Card>
      {rem && (
        <Card title="Remediation (verified, regression-checked)">
          <p>Faults fixed: <b>{rem.fixed}/{rem.faults}</b> · regressions: <b>{rem.regressions}</b> · actions taken on healthy networks: <b>{rem.wrongly_acted}/{rem.healthy_cases}</b></p>
        </Card>
      )}
      {g && (
        <Card title="Shadow gate">
          <p>Correct fixes applied: <b>{g.correct[0]}/{g.correct[1]}</b> · wrong diagnoses blocked: <b>{g.wrong[0]}/{g.wrong[1]}</b></p>
          <p>Unsafe fixes blocked: <b>{g.unsafe[0]}/{g.unsafe[1]}</b> (the same fixes without the gate caused a regression or failed: <b>{g.ungated_harmful}/{g.unsafe[1]}</b>)</p>
          <p>Shadow reproduced the live symptoms: <b>{g.fidelity[0]}/{g.fidelity[1]}</b></p>
        </Card>
      )}
    </div>
  );
}
