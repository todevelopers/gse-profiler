# PLAN.md — gse-profiler Implementation Plan

Each phase ends in a working, testable state. Phases 0–7 are **V1 scope**.
Phases 8–12 go beyond V1 with constructive additions.

---

## Phase 0: Project Setup & CI ✅

**Goal:** Skeleton that launches, CI green from day one.

### App skeleton

- [x] Directory structure per README
- [x] `app/main.py` — `Adw.Application` + `Adw.ApplicationWindow` with `Adw.OverlaySplitView`
- [x] Sidebar navigation (`Adw.OverlaySplitView` + `GtkListBox` with `navigation-sidebar` class)
- [x] Placeholder views for each section (`Adw.StatusPage` per view)
- [x] `companion-extension/metadata.json` — companion extension scaffold
- [x] `app/core/` stubs — `DBusClient`, `SocketServer`, `GitManager`, `JournalReader`
- [x] `api/devtools-api.js` — `DevToolsClient` skeleton with JSDoc
- [x] `scripts/restart-shell.sh` — X11/Wayland aware shell restart
- [x] `scripts/setup-and-run.sh` — Fedora quick-start (no sudo, no prompts)

### GitHub Actions

- [x] **`ci.yml`** — ruff · mypy · pytest · eslint on every push and PR to `main`
- [x] **`release.yml`** — tarball + changelog on `v*` tag push
- [x] **`companion-test.yml`** — ESLint on changes to `companion-extension/` or `api/`

---

## Phase 1: Extension Manager

**Goal:** Users can see all installed extensions and toggle them.

- [ ] `app/core/dbus_client.py`
  - Async `Gio.DBusProxy` wrapper for `org.gnome.Shell.Extensions`
  - Methods: `list_extensions()`, `enable_extension(uuid)`, `disable_extension(uuid)`
  - Properties per extension: name, UUID, version, state, path, error
- [ ] Extension list UI
  - `AdwPreferencesGroup` with `AdwActionRow` per extension, or `GtkListView`
  - State badge: enabled (green) / disabled (grey) / error (red)
  - Toggle switch → D-Bus call
- [ ] "Open folder" action — `Gio.AppInfo.launch_default_for_uri("file://...")`
- [ ] Refresh button + auto-refresh on D-Bus property change signal

### Companion extension bootstrap

- [ ] On app launch: check whether `gse-profiler-bridge@todevelopers` is installed
  - If not installed → copy `companion-extension/` to `~/.local/share/gnome-shell/extensions/gse-profiler-bridge@todevelopers/`
  - After copy → run `scripts/restart-shell.sh` in subprocess (prompts user on Wayland: logout required)
- [ ] After install (or if already installed but disabled) → call `enable_extension(COMPANION_UUID)` via D-Bus
- [ ] "Install / Reinstall companion" action in app menu (manual trigger)

### Connection status indicators

- [ ] App header bar chip: **Connected** (green) / **Disconnected** (grey) — reflects live Unix socket state
- [ ] GNOME panel icon in companion extension: `Gio.ThemedIcon` shown when extension is running, hidden on `disable()` (no menu in V1)

---

## Phase 2: Companion Extension + Unix Socket Transport

**Goal:** App and companion can exchange messages reliably.

### Companion extension

- [ ] `extension.js` — `enable()` / `disable()` lifecycle
- [ ] `socket_client.js` — connect to `$XDG_RUNTIME_DIR/gse-profiler.sock`, reconnect loop
- [ ] Handshake message `{ type: "hello", version: "1", uuid: COMPANION_UUID }`
- [ ] GNOME panel indicator (simple icon from `Gio.ThemedIcon`, no menu in V1)

### App side

- [ ] `app/core/socket_server.py` — async Unix socket server, `GLib.IOChannel`
- [ ] Message router — dispatch incoming JSON messages to the right subsystem
- [ ] Auto-install logic:
  - Copy `companion-extension/` to install path
  - Run `scripts/restart-shell.sh` in a subprocess
- [ ] Connection status indicator in app header bar (connected / disconnected chip)
- [ ] "Install / Reinstall companion" action in app menu
- [ ] Reinstall prompts shell restart

---

## Phase 3: Log Viewer

**Goal:** Live, filterable log stream from journalctl.

- [ ] `app/core/journal_reader.py`
  - Spawn `journalctl --follow -o json` subprocess
  - Parse JSON lines: `SYSLOG_IDENTIFIER`, `MESSAGE`, `PRIORITY`, `__REALTIME_TIMESTAMP`
  - Emit GObject signal per parsed entry
