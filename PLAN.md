# PLAN.md — gse-profiler Implementation Plan

Each phase ends in a working, testable state. **Phases 0–5 are V1 scope** — the app is feature-complete; remaining work is polish and release preparation.
Phases 6–11 go beyond V1 with constructive additions.

---

## Phase 0: Project Setup & CI ✅

**Goal:** Skeleton that launches, CI green from day one.

### App skeleton

- [x] Directory structure per README
- [x] `app/main.py` — `Adw.Application` + `Adw.ApplicationWindow` with `Adw.OverlaySplitView`
- [x] Sidebar navigation (`Adw.OverlaySplitView` + `GtkListBox` with `navigation-sidebar` class)
- [x] Placeholder views for each section (`Adw.StatusPage` per view)
- [x] `bridge-extension/metadata.json` — Bridge extension scaffold
- [x] `app/core/` stubs — `DBusClient`, `SocketServer`, `GitManager`, `JournalReader`
- [x] `api/devtools-api.js` — `DevToolsClient` skeleton with JSDoc
- [x] `scripts/restart-shell.sh` — X11/Wayland aware shell restart
- [x] `scripts/setup-and-run.sh` — Fedora quick-start (no sudo, no prompts)

### GitHub Actions

- [x] **`ci.yml`** — ruff · mypy · pytest · eslint on every push and PR to `main`
- [x] **`release.yml`** — tarball + changelog on `v*` tag push
- [x] **`bridge-test.yml`** — ESLint on changes to `bridge-extension/` or `api/`

---

## Phase 1: Extension Manager ✅

**Goal:** Users can see all installed extensions and toggle them.

- [x] `app/core/dbus_client.py`
  - Async `Gio.DBusProxy` wrapper for `org.gnome.Shell.Extensions`
  - Methods: `list_extensions()`, `enable_extension(uuid)`, `disable_extension(uuid)`
  - Properties per extension: name, UUID, version, state, path, error
- [x] Extension list UI
  - `AdwPreferencesGroup` with `AdwActionRow` per extension, or `GtkListView`
  - State badge: enabled (green) / disabled (grey) / error (red)
  - Toggle switch → D-Bus call
- [x] "Open folder" action — `Gio.AppInfo.launch_default_for_uri("file://...")`
- [x] Refresh button + auto-refresh on D-Bus property change signal

### Bridge extension bootstrap

- [x] On app launch: check whether `gse-profiler-bridge@todevelopers` is installed
  - If not installed → copy `bridge-extension/` to `~/.local/share/gnome-shell/extensions/gse-profiler-bridge@todevelopers/`
  - After copy → run `scripts/restart-shell.sh` in subprocess (prompts user on Wayland: logout required)
- [x] After install (or if already installed but disabled) → call `enable_extension(BRIDGE_UUID)` via D-Bus
- [x] "Install / Reinstall bridge" action in app menu (manual trigger)

### Connection status indicators

- [x] App header bar chip: **Connected** (green) / **Disconnected** (grey) — reflects live Unix socket state
- [x] GNOME panel icon in Bridge extension: `Gio.ThemedIcon` shown when extension is running, hidden on `disable()` (no menu in V1)

---

## Phase 2: Bridge extension + Unix Socket Transport ✅

**Goal:** App and bridge can exchange messages reliably.

### Bridge extension

- [x] `extension.js` — `enable()` / `disable()` lifecycle
- [x] `socket_client.js` — connect to `$XDG_RUNTIME_DIR/gse-profiler.sock`, reconnect loop
- [x] Handshake message `{ type: "hello", version: "1", uuid: BRIDGE_UUID }`
- [x] GNOME panel indicator (simple icon from `Gio.ThemedIcon`, no menu in V1)

### App side

- [x] `app/core/socket_server.py` — async Unix socket server, `Gio.SocketService`
- [x] Message router — dispatch incoming JSON messages to the right subsystem
- [x] Auto-install logic:
  - Copy `bridge-extension/` to install path
  - Run `scripts/restart-shell.sh` in a subprocess
- [x] Connection status indicator in app header bar (connected / disconnected chip)
- [x] "Install / Reinstall bridge" action in app menu
- [x] Reinstall prompts shell restart

---

## Phase 3: Log Viewer ✅

**Goal:** Live, filterable log stream from journalctl.

- [x] `app/core/journal_reader.py`
  - Spawn `journalctl --follow -o json` subprocess
  - Parse JSON lines: `SYSLOG_IDENTIFIER`, `MESSAGE`, `PRIORITY`, `__REALTIME_TIMESTAMP`
  - Emit GObject signal per parsed entry
- [x] Log Viewer UI
  - `GtkTextView` with monospace font
  - Auto-scroll to bottom (toggle button to lock/unlock)
- [x] Filter bar
  - UUID dropdown (populated from Extension Manager)
  - Log level filter (DEBUG / INFO / WARNING / ERROR / CRITICAL)
  - Full-text search with match highlighting
