#!/usr/bin/env bash
# Re-verifies remediation and the shadow gate on the final code. Resumable via --force reruns only what is listed.
exec 9>/tmp/anta_final.lock
flock -n 9 || { echo "final run already in progress"; exit 1; }
cd ~/ANTA && source .venv/bin/activate
python3 -m remediation.selftest
python3 -m remediation.run_eval --force
python3 -m remediation.run_eval --split stress --force
python3 -m remediation.run_eval --split stress_test --force
python3 -m remediation.run_gate_eval --split test --force
python3 -m experiments.final_report
echo "######## FINAL RUN DONE ($(date +%H:%M:%S))"
