<p align="center">
  <img src="app/data/icons/hicolor/scalable/apps/org.gnome.GSEProfiler.svg" width="128" height="128" alt="GSE Profiler">
</p>

# GSE Profiler

[![CI](https://github.com/todevelopers/gse-profiler/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/todevelopers/gse-profiler/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/todevelopers/gse-profiler?cacheSeconds=0)](https://github.com/todevelopers/gse-profiler/releases/latest)
[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)
[![ko-fi](https://img.shields.io/badge/Support%20on-Ko--fi-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/tommygunx89)

**GTK4 desktop application for managing, debugging, and profiling GNOME Shell extensions.**

Designed for extension developers who need deep runtime insight — live function timing,
log filtering, object inspection — without leaving the desktop.

---

## Features

| Feature               | Description                                                                                          |
| --------------------- | ---------------------------------------------------------------------------------------------------- |
| **Extension Manager** | List all installed extensions, enable/disable, open source folder                                    |
| **Log Viewer**        | Live `journalctl` stream filtered by extension UUID and log level, full-text search                  |
| **Profiler**          | Live function timing via monkey-patching; flamegraph / swimlane / histogram views; save & load JSON |
| **Inspector**         | Live access to extension `stateObj` — browse properties and methods of a running JS object          |

---

## Gallery

<img width="1250" height="818" alt="Extension manager" src="https://github.com/user-attachments/assets/084aceef-e270-46a4-8120-274e519f6cb8" />
<img width="1250" height="830" alt="Live log viewer" src="https://github.com/user-attachments/assets/74bfa024-e534-43da-8125-f24719e3e092" />
<img width="1250" height="789" alt="Flamegraph profiler" src="https://github.com/user-attachments/assets/a17c4dcc-7ccd-4348-87fb-6c233a3d797d" />

---

## Install

> Requires GNOME Shell 46+ in an active GNOME session (X11 or Wayland).

### Option 1 — Flatpak (recommended)

Grab the `.flatpak` bundle from the
[latest release](https://github.com/todevelopers/gse-profiler/releases/latest)
and install it:

```bash
flatpak install --user gse-profiler-*.flatpak
flatpak run io.github.todevelopers.GseProfiler
```

### Option 2 — One-line source install

```bash
curl -fsSL https://raw.githubusercontent.com/todevelopers/gse-profiler/main/scripts/setup-and-run.sh | bash
```

The script checks for GTK4 / libadwaita, clones the repository to
`~/gse-profiler`, and launches the app — no `sudo`, no prompts. On
subsequent runs the same command pulls the latest changes and restarts
the app.

### Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/todevelopers/gse-profiler/main/scripts/uninstall.sh | bash
```

Removes the app, desktop entry, icon, and bridge extension. Nothing else
on your system is touched.

---

## Architecture

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/architecture-dark.svg">
    <img alt="gse-profiler architecture diagram" src="docs/architecture-light.svg" width="900">
  </picture>
</p>

The app auto-installs a **bridge GJS extension** (`gse-profiler-bridge@todevelopers`)
into `~/.local/share/gnome-shell/extensions/`. The bridge runs inside the
`gnome-shell` process and is responsible for object inspection and runtime
monkey-patching (used for profiling) of the selected extension. It
communicates with the app over a Unix socket using newline-delimited JSON.

Standard GNOME Shell APIs (extension list, enable/disable) are accessed
directly via D-Bus.

After the bridge is installed, GNOME Shell must be restarted:

- **Wayland** — the app prompts you to log out and log back in.
- **X11** — automatic restart via `Meta.restart()` over D-Bus.

The main window shows a connection indicator (connected / disconnected).

---

## Requirements

- GNOME Shell 46+ (tested up to 50)
- Python 3.11+
- GTK 4 and libadwaita 1
- PyGObject (GTK4 bindings)
- `journalctl` — for the log viewer (part of `systemd`)

---

## Manual installation (development)

### 1. Clone

```bash
git clone https://github.com/todevelopers/gse-profiler.git
cd gse-profiler
```

### 2. Install system dependencies

```bash
# Fedora / RHEL
sudo dnf install python3-gobject gtk4 libadwaita

# Ubuntu / Debian (24.04+)
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
```

### 3. Run

```bash
python3 -m app.main
```

On first launch the app will offer to install the bridge extension and
restart GNOME Shell.

---

## Project Structure

```
gse-profiler/
├── app/                        # GTK4 Python application
│   ├── main.py
│   ├── ui/
│   │   ├── extension_manager.py
│   │   ├── extension_list.py
│   │   ├── details_view.py
│   │   ├── log_viewer.py
│   │   ├── profiler_view.py
│   │   ├── profiler/           # flamegraph, swimlane, histogram widgets
│   │   └── inspector_view.py
│   └── core/
│       ├── dbus_client.py      # D-Bus proxy for gnome-shell APIs
│       ├── socket_server.py    # Unix socket server (async)
│       ├── bridge_manager.py   # bridge install / update / hash check
│       └── journal_reader.py   # journalctl --follow subprocess
├── bridge-extension/           # GJS GNOME Shell extension
│   ├── extension.js
│   ├── profiler.js
│   ├── inspector.js
│   ├── socket_client.js
│   └── metadata.json
├── build-aux/                  # Flatpak manifest and launcher
├── data/                       # .desktop, AppStream metainfo, icons
├── docs/                       # architecture diagrams
├── scripts/                    # setup / uninstall / shell-restart
└── tests/                      # pytest unit tests
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide — development setup,
local checks, scripts, and CI/release automation.

---

## Support

If GSE Profiler saves you time, consider supporting development on
[Ko-fi](https://ko-fi.com/tommygunx89) — every coffee helps keep the
project moving.

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/tommygunx89)

---

## License

GPL-3.0-or-later — see [LICENSE](LICENSE).
