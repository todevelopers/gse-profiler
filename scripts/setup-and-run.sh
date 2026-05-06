#!/usr/bin/env bash
# GSE Profiler — quick-start script for Fedora (including Hyper-V VMs).
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/gazovic/gse-profiler/main/scripts/setup-and-run.sh | bash
#   — or —
#   git clone https://github.com/gazovic/gse-profiler.git && bash gse-profiler/scripts/setup-and-run.sh
#
# The script clones (or updates) the repository, installs dependencies, and
# starts the GTK4 application.  Run it from inside an active GNOME session —
# not from SSH without a display.
set -euo pipefail

REPO_URL="https://github.com/gazovic/gse-profiler.git"
INSTALL_DIR="${GSE_PROFILER_DIR:-$HOME/gse-profiler}"

# ── Helpers ────────────────────────────────────────────────────────────────────
info()    { echo -e "\033[1;34m[gse-profiler]\033[0m $*"; }
success() { echo -e "\033[1;32m[gse-profiler]\033[0m $*"; }
warn()    { echo -e "\033[1;33m[gse-profiler]\033[0m $*"; }
die()     { echo -e "\033[1;31m[gse-profiler] ERROR:\033[0m $*" >&2; exit 1; }

# ── Pre-flight checks ──────────────────────────────────────────────────────────
if [[ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    die "No display found. Run this script inside a GNOME session, not over bare SSH."
fi

if [[ -z "${XDG_SESSION_DESKTOP:-}" ]] && [[ -z "${GNOME_SHELL_SESSION_MODE:-}" ]]; then
    warn "GNOME session not detected (\$XDG_SESSION_DESKTOP is unset)."
    warn "The app requires a running GNOME session for D-Bus communication."
    warn "Continuing anyway — you can still explore the UI."
fi

# ── Install system dependencies ────────────────────────────────────────────────
info "Installing system dependencies (requires sudo)…"

if command -v dnf &>/dev/null; then
    sudo dnf install -y \
        git \
        python3-gobject \
        gtk4 \
        libadwaita
elif command -v apt-get &>/dev/null; then
    sudo apt-get install -y \
        git \
        python3-gi \
        gir1.2-gtk-4.0 \
        gir1.2-adw-1
else
    warn "Unknown package manager — skipping automatic dependency install."
    warn "Ensure the following are installed: git, PyGObject, GTK4, libadwaita."
fi

success "Dependencies OK."

# ── Clone or update repository ─────────────────────────────────────────────────
if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Updating existing installation at $INSTALL_DIR…"
    git -C "$INSTALL_DIR" pull --ff-only
else
    info "Cloning repository to $INSTALL_DIR…"
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

success "Repository is up to date."

# ── Launch ─────────────────────────────────────────────────────────────────────
info "Starting GSE Profiler…"
cd "$INSTALL_DIR"
exec python3 app/main.py
