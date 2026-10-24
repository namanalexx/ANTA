"""Compare systems on the benchmark. Usage (from ~/ANTA, venv active): python3 -m experiments.compare"""
from __future__ import annotations

import csv

from benchmark import ROOT
from benchmark.evaluator import _agg, connect

ORDER = ["llm_only", "react", "anta"]


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return (c - m) / d, (c + m) / d


def main() -> None:
    con = connect()
    rows = [dict(r) for r in con.execute("SELECT * FROM runs")]
    systems = [s for s in ORDER if any(r["system"] == s for r in rows)]
    csv_rows = []
    for label, pick in (("TEST (headline)", lambda r: r["split"] == "test"),
                        ("DEV (tuned on)", lambda r: r["split"] == "dev"),
                        ("ALL 35", lambda r: True)):
        print(f"\n=== {label} ===")
        print(f"  {'system':10s} {'n':>3s} {'detect':>7s} {'RCA':>5s} {'95% CI':>13s} {'device':>7s} {'layer':>6s} "
              f"{'evid':>5s} {'calls':>6s} {'sec':>6s}")
        for s in systems:
            sub = [r for r in rows if r["system"] == s and pick(r)]
            if not sub:
                continue
            a = _agg(sub)
            k = sum(r["rca_ok"] for r in sub)
            lo, hi = wilson(k, len(sub))
            print(f"  {s:10s} {a['n']:3d} {a['detect']:7.0%} {a['rca']:5.0%} {f'{lo:.0%}-{hi:.0%}':>13s} "
                  f"{a['device']:7.0%} {a['layer']:6.0%} {a['evid']:5.0%} {a['calls']:6.1f} {a['sec']:6.1f}")
            csv_rows.append({"slice": label, "system": s, **{k2: round(v, 4) for k2, v in a.items()},
                             "rca_ci_lo": round(lo, 4), "rca_ci_hi": round(hi, 4)})

    print("\n=== RCA BY TIER (test split) ===")
    tiers = sorted({r["tier"] for r in rows if r["split"] == "test"})
    print(f"  {'tier':12s} " + " ".join(f"{s:>9s}" for s in systems))
    for t in tiers:
        cells = []
        for s in systems:
            sub = [r for r in rows if r["system"] == s and r["split"] == "test" and r["tier"] == t]
            cells.append(f"{_agg(sub)['rca']:9.0%}" if sub else f"{'-':>9s}")
        print(f"  {t:12s} " + " ".join(cells))

    print("\n=== PER SCENARIO (test split): OK / predicted when wrong ===")
    ids = sorted({r["scenario_id"] for r in rows if r["split"] == "test"})
    print(f"  {'id':4s} {'truth':28s} " + " ".join(f"{s:>26s}" for s in systems))
    for sid in ids:
        first = next(r for r in rows if r["scenario_id"] == sid)
        cells = []
        for s in systems:
            r = next((x for x in rows if x["scenario_id"] == sid and x["system"] == s), None)
            if r is None:
                cells.append(f"{'-':>26s}")
            else:
                cells.append(f"{'OK' if r['rca_ok'] else str(r['pred_cause']) + '@' + str(r['pred_device']):>26s}")
        print(f"  {sid:4s} {first['truth_cause'] + '@' + first['truth_device']:28s} " + " ".join(cells))

    out = ROOT / "experiments" / "results" / "comparison.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    if csv_rows:
        with out.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(csv_rows[0]))
            w.writeheader()
            w.writerows(csv_rows)
        print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
