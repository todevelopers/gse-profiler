# CLAUDE.md — gse-profiler

## Project Overview

GTK4 desktop application for **managing, debugging, and profiling GNOME Shell extensions**.
Targets GNOME Shell extension developers. Internally installs a companion GJS extension that acts as a bridge into the `gnome-shell` process.

**Target platform:** GNOME 48+  
**Languages:** Python 3.11+ (app), GJS / ES6 (companion extension + developer API)

---

## Architecture

```
GTK4 App (Python/PyGObject)
         │
         ├─ D-Bus ──────────────► org.gnome.Shell.Extensions  (list / enable / disable)
         │
         └─ Unix Socket (JSON) ──► Companion Extension (GJS)
                                         │
                                         ├── Target extension   (monkey-patch, inspect)
                                         ├── Core gnome-shell   (optional)
                                         └── opt-in API bridge  (DevToolsClient)
```

Communication split:

- **D-Bus** — standard GNOME Shell APIs (extensions list, enable/disable)  
- **Unix socket** — all custom high-frequency communication with the companion

Socket path: `$XDG_RUNTIME_DIR/gse-profiler.sock`  
Protocol: newline-delimited JSON messages

---

## Directory Layout

```
gse-profiler/
├── app/                        # GTK4 Python application
│   ├── main.py
│   ├── ui/                     # UI view modules
│   │   ├── extension_manager.py
│   │   ├── log_viewer.py
│   │   ├── profiler_view.py
│   │   └── inspector_view.py
│   ├── core/                   # Core logic
│   │   ├── dbus_client.py
│   │   ├── socket_server.py
│   │   ├── git_manager.py
│   │   └── journal_reader.py
│   └── data/ui/                # Glade .ui files (if needed)
├── companion-extension/        # GJS GNOME Shell extension
│   ├── extension.js
│   ├── profiler.js
│   ├── inspector.js
│   ├── socket_client.js
│   └── metadata.json
├── api/
│   └── devtools-api.js         # opt-in developer API
├── scripts/
│   └── restart-shell.sh
└── tests/                      # pytest unit tests
```

---

## Companion Extension

- **UUID:** `gse-profiler-bridge@todevelopers`
- **Install path:** `~/.local/share/gnome-shell/extensions/gse-profiler-bridge@todevelopers/`
- Auto-installed by the app on first launch
- Shows a minimal status indicator in the GNOME panel (no menu needed in V1)
- After installation, `scripts/restart-shell.sh` is run to reload gnome-shell

### Shell Restart Logic

| Session type | Restart method                                    |
| ------------ | ------------------------------------------------- |
| X11          | `Meta.restart()` via `org.gnome.Shell Eval` D-Bus |
| Wayland      | `gnome-session-quit --logout --no-prompt`         |

---

## Coding Conventions

### Python (`app/`)

- Python 3.11+, PEP 8, type hints throughout
- Use GObject property system (`GObject.Property`) where appropriate
- D-Bus calls: use `Gio.DBusProxy` async variants — never block the main loop
- Unix socket I/O: async via `GLib.IOChannel` or `asyncio` with GLib event loop integration
- No hardcoded paths — use `GLib.get_user_data_dir()`, `GLib.get_runtime_dir()`, etc.

### GJS (`companion-extension/`, `api/`)

- ES6 module syntax (`import` / `export`), strict mode (`'use strict'`)
- Use GNOME GJS bindings (`imports.gi.*` or `gi://` depending on GNOME version)
- Always disconnect signals in `disable()` — no memory leaks
- Never use `org.gnome.Shell Eval` on Wayland — all introspection goes through the socket

### General

- All user-facing strings and identifiers in English
- No `console.log` left in production GJS code — use `log()` / `logError()`
- Profile event JSON schema: `{ type, extensionUuid, function, start, end, depth }`

---

## D-Bus Interfaces Used

| Interface                    | Purpose                         |
| ---------------------------- | ------------------------------- |
| `org.gnome.Shell.Extensions` | List extensions, enable/disable |
| `org.gnome.Shell`            | Shell eval for X11 restart      |
| `org.freedesktop.DBus`       | Introspection                   |

---

## Key Rules for the Agent

1. **Never block the GTK main loop** — all I/O must be async or run in a thread.
2. **Wayland first** — never assume X11; shell eval path is a fallback, not the default.
3. **opt-in API must be side-effect free when not connected** — all `DevToolsClient` methods must silently no-op when the companion socket is unavailable.
4. **Companion lifecycle** — always call `disable()` cleanup: disconnect signals, close socket, remove monkey-patches.
5. **Tests live in `tests/`** — use `pytest`; mock D-Bus and subprocess in unit tests.