- [x] Toolbar actions: copy selected lines, export visible log to `.txt` file, clear

---

## Phase 4: Profiler V1 ✅

**Goal:** Live function timing for a selected extension with flame graph visualization.

### Bridge side

- [x] `bridge-extension/profiler.js`
  - `startProfiling(uuid)` — monkey-patch all functions on extension's exported object
  - Record: function name, call depth, start timestamp (µs), end timestamp
  - Emit events via socket: `{ type: "profile_event", extensionUuid, function, start, end, depth }`
  - `stopProfiling()` — restore original functions

### App side

- [x] Profiler UI
  - Start / stop profiling controls (select target extension from dropdown)
  - Call table (`GtkColumnView`): function name, call count, total ms, avg ms, max ms — sortable
  - Flame graph (`Gtk.DrawingArea` + Cairo): horizontal axis = time, vertical axis = call depth
    - Each bar labeled with function name (clipped to fit)
    - Zoom (mouse wheel), pan (click-drag), hover tooltip
    - Click to filter call table to selected function
    - Hide-idle toggle with log-scale gap compression
- [x] Save profile to JSON file (`Gio.File`)
- [x] Load profile from JSON file + same visualization
- [x] Clear / reset profiling data

---

## Phase 5: Inspector ✅

**Goal:** Live access to extension `stateObj` properties and methods.

### Bridge side

- [x] `bridge-extension/inspector.js`
  - `inspect(uuid, path)` — resolve `stateObj` down the path one level at a time
  - Enumerate own properties + prototype chain (1 level)
  - Serialize: `{ name, type, value }` — handle functions, circular refs, symbols
  - Respond with `{ type: "inspect_result", extensionUuid, path, properties: [...] }`

### App side

- [x] Inspector UI
  - `GtkColumnView`: property name | type | value (read-only in V1)
  - Inline expand chevron for object/array values (depth 0)
  - Drill-in chevron + monospace breadcrumb for nested navigation
  - Refresh button
  - Copy selected row (name + type + value) to clipboard
  - Type pills color-coded by JS type (string / number / boolean / object / array / null / error)

> **Descoped from V1:** inline property editing was prototyped but cut because
> the bridge would have needed full path-aware writes plus `Gio.Settings`
> support to be useful. See Phase 11 for the full plan.

---

## Pre-release

**Goal:** Polish, packaging, and distribution prep before tagging `v1.0.0`.

### Polish & UX

- [ ] Visual review pass — spacing, colours, icon consistency across all views
- [ ] Keyboard shortcuts (`Gtk.ShortcutController`): `Ctrl+R` refresh, `Ctrl+F` search, `Ctrl+S` save
- [ ] Onboarding flow for first launch (bridge not installed → step-by-step dialog)
- [ ] Error states and empty states reviewed in every view

### GitHub repository prep

- [ ] README with screenshots, feature list, and quick-start instructions
- [ ] AppStream metadata (`app/data/org.gnome.GSEProfiler.appdata.xml`)
- [ ] `.desktop` entry (`gse-profiler.desktop`)
- [ ] Icon set: SVG master + rasterised 48 / 64 / 128 px PNG
- [ ] `CHANGELOG.md` for v1.0.0

### Packaging & distribution

- [ ] Flatpak manifest (`build-aux/org.gnome.GSEProfiler.json`)
  - PyGObject, GTK4, libadwaita as SDK extensions
  - Bridge extension installed outside sandbox (`--filesystem=home`)
- [ ] `release.yml` extended: build Flatpak bundle and attach to GitHub Release
- [ ] Publish to Flathub

---

## 🚀 V1 Release

> Pre-release tasks complete → tag `v1.0.0`, publish GitHub Release with Flatpak bundle + changelog.

---

## Phase 6: Clone from GitHub (V2)

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

## Phase 7: Memory Profiling (V2)

**Goal:** Heap snapshots and allocation tracking.

- [ ] Bridge: expose SpiderMonkey heap stats via GJS `System.gc()` + memory counters
- [ ] Memory timeline chart — heap size over time (`Gtk.DrawingArea` + Cairo)
- [ ] Object count table by constructor name
- [ ] Snapshot diff: compare two snapshots, highlight growth
- [ ] Leak candidates: objects that grew monotonically between snapshots

---

## Phase 8: Extension Health & Linting (V2+)

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

## Phase 9: Settings & Preferences (V2+)

- [ ] `AdwPreferencesWindow`
  - Theme: follow system / force dark / force light
  - Log viewer: max lines buffer, font size
  - Socket path override (advanced)
  - Auto-connect bridge on launch
- [ ] Session persistence via GSettings — remember last selected extension, filter state
- [ ] i18n scaffold (gettext / `_()`) — English only initially, structure ready for translators

---

## Phase 10: Extended Packaging (V2+)

