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

**Goal:** Live function timing for a selected extension.

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
  - Timeline view (simple horizontal bar chart per function, sorted by start time)
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
> support to be useful. See Phase 13 for the full plan.

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
  - `connect(uuid)` — find and connect to bridge socket
  - `disconnect()`
  - `mark(name)` — timestamp marker
  - `measure(name, startMark, endMark)` — range from two marks
  - `counter(name, value)` — increment custom metric
  - `watch(object, properties)` — emit event on property change
  - All methods: silent no-op when not connected (no exceptions thrown)
- [ ] Bridge routes `devtools_*` message types to profiler subsystem
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

- [ ] Bridge: expose SpiderMonkey heap stats via GJS `System.gc()` + memory counters
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
  - Auto-connect bridge on launch
- [ ] Keyboard shortcuts (`Gtk.ShortcutController`)
  - `Ctrl+R` — refresh current view
  - `Ctrl+F` — focus search/filter
  - `Ctrl+S` — save profile / log export
- [ ] Session persistence via GSettings — remember last selected extension, filter state
- [ ] i18n scaffold (gettext / `_()`) — English only initially, structure ready for translators
- [ ] Onboarding flow for first launch (bridge not installed → step-by-step dialog)

---

## Phase 12: Packaging & Distribution (V2+)

- [ ] AppStream metadata (`app/data/org.gnome.GSEProfiler.appdata.xml`)
- [ ] `.desktop` entry (`gse-profiler.desktop`)
- [ ] Icon set: SVG master + rasterised 48 / 64 / 128 px PNG
- [ ] Flatpak manifest (`build-aux/org.gnome.GSEProfiler.json`)
  - PyGObject, GTK4, libadwaita as SDK extensions
  - Bridge extension installed outside sandbox (`--filesystem=home`)
- [ ] RPM spec for Fedora/RHEL
- [ ] `release.yml` extended: build Flatpak bundle and attach to GitHub Release
- [ ] Bridge extension cleanup on app uninstall — call `BridgeManager.uninstall()` (or a dedicated `scripts/uninstall.sh`) from the appropriate package uninstall hook: `%preun` in RPM, `cleanup` in Flatpak manifest

---

## Phase 13: Inspector V2 — Writable Properties (V2+)

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

## Milestone Summary

| Phase | Milestone           | Scope                       |
| ----- | ------------------- | --------------------------- |
| 0     | Skeleton + CI       | Project setup               |
| 1     | Extension Manager   | List, enable/disable        |
| 2     | Bridge + Socket     | App ↔ Shell IPC             |
| 3     | Log Viewer          | Live filtered logs          |
| 4     | Profiler V1         | Function timing table       |
| 5     | Inspector           | stateObj live view (R/O)    |
| 6     | GitHub clone        | Install extensions          |
| 7     | opt-in API          | Developer integration       |
| 8     | Flame graph         | Visual profiling (V2)       |
| 9     | Memory profiling    | Heap analysis (V2)          |
| 10    | Health checks       | Linting + validation (V2+)  |
| 11    | Settings + Polish   | UX completeness (V2+)       |
| 12    | Packaging           | Flatpak + releases (V2+)    |
| 13    | Inspector writable  | Full property editing (V2+) |

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

### No-op pattern for devtools-api.js

```javascript
mark(name) {
    if (!this._connected) return;
    this._send({ type: 'devtools_mark', name, ts: Date.now() });
}
```
