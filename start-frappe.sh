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
  echo "Already listening on :8000"
  echo "  Demo:   http://demovalence.localhost:8000"
  echo "  Madhav: http://madhav.localhost:8000"
  exit 0
fi

# Ensure Host-based multi-site routing (bench serve --site locks to one site)
python3 - <<'PY'
import json
from pathlib import Path
p = Path("sites/common_site_config.json")
cfg = json.loads(p.read_text())
if not cfg.get("dns_multitenant"):
    cfg["dns_multitenant"] = True
    p.write_text(json.dumps(cfg, indent=1) + "\n")
    print("Enabled dns_multitenant in common_site_config.json")
PY

echo "Starting multi-site server on :8000 (Ctrl+C to stop)..."
echo "  Demo:   http://demovalence.localhost:8000"
echo "  Madhav: http://madhav.localhost:8000"
echo "  (Use site hostname — plain 127.0.0.1 will not pick a site.)"
# site=None so HTTP Host selects demovalence.localhost / madhav.localhost / etc.
# --noreload avoids the dev reloader dying with “apps.txt Not Found” after file changes
cd sites
exec ../env/bin/python -c "
from frappe.app import serve
serve(port=8000, no_reload=True, site=None, sites_path='.')
"