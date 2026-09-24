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
  echo "  Demo:      http://demovalence.localhost:8000"
  echo "  Madhav:    http://madhav.localhost:8000"
  echo "  Fallback:  http://127.0.0.1:8000"
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

DEFAULT_SITE=$(python3 -c "import json; print(json.load(open('sites/common_site_config.json')).get('default_site') or 'demovalence.localhost')")

echo "Starting multi-site server on :8000 (Ctrl+C to stop)..."
echo "  Demo:      http://demovalence.localhost:8000"
echo "  Madhav:    http://madhav.localhost:8000"
echo "  Fallback:  http://127.0.0.1:8000  →  ${DEFAULT_SITE}"
echo "  If Safari says Can't Find the Server, add hosts:"
echo "    sudo sh -c 'printf \"\\n127.0.0.1 demovalence.localhost madhav.localhost valence.localhost\\n\" >> /etc/hosts'"
# site=None so HTTP Host selects demovalence.localhost / madhav.localhost / etc.
# 127.0.0.1 / localhost fall back to default_site (Safari often cannot resolve *.localhost).
# --noreload avoids the dev reloader dying with “apps.txt Not Found” after file changes
cd sites
exec ../env/bin/python -c "
import functools
import json
from pathlib import Path

import frappe.app
import frappe.utils

cfg = json.loads(Path('common_site_config.json').read_text())
default_site = cfg.get('default_site') or 'demovalence.localhost'
fallback_hosts = {
    '127.0.0.1', 'localhost', '0.0.0.0',
    '::1', '[::1]',
}

def get_site_name(hostname):
    name = (hostname or '').split(':', 1)[0].strip().lower()
    if name in fallback_hosts or name.startswith('192.168.') or name.startswith('10.'):
        return default_site
    return name

# Replace cached helper used by frappe.app.init_request
frappe.utils.get_site_name = get_site_name
frappe.app.get_site_name = get_site_name

frappe.app.serve(port=8000, no_reload=True, site=None, sites_path='.')
"