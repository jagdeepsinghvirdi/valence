# Valence

Custom [Frappe](https://frappeframework.com) / ERPNext app for Valence Lab.

Requires **Frappe v15+**, **ERPNext**, and **HRMS** (for Attendance). This app cannot run on its own — it must be installed on a Frappe bench.

---

## Prerequisites

| Requirement | Notes |
| --- | --- |
| macOS (or Linux with equivalent packages) | Setup script is macOS-oriented |
| Xcode Command Line Tools | macOS only |
| Homebrew | For system packages |
| Python **3.11** | Managed via `uv` or Homebrew |
| Node **18+** and Yarn | Via nvm or Homebrew |
| Redis + MariaDB | Required by Frappe |
| [uv](https://github.com/astral-sh/uv) + `frappe-bench` | Bench CLI |

---

## Quick setup (recommended)

Helpers live in this repo:

| Script | Purpose |
| --- | --- |
| `setup-frappe.sh` | Install dependencies, create bench/site, install apps |
| `start-frappe.sh` | Start the web server on port 8000 |
| `RUN-SETUP.command` | Double-clickable macOS wrapper for full setup |

### 1. Clone the repo

```bash
git clone <this-repo-url> valence
cd valence
```

### 2. Run setup

Use **Terminal.app** (not a restricted/sandbox terminal). Homebrew/sudo prompts need a normal shell.

```bash
bash ./setup-frappe.sh
```

Or double-click `RUN-SETUP.command` in Finder.

**Optional env vars** before running setup:

| Variable | Default | Meaning |
| --- | --- | --- |
| `ADMIN_PASSWORD` | `admin` | Desk Administrator password |
| `DB_ROOT_PASSWORD` | `root` | MariaDB root password |
| `FRAPPE_BRANCH` | `version-15` | Frappe / ERPNext / HRMS branch |

Example:

```bash
ADMIN_PASSWORD='your-password' DB_ROOT_PASSWORD='your-db-pass' bash ./setup-frappe.sh
```

What the script does:

1. Installs Xcode CLT / Homebrew / system packages (git, redis, MariaDB, Python 3.11)
2. Sets up Node 18 + Yarn (via nvm)
3. Installs `uv` + `frappe-bench`
4. Creates bench at `~/frappe/valence-bench`
5. Fetches **ERPNext** + **HRMS** (`version-15`)
6. Symlinks this repo as the `valence` app
7. Creates site `valence.localhost` and installs erpnext, hrms, valence
8. Enables developer mode and builds the app

Setup log: `~/valence-setup.log`

Typical first-time run: **20–40 minutes**.

### 3. Start the server

```bash
bash ./start-frappe.sh
```

Leave that terminal window open. Then open:

**http://127.0.0.1:8000**

| | |
| --- | --- |
| User | `Administrator` |
| Password | `admin` (or value of `ADMIN_PASSWORD`) |

---

## Manual setup

If you prefer not to use the script:

### 1. System packages (macOS)

```bash
# Xcode CLT (if missing)
xcode-select --install

# Homebrew packages
brew install git redis pkg-config python@3.11 mariadb

# MariaDB utf8mb4 config (Frappe requirement)
# Add character-set-server = utf8mb4 etc. under [mysqld]
brew services start redis
brew services start mariadb
```

### 2. Node + Yarn

```bash
# Via nvm (recommended)
nvm install 18 && nvm use 18
npm install -g yarn
```

### 3. Bench

```bash
# Install uv + bench
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.11
uv tool install frappe-bench

# Init bench
mkdir -p ~/frappe && cd ~/frappe
bench init valence-bench --frappe-branch version-15 --python "$(uv python find 3.11)"
cd ~/frappe/valence-bench
```

### 4. Apps + site

```bash
# Dependencies
bench get-app erpnext --branch version-15
bench get-app hrms --branch version-15

# Link local valence app (from clone path)
bench get-app /path/to/valence
# Or symlink:
# ln -sfn /path/to/valence apps/valence
# ./env/bin/pip install -e apps/valence
# echo valence >> sites/apps.txt

# Site
bench new-site valence.localhost \
  --db-root-password root \
  --admin-password admin \
  --set-default

bench --site valence.localhost install-app erpnext
bench --site valence.localhost install-app hrms
bench --site valence.localhost install-app valence

bench --site valence.localhost set-config developer_mode 1
bench --site valence.localhost clear-cache
bench build --app valence
```

### 5. Run

```bash
cd ~/frappe/valence-bench
bench serve --port 8000 --noreload
# or: bench start
```

---

## Day-to-day development

| Task | Command |
| --- | --- |
| Start server | `bash /path/to/valence/start-frappe.sh` |
| Clear cache | `cd ~/frappe/valence-bench && bench --site valence.localhost clear-cache` |
| Rebuild JS assets | `bench build --app valence` |
| Migrate after app changes | `bench --site valence.localhost migrate` |
| Install / update app on site | `bench --site valence.localhost install-app valence` |

The setup script **symlinks** this repo into `apps/valence`, so edits in the clone apply to the running bench.

Bench location: `~/frappe/valence-bench`  
Default site: `valence.localhost`

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| Safari/browser can’t connect | Server not running — re-run `start-frappe.sh` and keep the terminal open |
| `redis-server` not found | Install Redis (`brew install redis`) or ensure it is on `PATH` |
| `bench` not found | Ensure `~/.local/bin` is on `PATH` (`uv tool install frappe-bench`) |
| MariaDB root connection fails | `brew services restart mariadb`, set password, re-run setup with `DB_ROOT_PASSWORD` |
| Setup fails mid-way | Check `~/valence-setup.log`, fix the error, re-run `setup-frappe.sh` (it is mostly idempotent) |
| Port 8000 already in use | Something is already listening — open http://127.0.0.1:8000 or free the port |

---

## Notes

- **HRMS** is needed for Attendance-related features.
- `hooks.py` may reference a private **chemical** app whitelist method. Install that app on the bench only if you need that code path.
- License: **MIT**
