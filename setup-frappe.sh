#!/bin/bash
# Valence local setup for macOS (Frappe v15 + ERPNext + HRMS + this app).
# Run in Terminal.app (outside Cursor sandbox):
#   bash /Users/ajitsingh/Documents/techno/valence/setup-frappe.sh
set -euo pipefail

LOG="${HOME}/valence-setup.log"
exec > >(tee -a "$LOG") 2>&1

echo "==== Valence setup started $(date) ===="
echo "Log file: $LOG"

VALENCE_SRC="$(cd "$(dirname "$0")" && pwd)"
BENCH_PARENT="${HOME}/frappe"
BENCH_DIR="${BENCH_PARENT}/valence-bench"
SITE_NAME="valence.localhost"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"
DB_ROOT_PASSWORD="${DB_ROOT_PASSWORD:-root}"
FRAPPE_BRANCH="${FRAPPE_BRANCH:-version-15}"

export PATH="/opt/homebrew/bin:/usr/local/bin:${HOME}/.local/bin:${PATH}"
export HOMEBREW_NO_AUTO_UPDATE=1
export HOMEBREW_NO_ENV_HINTS=1
export NONINTERACTIVE=1

# ---------- helpers ----------
have() { command -v "$1" >/dev/null 2>&1; }

ensure_brew_shellenv() {
  if [ -x /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [ -x /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
}

load_nvm() {
  export NVM_DIR="${HOME}/.nvm"
  if [ -s "${NVM_DIR}/nvm.sh" ]; then
    # shellcheck disable=SC1090
    . "${NVM_DIR}/nvm.sh"
  fi
}

# ---------- 1. Xcode CLT ----------
echo "[1/9] Checking Xcode Command Line Tools..."
if ! xcode-select -p >/dev/null 2>&1; then
  echo "Installing Xcode CLT (GUI prompt may appear)..."
  xcode-select --install || true
  echo "Finish the CLT install dialog, then re-run this script."
  exit 1
fi

# ---------- 2. Homebrew ----------
echo "[2/9] Installing Homebrew if needed..."
if ! have brew; then
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
ensure_brew_shellenv
# Persist brew on PATH for zsh
if [ -x /opt/homebrew/bin/brew ] && ! grep -q 'brew shellenv' "${HOME}/.zprofile" 2>/dev/null; then
  echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> "${HOME}/.zprofile"
fi
brew --version

# ---------- 3. System packages ----------
echo "[3/9] Installing git, redis, mariadb, pkg-config, python@3.11..."
brew install git redis pkg-config python@3.11 mariadb || brew install git redis pkg-config python@3.11 mariadb@11.4

# Prefer python3.11 from brew
BREW_PREFIX="$(brew --prefix)"
export PATH="$(brew --prefix python@3.11)/bin:${PATH}"

# MariaDB charset config (required by Frappe)
MYSQL_CNF_DIR="${BREW_PREFIX}/etc/my.cnf.d"
mkdir -p "${MYSQL_CNF_DIR}"
cat > "${MYSQL_CNF_DIR}/frappe.cnf" <<'EOF'
[mysqld]
character-set-client-handshake = FALSE
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci

[mysql]
default-character-set = utf8mb4
EOF

echo "Starting redis + mariadb..."
brew services start redis
brew services start mariadb 2>/dev/null || brew services start mariadb@11.4 || true
sleep 3

# Ensure root password works for bench
if mysql -u root -e "SELECT 1" >/dev/null 2>&1; then
  mysql -u root <<SQL
ALTER USER 'root'@'localhost' IDENTIFIED BY '${DB_ROOT_PASSWORD}';
FLUSH PRIVILEGES;
SQL
elif mysql -u root -p"${DB_ROOT_PASSWORD}" -e "SELECT 1" >/dev/null 2>&1; then
  echo "MariaDB root already uses configured password."
else
  echo "WARNING: Could not connect to MariaDB as root."
  echo "Fix with: brew services restart mariadb && mysql_secure_installation"
  echo "Then re-run this script with DB_ROOT_PASSWORD set."
  exit 1
fi

# ---------- 4. Node + yarn ----------
echo "[4/9] Setting up Node 18+ and yarn..."
load_nvm
if ! have nvm && [ ! -s "${HOME}/.nvm/nvm.sh" ]; then
  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
  load_nvm
fi
load_nvm
if have nvm; then
  nvm install 18
  nvm use 18
  nvm alias default 18
else
  brew install node@18
  brew link --overwrite --force node@18 || true
fi
npm install -g yarn
echo "node=$(node -v) yarn=$(yarn -v)"

# ---------- 5. uv + bench ----------
echo "[5/9] Installing uv and frappe-bench..."
if ! have uv; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${PATH}"
fi
uv python install 3.11
uv tool install frappe-bench
export PATH="${HOME}/.local/bin:${PATH}"
bench --version

PYTHON_BIN="$(uv python find 3.11)"
echo "Using Python: ${PYTHON_BIN}"

# ---------- 6. Bench init ----------
echo "[6/9] Creating bench at ${BENCH_DIR}..."
mkdir -p "${BENCH_PARENT}"
if [ ! -d "${BENCH_DIR}/apps/frappe" ]; then
  cd "${BENCH_PARENT}"
  bench init "$(basename "${BENCH_DIR}")" \
    --frappe-branch "${FRAPPE_BRANCH}" \
    --python "${PYTHON_BIN}"
fi
cd "${BENCH_DIR}"

# ---------- 7. Apps ----------
echo "[7/9] Getting ERPNext + HRMS..."
if [ ! -d apps/erpnext ]; then
  bench get-app erpnext --branch "${FRAPPE_BRANCH}"
fi
if [ ! -d apps/hrms ]; then
  bench get-app hrms --branch "${FRAPPE_BRANCH}" || echo "HRMS get-app failed; continuing"
fi

echo "Linking valence app from ${VALENCE_SRC}..."
# Always symlink the local repo so edits apply to the running bench
if [ -e apps/valence ] && [ ! -L apps/valence ]; then
  echo "Replacing copied apps/valence with symlink to ${VALENCE_SRC}..."
  rm -rf apps/valence
fi
if [ ! -e apps/valence ]; then
  ln -sfn "${VALENCE_SRC}" apps/valence
fi
./env/bin/pip install -e apps/valence
# Ensure apps.txt lists valence
if ! grep -qx "valence" sites/apps.txt 2>/dev/null; then
  echo "valence" >> sites/apps.txt
fi

# ---------- 8. Site ----------
echo "[8/9] Creating site ${SITE_NAME}..."
if [ ! -d "sites/${SITE_NAME}" ]; then
  bench new-site "${SITE_NAME}" \
    --db-root-password "${DB_ROOT_PASSWORD}" \
    --admin-password "${ADMIN_PASSWORD}" \
    --set-default
  bench --site "${SITE_NAME}" install-app erpnext
  bench --site "${SITE_NAME}" install-app hrms || true
  bench --site "${SITE_NAME}" install-app valence
else
  echo "Site exists; ensuring apps are installed..."
  bench --site "${SITE_NAME}" install-app erpnext || true
  bench --site "${SITE_NAME}" install-app hrms || true
  bench --site "${SITE_NAME}" install-app valence || true
fi

# ---------- 9. Dev settings ----------
echo "[9/9] Enabling developer mode..."
bench use "${SITE_NAME}"
bench --site "${SITE_NAME}" set-config developer_mode 1
bench --site "${SITE_NAME}" clear-cache
bench build --app valence || true

echo ""
echo "============================================"
echo " Valence setup complete"
echo "============================================"
echo " Bench dir : ${BENCH_DIR}"
echo " Site      : ${SITE_NAME}"
echo " Login     : Administrator / ${ADMIN_PASSWORD}"
echo " DB root   : root / ${DB_ROOT_PASSWORD}"
echo " Log       : ${LOG}"
echo ""
echo " Start the stack (keep Terminal open):"
echo "   bash ${VALENCE_SRC}/start-frappe.sh"
echo ""
echo " Then open: http://127.0.0.1:8000"
echo "============================================"
