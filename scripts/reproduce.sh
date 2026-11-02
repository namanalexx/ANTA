#!/usr/bin/env bash
# Full reproduction. Takes several hours. Usage: scripts/reproduce.sh [--quick]
# --quick skips the ReAct baseline and the shadow-gate evaluation.
# Note: the 'anta_v1' rows (agent before the fault-type extension) are an archive and are not regenerated.
set -e
cd ~/ANTA && source .venv/bin/activate
QUICK=0; [ "${1:-}" = "--quick" ] && QUICK=1
scripts/start_lab.sh
(cd network && python3 -m tools.gate | tail -2)
python3 -m benchmark.make_scenarios
python3 -m benchmark.runner --system anta --force | tail -45
python3 -m benchmark.runner --system anta --split stress --force | tail -3
python3 -m benchmark.runner --system anta --split stress_test --force | tail -3
python3 -m benchmark.runner --system llm_only --force | tail -3
[ $QUICK -eq 0 ] && python3 -m benchmark.runner --system react --force | tail -3
python3 -m remediation.selftest
python3 -m remediation.run_eval --force
python3 -m remediation.run_eval --split stress --force
python3 -m remediation.run_eval --split stress_test --force
[ $QUICK -eq 0 ] && python3 -m remediation.run_gate_eval --split test --force
python3 -m experiments.compare
python3 -m experiments.final_report
echo "Done. Results: docs/RESULTS.md"
