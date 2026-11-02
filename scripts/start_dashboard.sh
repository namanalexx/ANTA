#!/usr/bin/env bash
# Starts the dashboard backend (port 8000) and frontend (port 5173). Ctrl+C stops both.
cd ~/ANTA && source .venv/bin/activate
export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
trap 'kill 0' EXIT
uvicorn backend.api:app --port 8000 &
(cd frontend && npm run dev) &
wait
