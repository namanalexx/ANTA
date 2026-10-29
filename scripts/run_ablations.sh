#!/usr/bin/env bash
# Runs every ablation variant on all 51 scenarios. Resumable: finished runs are skipped.
cd ~/ANTA && source .venv/bin/activate
for sys in anta_ranked anta_random anta_ranked_noelim anta_ranked_noprec anta_llama3b; do
  echo "######## variant: $sys  ($(date +%H:%M:%S))"
  for split in all stress stress_test; do
    python3 -m benchmark.runner --system "$sys" --split "$split"
  done
done
echo "######## ALL DONE ($(date +%H:%M:%S))"
