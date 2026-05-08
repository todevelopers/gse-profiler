#!/usr/bin/env bash
# Restart GNOME Shell after bridge extension install/update.
#
# X11:     uses busctl to call Meta.restart() via org.gnome.Shell
# Wayland: uses gnome-session-quit (requires re-login)
set -euo pipefail

SESSION="${XDG_SESSION_TYPE:-unknown}"

if [[ "$SESSION" == "wayland" ]]; then
    echo "Wayland session detected — logging out to reload GNOME Shell."
    echo "Please log back in after the session ends."
    gnome-session-quit --logout --no-prompt
else
    echo "X11 session detected — restarting GNOME Shell in place."
    busctl --user call \
        org.gnome.Shell \
        /org/gnome/Shell \
        org.gnome.Shell \
        Eval s 'Meta.restart("Restarting GNOME Shell for GSE Profiler…")'
fi
