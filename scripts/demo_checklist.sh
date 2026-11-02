#!/usr/bin/env bash
# Pre-demo health check. Run it 10 minutes before presenting.
cd ~/ANTA && source .venv/bin/activate
ok()  { echo "  [ok]   $1"; }
bad() { echo "  [FAIL] $1"; }
echo "ANTA pre-demo checklist"
curl -s --max-time 5 http://localhost:11434 | grep -q "Ollama is running" && ok "Ollama reachable" || bad "Ollama not reachable: start the Ollama app on Windows"
docker info >/dev/null 2>&1 && ok "Docker engine running" || bad "Docker engine not running: start Docker Desktop"
for c in client router firewall dns-server web-server; do
  docker ps --format '{{.Names}}' | grep -qx "$c" && ok "container $c" || bad "container $c not running: scripts/start_lab.sh"
done
(cd network && ./verify_topology.sh | tail -1 | grep -q " 0 failed") && ok "lab verifies 8/8" || bad "lab verification failed: scripts/start_lab.sh"
python3 - <<'PY'
from agent import llm
import time
t = time.time()
try:
    llm.chat_json("Reply with JSON only.", '{"ok": true}')
    print(f"  [ok]   LLM answered in {time.time() - t:.1f}s (model {llm.MODEL})")
except Exception as e:
    print("  [FAIL] LLM call failed:", e)
PY
echo "Next: scripts/start_dashboard.sh, then open http://localhost:5173"
