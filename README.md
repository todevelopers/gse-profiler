<p align="center">
  <img src="app/data/icons/hicolor/scalable/apps/org.gnome.GSEProfiler.svg" width="128" height="128" alt="GSE Profiler">
</p>

# gse-profiler

[![CI](https://github.com/todevelopers/gse-profiler/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/todevelopers/gse-profiler/actions/workflows/ci.yml)

**GTK4 desktop application for managing, debugging, and profiling GNOME Shell extensions.**

Designed for extension developers who need deep runtime insight — live function timing,
log filtering, object inspection — without leaving the desktop.

---

## Features

| Feature               | Description                                                                                |
| --------------------- | ------------------------------------------------------------------------------------------ |
| **Extension Manager** | List all installed extensions, enable/disable, clone from GitHub, open source folder       |
| **Log Viewer**        | Live `journalctl` stream filtered by extension UUID and log level, full-text search        |
| **Profiler**          | Live function timing via monkey-patching; load and visualize saved profile files           |
| **Inspector**         | Live access to extension `stateObj` — browse properties and methods of a running JS object |

---

## Gallery
<img width="1250" height="818" alt="Screenshot From 2026-05-16 12-40-11" src="https://github.com/user-attachments/assets/084aceef-e270-46a4-8120-274e519f6cb8" />
<img width="1250" height="830" alt="Screenshot From 2026-05-16 14-39-41" src="https://github.com/user-attachments/assets/74bfa024-e534-43da-8125-f24719e3e092" />
<img width="1250" height="789" alt="Screenshot From 2026-05-17 14-36-41" src="https://github.com/user-attachments/assets/a17c4dcc-7ccd-4348-87fb-6c233a3d797d" />

---

## Quick Start

> Requires Fedora (or any GNOME 48+ distro) running inside an active GNOME session.

```bash
curl -fsSL https://raw.githubusercontent.com/todevelopers/gse-profiler/main/scripts/setup-and-run.sh | bash
```

The script checks for GTK4/libadwaita (pre-installed on any Fedora GNOME system),
clones the repository to `~/gse-profiler`, and launches the app — no `sudo`, no prompts.

On subsequent runs the same command pulls the latest changes and restarts the app.

---

## Architecture

```
GTK4 App (Python/PyGObject)
         │
         ├─ D-Bus ──────────────► org.gnome.Shell.Extensions
         │                        (list / enable / disable)
         │
         └─ Unix Socket (JSON) ──► Bridge Extension (GJS)
                                         │
                                         ├── Target extension   (monkey-patch, inspect)
                                         ├── Core gnome-shell   (optional)
                                         └── opt-in API bridge
```

The app auto-installs a **bridge GJS extension** (`gse-profiler-bridge`) into
`~/.local/share/gnome-shell/extensions/`. The bridge runs inside the `gnome-shell` process
and is responsible for monkey-patching, log interception, object inspection, and the developer
API bridge. It communicates back to the app over a Unix socket using newline-delimited JSON.

Standard GNOME Shell APIs (extension list, enable/disable) are accessed directly via D-Bus.

---

## Requirements

- GNOME 48+
- Python 3.11+
- PyGObject (GTK4 bindings)
- `git` — for cloning extensions
- `journalctl` — for the log viewer (part of `systemd`)

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/gazovic/gse-profiler.git
cd gse-profiler
```

### 2. Install Python dependencies

Via your distro package manager (recommended — avoids GTK4 binding issues with pip):

```bash
# Fedora / RHEL
sudo dnf install python3-gobject gtk4 libadwaita

# Ubuntu / Debian (24.04+)
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
```

Or with pip (requires system GTK4 libraries already installed):

```bash
pip install --user PyGObject
```

### 3. Run

```bash
python3 app/main.py
```

On first launch the app will offer to install the bridge extension and restart GNOME Shell.

---

## Bridge Extension

The bridge extension is bundled in `bridge-extension/` and **auto-installed** by the
application — no manual steps needed. After installation, GNOME Shell must be restarted:

- **Wayland** — the app will prompt you to log out and log back in
- **X11** — automatic restart via `Meta.restart()` over D-Bus

The bridge shows a small status indicator in the GNOME panel to confirm it is active.
The main app window also shows a connection indicator (connected / disconnected).

---

## opt-in Developer API

Extension developers can optionally import `api/devtools-api.js` for deeper profiling integration.
If gse-profiler is not running, all API calls silently **no-op** — your extension works normally
with zero overhead.

```javascript
import { DevToolsClient } from '/path/to/api/devtools-api.js';

const devtools = new DevToolsClient();
devtools.connect('my-extension@example.com');

devtools.mark('init-start');
// ... your initialization code ...
devtools.mark('init-end');
devtools.measure('init', 'init-start', 'init-end');

devtools.counter('network-requests', 1);
devtools.watch(myObject, ['property1', 'property2']);
```

---

## Project Structure

```
gse-profiler/
├── app/                        # GTK4 Python application
│   ├── main.py
│   ├── ui/
│   │   ├── extension_manager.py
│   │   ├── log_viewer.py
│   │   ├── profiler_view.py
│   │   └── inspector_view.py
│   ├── core/
│   │   ├── dbus_client.py      # D-Bus proxy for gnome-shell APIs
│   │   ├── socket_server.py    # Unix socket server (async)
│   │   ├── git_manager.py      # git clone / pull subprocess wrapper
│   │   └── journal_reader.py   # journalctl --follow subprocess
│   └── data/ui/                # Glade .ui files (optional)
├── bridge-extension/        # GJS GNOME Shell extension (bridge)
│   ├── extension.js
│   ├── profiler.js
│   ├── inspector.js
│   ├── socket_client.js
│   └── metadata.json
├── api/
│   └── devtools-api.js         # opt-in developer API
├── scripts/
│   └── restart-shell.sh        # handles Wayland (logout) and X11 (restart)
└── tests/                      # pytest unit tests
```

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Run linters before committing: `ruff check app/` and `eslint bridge-extension/ api/`
4. Run tests: `pytest tests/`
5. Open a pull request

---

## License

GPL-3.0 — see [LICENSE](LICENSE).
