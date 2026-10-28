import React, { useEffect, useRef } from "react";
import * as d3 from "d3";

const NODES = ["client", "router", "firewall", "dns-server", "web-server"];
const POS = { client: [90, 160], router: [270, 160], firewall: [450, 160], "dns-server": [650, 80], "web-server": [650, 240] };
const EDGES = [["client", "router"], ["router", "firewall"], ["firewall", "dns-server"], ["firewall", "web-server"]];
const SHORT = { client: "CLIENT", router: "ROUTER", firewall: "FIREWALL", "dns-server": "DNS", "web-server": "WEB" };

export function testNodes(t) {
  if (!t) return [];
  let m;
  if ((m = t.match(/^ping_client_(.+)$/))) return ["client", m[1]];
  if (t === "trace_client_web") return ["client", "router", "firewall", "web-server"];
  if (t === "dns_query") return ["client", "dns-server"];
  if ((m = t.match(/^(?:routes|fw)_(.+)$/))) return [m[1]];
  if (t === "svc_web") return ["web-server"];
  if (t === "svc_dns") return ["dns-server"];
  if ((m = t.match(/^ifaces_(.+)$/))) return [m[1]];
  if ((m = t.match(/^quality_client_(.+)$/))) return ["client", m[1]];
  if ((m = t.match(/^cap_(.+)_http$/))) return ["client", m[1]];
  return [];
}

export default function Topology({ topo, hyps, diagnosis, gate, activeTest }) {
  const ref = useRef(null);
  useEffect(() => {
    const svg = d3.select(ref.current);
    const active = new Set(testNodes(activeTest));
    const heat = (n) => {
      const c = d3.max(hyps.filter((h) => h.device === n && h.cause !== "no_fault"), (h) => h.confidence) || 0;
      return d3.interpolateRgb("#1e293b", "#ef4444")(Math.min(1, c * 1.1));
    };
    const dg = diagnosis && diagnosis.diagnosis;
    const root = dg && dg.cause !== "no_fault" ? dg.device : null;
    const healthy = dg && dg.cause === "no_fault";
    const fixed = !!(gate && gate.live && gate.live.result && gate.live.result.fixed && !gate.live.result.regression);
    const hot = (d) => active.has(d[0]) && active.has(d[1]);

    svg.selectAll("line.edge").data(EDGES, (d) => d.join("-")).join("line").attr("class", "edge")
      .attr("x1", (d) => POS[d[0]][0]).attr("y1", (d) => POS[d[0]][1])
      .attr("x2", (d) => POS[d[1]][0]).attr("y2", (d) => POS[d[1]][1])
      .attr("stroke", (d) => (hot(d) ? "#38bdf8" : "#475569")).attr("stroke-width", (d) => (hot(d) ? 4 : 2));

    const nodes = svg.selectAll("g.node").data(NODES, (d) => d).join((enter) => {
      const g = enter.append("g").attr("class", "node");
      g.append("circle").attr("r", 34).attr("fill", "#1e293b").attr("stroke", "#64748b").attr("stroke-width", 3);
      g.append("text").attr("class", "short").attr("text-anchor", "middle").attr("dy", 4);
      g.append("text").attr("class", "name").attr("text-anchor", "middle").attr("dy", 56);
      g.append("text").attr("class", "ip").attr("text-anchor", "middle").attr("dy", 70);
      g.append("text").attr("class", "tag").attr("text-anchor", "middle").attr("dy", -44);
      return g;
    });
    nodes.attr("transform", (d) => `translate(${POS[d][0]},${POS[d][1]})`).classed("active", (d) => active.has(d));
    nodes.select("circle").transition().duration(500)
      .attr("fill", (d) => heat(d))
      .attr("stroke", (d) => (fixed && d === root ? "#22c55e" : d === root ? "#fb7185" : healthy ? "#22c55e" : active.has(d) ? "#38bdf8" : "#64748b"))
      .attr("stroke-width", (d) => (d === root || active.has(d) ? 6 : 3));
    nodes.select("text.short").text((d) => SHORT[d]);
    nodes.select("text.name").text((d) => d);
    nodes.select("text.ip").text((d) => Object.values((topo && topo.ip_assignments && topo.ip_assignments[d]) || {}).join("  "));
    nodes.select("text.tag").text((d) => (fixed && d === root ? "FIXED" : d === root ? "ROOT CAUSE" : ""));
  }, [topo, hyps, diagnosis, gate, activeTest]);

  return <svg ref={ref} viewBox="0 0 760 320" className="topo" />;
}
