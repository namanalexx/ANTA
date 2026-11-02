#!/usr/bin/env bash
# Runs every ablation variant on all 51 scenarios, one variant at a time. Resumable.
# Refuses to start if another copy is running (two overlapping runs corrupt each other's faults).
exec 9>/tmp/anta_ablations.lock
flock -n 9 || { echo "another ablation run is already in progress"; exit 1; }
cd ~/ANTA && source .venv/bin/activate
for sys in anta_ranked anta_ranked_noelim anta_ranked_noprec anta_llama3b anta_random; do
  echo "######## variant: $sys  ($(date +%H:%M:%S))"
  for split in all stress stress_test; do
    python3 -m benchmark.runner --system "$sys" --split "$split"
  done
done
echo "######## ALL DONE ($(date +%H:%M:%S))"
