#!/bin/bash
# Start local Frappe/ERPNext for Valence. Keep this terminal open.
#   bash /Users/ajitsingh/Documents/techno/valence/start-frappe.sh
set -euo pipefail

BENCH_DIR="${HOME}/frappe/valence-bench"
export PATH="${HOME}/micromamba/envs/valence/bin:${HOME}/micromamba/bin:${HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:${PATH}"

if [ ! -d "${BENCH_DIR}" ]; then
  echo "Bench not found at ${BENCH_DIR}. Run setup-frappe.sh first."
  exit 1
fi
cd "${BENCH_DIR}"

if ! command -v redis-server >/dev/null 2>&1; then
  echo "redis-server not found. Install redis or activate micromamba env 'valence'."
  exit 1
fi
if ! command -v bench >/dev/null 2>&1; then
  echo "bench not found on PATH (expected ${HOME}/.local/bin/bench)."
  exit 1
fi

# Cache / queue redis used by this bench (ports from config/)
redis-cli -p 13000 ping >/dev/null 2>&1 || redis-server config/redis_cache.conf --daemonize yes
redis-cli -p 11000 ping >/dev/null 2>&1 || redis-server config/redis_queue.conf --daemonize yes

if lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Already listening on :8000 — open http://127.0.0.1:8000"
  exit 0
fi

echo "Starting web server on http://127.0.0.1:8000 (Ctrl+C to stop)..."
# --noreload avoids the dev reloader dying with “apps.txt Not Found” after file changes
exec bench serve --port 8000 --noreload