- [ ] RPM spec for Fedora/RHEL
- [ ] Bridge extension cleanup on app uninstall — `BridgeManager.uninstall()` hooked into `%preun` (RPM) and `cleanup` (Flatpak manifest)
- [ ] Full Flathub submission (review, metadata compliance, sandbox policy)

---

## Phase 11: Inspector V2 — Writable Properties (V2+)

**Goal:** Bring back inline editing of extension state in a way that actually
works across the whole tree, not just the root level.

### Why this is its own phase

The V1 prototype only wrote to `stateObj[name]`, ignoring the active drill path,
and could never edit GSettings-backed values (which is where most extensions
keep their configurable state). Doing it properly means cooperating with both
nested object paths and `Gio.Settings`, so it belongs in V2.

### Bridge side

- [ ] `setProperty(uuid, path, name, value)` — walk `stateObj` down `path`,
      then assign to `target[name]`. Honour both data descriptors with `writable: true`
      and accessor descriptors with a setter.
- [ ] Detect `Gio.Settings` instances during serialization; expose their keys as
      writable children with their declared schema type (`b`, `i`, `d`, `s`, enums).
- [ ] Re-introduce a `writable` flag in `inspect_result` for each property — only
      `true` when the property is actually assignable on the current `holder`
      (own data prop, accessor with setter, or known GSettings key).
- [ ] Validate `set_property` values against the property's reported type before
      assigning; reject with a typed error instead of throwing.

### App side

- [ ] Render a "writable" affordance on rows that can be edited (e.g. an edit
      pencil icon that appears on hover, mirroring the drill-in chevron).
- [ ] Adwaita `AlertDialog` for edit, with a control matched to the type:
  - String → `Gtk.Entry`
  - Number → `Gtk.SpinButton` with min/max from GSettings schema where known
  - Boolean → `Gtk.Switch`
  - Enum (GSettings choice key) → `Gtk.DropDown` populated with allowed values
- [ ] Send `set_property` with the current navigation `path` and the row `name`.
- [ ] On `set_property_result.ok` → re-issue `inspect` at the current path and
      flash the affected row briefly to confirm the write.
- [ ] On `set_property_result.error` → `Adw.Toast` with the bridge's error message.
- [ ] Drop stale `set_property_result`s where `extensionUuid` / `path` no longer
      match the active navigation (same pattern as stale `inspect_result`s).

### Protocol additions

```
→ { type: "set_property", uuid, path, name, value }
← { type: "set_property_result", extensionUuid, path, name, ok, error? }
```

`inspect_result.properties[*].writable` returns as a boolean — absent or `false`
means read-only for V1 clients.

---

## Deferred — opt-in Developer API

> **Status: deferred indefinitely.** The core tooling covers the developer use-case well enough for V1 and V2. Revisit only if there is concrete demand.

**Original goal:** Extension developers integrate `DevToolsClient` for custom profiling marks, counters, and property watches.

- `api/devtools-api.js` — `DevToolsClient` with `connect`, `mark`, `measure`, `counter`, `watch`
- Bridge routes `devtools_*` message types to profiler subsystem
- App displays API-originated events in a distinct colour
- All methods: silent no-op when not connected

---

## Milestone Summary

| Phase         | Milestone             | Scope                         | Status       |
| ------------- | --------------------- | ----------------------------- | ------------ |
| 0             | Skeleton + CI         | Project setup                 | ✅ done      |
| 1             | Extension Manager     | List, enable/disable          | ✅ done      |
| 2             | Bridge + Socket       | App ↔ Shell IPC               | ✅ done      |
| 3             | Log Viewer            | Live filtered logs            | ✅ done      |
| 4             | Profiler V1           | Timing table + flame graph    | ✅ done      |
| 5             | Inspector             | stateObj live view (R/O)      | ✅ done      |
| —             | Pre-release           | Polish, GitHub, Flatpak       | in progress  |
| —             | **V1 Release**        | **tag v1.0.0**                | **upcoming** |
| 6             | GitHub clone          | Install extensions (V2)       | planned      |
| 7             | Memory profiling      | Heap analysis (V2)            | planned      |
| 8             | Health checks         | Linting + validation (V2+)    | planned      |
| 9             | Settings              | Preferences window (V2+)      | planned      |
| 10            | Extended packaging    | RPM + Flathub full (V2+)      | planned      |
| 11            | Inspector writable    | Full property editing (V2+)   | planned      |
| —             | opt-in Developer API  | Extension author integration  | deferred ∞   |

---

## Implementation Notes

### Async strategy (Python)

Use `asyncio` with `gbulb` or `asyncio`'s GLib integration to bridge the GLib main loop
with `asyncio` coroutines. All socket I/O and subprocess communication should be async.
Never block with `subprocess.run()` on the main thread.

### Wayland compatibility

Avoid `org.gnome.Shell Eval` entirely for runtime introspection — it is restricted on Wayland
and may be disabled in future GNOME versions. All deep operations go through the bridge socket.

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
