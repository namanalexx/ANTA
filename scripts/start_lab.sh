#!/usr/bin/env bash
# Starts the live lab and verifies it (8 checks).
cd ~/ANTA/network/topology && docker compose up -d && sleep 6
cd ~/ANTA/network && ./verify_topology.sh | tail -2