- [ ] Log Viewer UI
  - `GtkColumnView` or `GtkTextView` with monospace font
  - Auto-scroll to bottom (toggle button to lock/unlock)
- [ ] Filter bar
  - UUID dropdown (populated from Extension Manager)
  - Log level filter (DEBUG / INFO / WARNING / ERROR / CRITICAL)
  - Full-text search with match highlighting
- [ ] Toolbar actions: copy selected lines, export visible log to `.txt` file, clear

---

## Phase 4: Profiler V1

**Goal:** Live function timing for a selected extension.

### Companion side

- [ ] `companion-extension/profiler.js`
  - `startProfiling(uuid)` — monkey-patch all functions on extension's exported object
  - Record: function name, call depth, start timestamp (µs), end timestamp
  - Emit events via socket: `{ type: "profile_event", extensionUuid, function, start, end, depth }`
  - `stopProfiling()` — restore original functions

### App side

- [ ] Profiler UI
  - Start / stop profiling controls (select target extension from dropdown)
  - Call table (`GtkColumnView`): function name, call count, total ms, avg ms, max ms — sortable
  - Timeline view (simple horizontal bar chart per function, sorted by start time)
- [ ] Save profile to JSON file (`Gio.File`)
- [ ] Load profile from JSON file + same visualization
- [ ] Clear / reset profiling data

---

## Phase 5: Inspector

**Goal:** Live access to extension `stateObj` properties and methods.

### Companion side

- [ ] `companion-extension/inspector.js`
  - `inspect(uuid)` — get reference to extension's `stateObj`
  - Enumerate own properties + prototype chain (1 level)
  - Serialize: `{ name, type, value, writable }` — handle functions, circular refs, symbols
  - Respond with `{ type: "inspect_result", extensionUuid, properties: [...] }`

### App side

- [ ] Inspector UI
  - `GtkTreeView` / `GtkColumnView`: property name | type | value
  - Expand row for object/array values (1-level deep in V1)
  - Refresh button
  - Copy property path / value to clipboard
  - Inline editing for string / number / boolean properties (send `set_property` message back)

---

## Phase 6: Clone from GitHub

**Goal:** Install GNOME Shell extensions directly from a GitHub URL.

- [ ] `app/core/git_manager.py`
  - `clone(url, target_path)` — spawn `git clone`, stream output
  - `pull(path)` — spawn `git pull`, stream output
  - Read `metadata.json` after clone to extract UUID and name
- [ ] Clone dialog (`AdwDialog`)
  - Input: GitHub URL
  - Live progress display (stream git stdout)
  - After success: show extension name + UUID, offer to enable
- [ ] Extensions cloned this way get an "Update" action in Extension Manager
- [ ] Error handling: invalid URL, git not installed, network failure, UUID conflict

---

## Phase 7: opt-in Developer API

**Goal:** Extension developers can integrate for deeper profiling.

- [ ] `api/devtools-api.js` — `DevToolsClient` class
  - `connect(uuid)` — find and connect to companion socket
  - `disconnect()`
  - `mark(name)` — timestamp marker
  - `measure(name, startMark, endMark)` — range from two marks
  - `counter(name, value)` — increment custom metric
  - `watch(object, properties)` — emit event on property change
  - All methods: silent no-op when not connected (no exceptions thrown)
- [ ] Companion routes `devtools_*` message types to profiler subsystem
- [ ] App Profiler view displays API-originated events distinctly (different color)
- [ ] JSDoc comments on all public API methods
- [ ] README section: "opt-in Developer API" with copy-paste example

---

## Phase 8: Flame Graph (V2)

**Goal:** Visual call-stack flame graph for profiling data.

- [ ] Build flame graph data structure from recorded profile events (call depth + timing)
- [ ] Custom `Gtk.DrawingArea` widget rendered with Cairo
  - Horizontal axis = time, vertical axis = call depth
  - Each bar labeled with function name (clipped to fit)
  - Color coding by call depth or by extension module
- [ ] Interaction
  - Zoom: mouse wheel on time axis
  - Pan: click-drag
  - Hover tooltip: function name, total time, % of parent
  - Click to filter call table to selected function
- [ ] Export as SVG or PNG (`cairo.SVGSurface` / `cairo.ImageSurface`)

---

