import React, { useEffect, useRef, useState } from "react";

export const NAMES = ["client", "router", "firewall", "dns-server", "web-server"];
const LINKS = [["client", "router"], ["router", "firewall"], ["firewall", "dns-server"], ["firewall", "web-server"]];
const LEVELS = [0, 0.26, 0.52, 0.78, 1];
const LOOP = 20;
const TAU = Math.PI * 2;

export function layoutFor(W) {
  if (W < 760) {
    return { client: [0.14, 0.73], router: [0.38, 0.73], firewall: [0.62, 0.73], "dns-server": [0.86, 0.64], "web-server": [0.86, 0.83] };
  }
  return { client: [0.13, 0.725], router: [0.315, 0.725], firewall: [0.5, 0.725], "dns-server": [0.69, 0.625], "web-server": [0.69, 0.825] };
}
export function nodeRadius(W, H) {
  return Math.max(24, Math.min(H * 0.058, W * 0.042));
}

const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
const hash = (a, b) => { const s = Math.sin(a * 127.1 + b * 311.7) * 43758.5453; return s - Math.floor(s); };
const mixAt = (t, on, off, dur) => smooth(on, on + dur, t) * (1 - smooth(off, off + dur, t));

// A live dot-matrix (LED halftone) rendering of the lab: shaded discs and links drawn into two tiny "field" canvases
// (healthy pose and under-investigation pose), then turned into scanline rows of quantised dots. Each half dissolves
// from one pose to the other dot by dot and back.
export default function DotHero({ running = false }) {
  const wrap = useRef(null);
  const cvs = useRef(null);
  const runRef = useRef(running);
  const [size, setSize] = useState({ W: 1440, H: 800 });

  useEffect(() => { runRef.current = running; }, [running]);

  useEffect(() => {
    const canvas = cvs.current, host = wrap.current;
    const ctx = canvas.getContext("2d");
    const mk = () => { const c = document.createElement("canvas"); return [c, c.getContext("2d", { willReadFrequently: true })]; };
    const [cA, fA] = mk();
    const [cB, fB] = mk();
    let W = 0, H = 0, cols = 0, rows = 0, step = 7, rowStep = 14, R = 3.2, DPR = 1, seeds = new Float32Array(0);
    let raf = 0;
    const t0 = performance.now();
    const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const positions = (t) => {
      const L = layoutFor(W), a = (TAU * t) / LOOP, rN = nodeRadius(W, H);
      const cx = W * 0.5, cy = H * 0.715, sc = 1 + 0.02 * Math.sin(a + 0.9);
      const P = {};
      NAMES.forEach((n, k) => {
        const x = L[n][0] * W + Math.sin(a + k * 0.9) * W * 0.0055;
        const y = L[n][1] * H + Math.sin(1.5 * a + k * 1.3) * H * 0.011;
        P[n] = [cx + (x - cx) * sc, cy + (y - cy) * sc];
      });
      return { P, rN: rN * sc };
    };

    const drawField = (fctx, kind, P, rN) => {
      fctx.setTransform(1, 0, 0, 1, 0, 0);
      fctx.fillStyle = "#fff";
      fctx.fillRect(0, 0, cols, rows);
      fctx.setTransform(cols / W, 0, 0, rows / H, 0, 0);
      fctx.lineCap = "round";
      fctx.strokeStyle = "#6a6a6a";
      fctx.lineWidth = kind === "A" ? rN * 0.2 : rN * 0.12;
      fctx.setLineDash(kind === "A" ? [] : [rN * 0.4, rN * 0.34]);
      fctx.beginPath();
      for (const [a, b] of LINKS) { fctx.moveTo(P[a][0], P[a][1]); fctx.lineTo(P[b][0], P[b][1]); }
      fctx.stroke();
      fctx.setLineDash([]);
      for (const n of NAMES) {
        const [x, y] = P[n];
        if (kind === "A") {
          const g = fctx.createRadialGradient(x - rN * 0.3, y - rN * 0.35, rN * 0.1, x, y, rN);
          g.addColorStop(0, "#cfcfcf"); g.addColorStop(0.55, "#8d8d8d"); g.addColorStop(1, "#4b4b4b");
          fctx.fillStyle = g;
          fctx.beginPath(); fctx.arc(x, y, rN, 0, TAU); fctx.fill();
        } else {
          fctx.strokeStyle = "#555"; fctx.lineWidth = rN * 0.3;
          fctx.beginPath(); fctx.arc(x, y, rN * 0.8, 0, TAU); fctx.stroke();
          fctx.fillStyle = "#888";
          fctx.beginPath(); fctx.arc(x, y, rN * 0.18, 0, TAU); fctx.fill();
        }
      }
    };

    const render = (tt) => {
      if (!cols) return;
      const t = ((tt % LOOP) + LOOP) % LOOP;
      const { P, rN } = positions(t);
      drawField(fA, "A", P, rN);
      drawField(fB, "B", P, rN);
      const dA = fA.getImageData(0, 0, cols, rows).data;
      const dB = fB.getImageData(0, 0, cols, rows).data;
      ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = "#0d0d0d";
      ctx.beginPath();
      const busy = runRef.current ? 1 : 0;
      const tick = Math.floor(t * (7 + 7 * busy));
      const mL = mixAt(t, 6.2, 14.6, 1.6), mR = mixAt(t, 2.4, 10.4, 1.6);
      for (let j = 0; j < rows; j++) {
        const y = (j + 0.5) * rowStep;
        const yFade = smooth(0.5 * H, 0.58 * H, y); // keep the copy block clear
        if (yFade <= 0) continue;
        const shift = hash(j, tick) > 0.965 ? Math.round((hash(tick, j) - 0.5) * 8) : 0;
        for (let i = 0; i < cols; i++) {
          const ii = clamp(i - shift, 0, cols - 1);
          const idx = (j * cols + ii) * 4;
          const seed = seeds[j * cols + i];
          const m = i < cols / 2 ? mL : mR;
          const lum = ((seed < m ? dB : dA)[idx]) / 255;
          let v = clamp((1 - lum - 0.16) / 0.42, 0, 1);
          if (m > 0.001 && m < 0.999) {
            const d = Math.abs(seed - m);
            if (d < 0.12) { v *= d / 0.12; if (hash(i + tick, j) <= 0.4) v *= 0.3; }
          }
          v *= 0.86 + 0.14 * Math.sin(t * 3.2 + seed * 40);
          v *= yFade;
          let level = 0;
          for (let k = LEVELS.length - 1; k >= 0; k--) { if (v >= LEVELS[k] - 0.13) { level = LEVELS[k]; break; } }
          if (level === 0) continue;
          const rad = level === LEVELS[1] ? R * 0.38 : R * level;
          const x = (i + 0.5) * step;
          ctx.moveTo(x + rad, y);
          ctx.arc(x, y, rad, 0, TAU);
        }
      }
      ctx.fill();
    };
    window.__render = render;

    const resize = () => {
      W = host.clientWidth; H = host.clientHeight;
      if (!W || !H) return;
      DPR = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.round(W * DPR); canvas.height = Math.round(H * DPR);
      step = Math.max(5, W / 205); rowStep = step * 2.05; R = step * 0.46;
      cols = Math.ceil(W / step); rows = Math.ceil(H / rowStep);
      cA.width = cB.width = cols; cA.height = cB.height = rows;
      seeds = new Float32Array(cols * rows);
      for (let j = 0; j < rows; j++) for (let i = 0; i < cols; i++) seeds[j * cols + i] = 0.55 * hash(i, j) + 0.45 * hash(j * 3.1, 7.7);
      setSize({ W, H });
      if (reduce) render(1.0);
    };

    const loop = (now) => {
      if (!document.hidden) render((now - t0) / 1000);
      raf = requestAnimationFrame(loop);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(host);
    if (!reduce) raf = requestAnimationFrame(loop);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); };
  }, []);

  const L = layoutFor(size.W), rn = nodeRadius(size.W, size.H);
  return (
    <div className="dots" ref={wrap}>
      <canvas ref={cvs} />
      {NAMES.map((n) => (
        <span key={n} className="hero-label" style={{ left: L[n][0] * size.W, top: L[n][1] * size.H + rn + 14 }}>{n}</span>
      ))}
    </div>
  );
}
