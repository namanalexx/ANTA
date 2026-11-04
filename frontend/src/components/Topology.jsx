import React, { useEffect, useRef } from "react";
import * as d3 from "d3";

const NODES = ["client", "router", "firewall", "dns-server", "web-server"];
const POS = { client: [90, 160], router: [270, 160], firewall: [450, 160], "dns-server": [650, 80], "web-server": [650, 240] };
const EDGES = [["client", "router"], ["router", "firewall"], ["firewall", "dns-server"], ["firewall", "web-server"]];
const LEVELS = [0, 0.26, 0.52, 0.78, 1];
const RN = 34;

export function testNodes(t) {
  if (!t) return [];
  let m;
  if ((m = t.match(/^ping_client_(.+)$/))) return ["client", m[1]];
  if (t === "trace_client_web") return ["client", "router", "firewall", "web-server"];
  if (t === "dns_query") return ["client", "dns-server"];
  if ((m = t.match(/^(?:routes|fw)_(.+)$/))) return [m[1]];
  if (t === "svc_web") return ["web-server"];
  if (t === "svc_dns") return ["dns-server"];
  if ((m = t.match(/^cap_(.+)_http$/))) return ["client", m[1]];
  if ((m = t.match(/^ifaces_(.+)$/))) return [m[1]];
  if ((m = t.match(/^quality_client_(.+)$/))) return ["client", m[1]];
  return [];
}

// hex grid of dot positions inside a node disc
const DOTS = (() => {
  const out = [], s = 8.4;
  for (let row = -4; row <= 4; row++) {
    for (let col = -4; col <= 4; col++) {
      const x = col * s + (Math.abs(row) % 2 ? s / 2 : 0), y = row * s * 0.87;
      if (Math.hypot(x, y) <= RN - 6) out.push([x, y]);
    }
  }
  return out;
})();
const quant = (v) => { for (let k = LEVELS.length - 1; k >= 0; k--) if (v >= LEVELS[k] - 0.13) return LEVELS[k]; return 0; };
const dotR = (l) => (l === 0 ? 0.9 : l === 0.26 ? 1.5 : 1.5 + 2.4 * l);

export default function Topology({ topo, hyps, diagnosis, gate, activeTest }) {
  const ref = useRef(null);
  useEffect(() => {
    const svg = d3.select(ref.current);
    const active = new Set(testNodes(activeTest));
    const dg = diagnosis && diagnosis.diagnosis;
    const root = dg && dg.cause !== "no_fault" ? dg.device : null;
    const fixed = !!(gate && gate.live && gate.live.result && gate.live.result.fixed && !gate.live.result.regression);
    const heat = (n) => (fixed ? 0 : d3.max(hyps.filter((h) => h.device === n && h.cause !== "no_fault"), (h) => h.confidence) || 0);
    const hot = (d) => active.has(d[0]) && active.has(d[1]);

    svg.selectAll("line.edge").data(EDGES, (d) => d.join("-")).join("line").attr("class", (d) => "edge" + (hot(d) ? " hot" : ""))
      .attr("x1", (d) => POS[d[0]][0]).attr("y1", (d) => POS[d[0]][1]).attr("x2", (d) => POS[d[1]][0]).attr("y2", (d) => POS[d[1]][1]);

    const nodes = svg.selectAll("g.node").data(NODES, (d) => d).join((enter) => {
      const g = enter.append("g").attr("class", "node");
      g.append("circle").attr("class", "pulse").attr("r", RN);
      g.append("circle").attr("class", "ring").attr("r", RN);
      g.append("g").attr("class", "dots").selectAll("circle").data(DOTS).join("circle")
        .attr("cx", (d) => d[0]).attr("cy", (d) => d[1]).attr("r", 0.9).attr("fill", "#111");
      g.append("text").attr("class", "name").attr("text-anchor", "middle").attr("dy", RN + 20);
      g.append("text").attr("class", "ip").attr("text-anchor", "middle").attr("dy", RN + 34);
      g.append("text").attr("class", "tag").attr("text-anchor", "middle").attr("dy", -RN - 10);
      return g;
    });
    nodes.attr("transform", (d) => `translate(${POS[d][0]},${POS[d][1]})`)
      .classed("active", (d) => active.has(d)).classed("root", (d) => d === root);
    nodes.select("g.dots").selectAll("circle").transition().duration(500).attr("r", function () {
      const name = d3.select(this.parentNode.parentNode).datum();
      return dotR(quant(heat(name)));
    });
    nodes.select("text.name").text((d) => d);
    nodes.select("text.ip").text((d) => Object.values((topo && topo.ip_assignments && topo.ip_assignments[d]) || {}).join("  "));
    nodes.select("text.tag").text((d) => (fixed && d === root ? "FIXED" : d === root ? "ROOT CAUSE" : ""));
  }, [topo, hyps, diagnosis, gate, activeTest]);

  return <svg ref={ref} viewBox="0 0 760 320" className="topo" />;
}
