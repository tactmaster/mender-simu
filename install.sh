#!/usr/bin/env bash
# install.sh — Install or uninstall the Mender Fleet Simulator as a systemd service.
#
# Usage:
#   sudo ./install.sh              # install / update
#   sudo ./install.sh --uninstall  # remove everything

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
INSTALL_DIR="/opt/mender-simulator"
DATA_DIR="$INSTALL_DIR/data"
CONFIG_DIR="$INSTALL_DIR/config"
VENV_DIR="$INSTALL_DIR/venv"
LOG_DIR="/var/log/mender-simulator"
SERVICE_USER="mender-simulator"
SERVICE_FILE="/etc/systemd/system/mender-simulator.service"
PYTHON="${PYTHON:-python3}"

# ── Helpers ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[install]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}   $*"; }
error() { echo -e "${RED}[error]${NC}  $*" >&2; exit 1; }

# ── Checks ────────────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || error "Must be run as root: sudo $0 $*"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Uninstall ─────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--uninstall" ]]; then
    info "Stopping and disabling service..."
    systemctl stop mender-simulator 2>/dev/null || true
    systemctl disable mender-simulator 2>/dev/null || true

    info "Removing service file..."
    rm -f "$SERVICE_FILE"
    systemctl daemon-reload

    info "Removing installation directory..."
    rm -rf "$INSTALL_DIR"

    info "Removing log directory..."
    rm -rf "$LOG_DIR"

    if id "$SERVICE_USER" &>/dev/null; then
        info "Removing service user..."
        userdel "$SERVICE_USER" 2>/dev/null || true
    fi

    info "Uninstall complete."
    exit 0
fi

# ── Python version check ──────────────────────────────────────────────────────
PY_VERSION=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
if [[ $PY_MAJOR -lt 3 || ($PY_MAJOR -eq 3 && $PY_MINOR -lt 9) ]]; then
    error "Python 3.9+ required (found $PY_VERSION). Set PYTHON=/path/to/python3.9 and retry."
fi
info "Using Python $PY_VERSION ($($PYTHON -c 'import sys; print(sys.executable)'))"

# ── Service user ──────────────────────────────────────────────────────────────
if ! id "$SERVICE_USER" &>/dev/null; then
    info "Creating system user '$SERVICE_USER'..."
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
else
    info "User '$SERVICE_USER' already exists."
fi

# ── Directories ───────────────────────────────────────────────────────────────
info "Creating directories..."
mkdir -p "$DATA_DIR" "$CONFIG_DIR" "$LOG_DIR"

# ── Install package into venv ─────────────────────────────────────────────────
if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtual environment..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

info "Installing package..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet "$SCRIPT_DIR"

# ── Config ────────────────────────────────────────────────────────────────────
PROD_CONFIG="$CONFIG_DIR/config.yaml"
if [[ -f "$PROD_CONFIG" ]]; then
    warn "Config already exists at $PROD_CONFIG — not overwriting."
    warn "Edit it manually if you need to change tokens or device counts."
else
    info "Installing default config to $PROD_CONFIG..."
    cp "$SCRIPT_DIR/config/config.yaml" "$PROD_CONFIG"

    # Rewrite paths to absolute production values
    sed -i \
        -e 's|log_file:.*|log_file: "/var/log/mender-simulator/simulator.log"|' \
        -e 's|database_path:.*|database_path: "/opt/mender-simulator/data/devices.db"|' \
        "$PROD_CONFIG"

    warn "──────────────────────────────────────────────────────────"
    warn "ACTION REQUIRED: Edit $PROD_CONFIG"
    warn "  • Set server.tenant_token"
    warn "  • Set server.personal_access_token  (for preauthorization)"
    warn "──────────────────────────────────────────────────────────"
fi

# ── Permissions ───────────────────────────────────────────────────────────────
info "Setting permissions..."
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR" "$LOG_DIR"
chmod 750 "$DATA_DIR" "$LOG_DIR"
chmod 640 "$PROD_CONFIG"   # config may contain tokens

# ── Systemd service ───────────────────────────────────────────────────────────
info "Installing systemd service..."
cp "$SCRIPT_DIR/mender-simulator.service" "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable mender-simulator

# Only start if config looks ready (tokens filled in)
if grep -q 'YOUR_TENANT_TOKEN_HERE\|tenant_token: ""' "$PROD_CONFIG" 2>/dev/null; then
    warn "Service installed but NOT started — edit $PROD_CONFIG first, then run:"
    warn "  sudo systemctl start mender-simulator"
else
    info "Starting service..."
    systemctl restart mender-simulator
    sleep 2
    systemctl status mender-simulator --no-pager -l || true
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo
info "Installation complete."
echo "  Config  : $PROD_CONFIG"
echo "  Data    : $DATA_DIR"
echo "  Logs    : journalctl -u mender-simulator -f"
echo "            tail -f $LOG_DIR/simulator.log"
echo "  Manage  : sudo systemctl {start|stop|restart|status} mender-simulator"
echo "  Remove  : sudo $0 --uninstall"