## Phase 9: Memory Profiling (V2)

**Goal:** Heap snapshots and allocation tracking.

- [ ] Companion: expose SpiderMonkey heap stats via GJS `System.gc()` + memory counters
- [ ] Memory timeline chart — heap size over time (`Gtk.DrawingArea` + Cairo)
- [ ] Object count table by constructor name
- [ ] Snapshot diff: compare two snapshots, highlight growth
- [ ] Leak candidates: objects that grew monotonically between snapshots

---

## Phase 10: Extension Health & Linting (V2+)

**Goal:** Automated quality checks surfaced in the UI.

- [ ] ESLint integration — run ESLint on extension source directory, show inline errors
  - Use `eslint --format=json`, parse output, display in a `GtkListBox`
- [ ] `metadata.json` validator
  - Required fields: `uuid`, `name`, `description`, `shell-version`
  - Warn on missing `url`, invalid `shell-version` range
- [ ] Shell error scanner — parse journal for uncaught JS exceptions tagged to the extension
- [ ] Performance regression detection — compare saved profiles, flag functions that regressed > 20%
- [ ] Extension health summary card in Extension Manager (green / yellow / red)

---

## Phase 11: Settings & Polish (V2+)

- [ ] `AdwPreferencesWindow`
  - Theme: follow system / force dark / force light
  - Log viewer: max lines buffer, font size
  - Socket path override (advanced)
  - Auto-connect companion on launch
- [ ] Keyboard shortcuts (`Gtk.ShortcutController`)
  - `Ctrl+R` — refresh current view
  - `Ctrl+F` — focus search/filter
  - `Ctrl+S` — save profile / log export
- [ ] Session persistence via GSettings — remember last selected extension, filter state
- [ ] i18n scaffold (gettext / `_()`) — English only initially, structure ready for translators
- [ ] Onboarding flow for first launch (companion not installed → step-by-step dialog)

---

## Phase 12: Packaging & Distribution (V2+)

- [ ] AppStream metadata (`app/data/org.gnome.GSEProfiler.appdata.xml`)
- [ ] `.desktop` entry (`gse-profiler.desktop`)
- [ ] Icon set: SVG master + rasterised 48 / 64 / 128 px PNG
- [ ] Flatpak manifest (`build-aux/org.gnome.GSEProfiler.json`)
  - PyGObject, GTK4, libadwaita as SDK extensions
  - Companion extension installed outside sandbox (`--filesystem=home`)
- [ ] RPM spec for Fedora/RHEL
- [ ] `release.yml` extended: build Flatpak bundle and attach to GitHub Release

---

## Milestone Summary

| Phase | Milestone          | Scope                      |
| ----- | ------------------ | -------------------------- |
| 0     | Skeleton + CI      | Project setup              |
| 1     | Extension Manager  | List, enable/disable       |
| 2     | Companion + Socket | App ↔ Shell IPC            |
| 3     | Log Viewer         | Live filtered logs         |
| 4     | Profiler V1        | Function timing table      |
| 5     | Inspector          | stateObj live view         |
| 6     | GitHub clone       | Install extensions         |
| 7     | opt-in API         | Developer integration      |
| 8     | Flame graph        | Visual profiling (V2)      |
| 9     | Memory profiling   | Heap analysis (V2)         |
| 10    | Health checks      | Linting + validation (V2+) |
| 11    | Settings + Polish  | UX completeness (V2+)      |
| 12    | Packaging          | Flatpak + releases (V2+)   |

---

## Implementation Notes

### Async strategy (Python)

Use `asyncio` with `gbulb` or `asyncio`'s GLib integration to bridge the GLib main loop
with `asyncio` coroutines. All socket I/O and subprocess communication should be async.
Never block with `subprocess.run()` on the main thread.

### Wayland compatibility

Avoid `org.gnome.Shell Eval` entirely for runtime introspection — it is restricted on Wayland
and may be disabled in future GNOME versions. All deep operations go through the companion socket.

### Profile event JSON schema (v1)

```json
{
  "type": "profile_event",
  "extensionUuid": "my-ext@example.com",
  "function": "MyClass.prototype.init",
  "start": 1714901234.123456,
  "end":   1714901234.456789,
  "depth": 2
}
```

### No-op pattern for devtools-api.js

```javascript
mark(name) {
    if (!this._connected) return;
    this._send({ type: 'devtools_mark', name, ts: Date.now() });
}
```
