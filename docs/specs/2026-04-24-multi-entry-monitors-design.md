# Multi-entry monitors with per-entry direction — design

- Status: approved (interface + implementation), pending implementation
- Date: 2026-04-24
- Related: [issue #1 (GitHub)](https://github.com/mattabott/mouseferry/issues/1)
- Target version: `mouseferry` v0.2.0
- Supersedes the v0.3 label in issue #1 (no v0.2 was planned in between; this feature is now v0.2.0).

## Problem

`mouseferry` v0.1.1 supports one **single entry edge** on one **single monitor**. In real-world setups a user may position the Android tablet so that it is physically adjacent to more than one monitor at once — e.g. right of the laptop AND below a top-right monitor — and want to ferry to the same tablet from any of those edges. v0.1.1 cannot express this.

Concrete scenario from the user:

> 3 monitors: laptop (primary, bottom), one above the laptop, one above-and-to-the-right. Tablet physically wedged so it's reachable both from the right edge of the laptop and from the bottom edge of the top-right monitor. Single Android device — not two.

## Goals

- Support **multiple entry edges on multiple monitors**, each with its own direction
- Support **all four cardinal directions** (`left`, `right`, `top`, `bottom`) — v0.1.1 only supports `left`/`right`
- Keep the model **single-device / single-return**: one Android device, one return monitor
- Multi-entry config lives on the **CLI only** (per user preference): agile for mobile setups, scriptable via shell aliases
- **Zero breaking change** for v0.1.1 users: if they don't pass `--entry`, behavior is identical

## Non-goals

- **Config-file storage of multi-entry**. User explicitly rejected this; the CLI-only contract is a deliberate UX choice to force an explicit decision at launch.
- **Multiple Android devices.** Single device per `mouseferry` process. If a user ever wants multi-device, that's a separate, larger effort (serial routing, multiple scrcpy subprocesses, output disambiguation).
- **Hotplug re-detection.** Same as v0.1.1: snapshot at startup, restart required if the layout changes.
- **Variable return monitor per entry.** The return is always a single monitor regardless of which entry triggered the ferry.
- **TUI / interactive mode.** Rejected in favor of pure CLI (the wizard gets boring by the 10th launch).
- **Profile system** (named sets of entries persisted in config). Can be added later if demand emerges.
- **Wayland support.** Unchanged from v0.1.1.

## Decisions

| Decision | Choice | Rejected alternatives |
|---|---|---|
| Where multi-entry is configured | CLI only (`--entry`, `--return`) | Config section (rejected by user), mutex config+CLI, profile system |
| CLI format | `--entry MONITOR:DIRECTION`, repeatable | `--entries a:right,b:bottom` (awkward to script), two flags `--from --edge` (ambiguous with repetition) |
| Separator inside `--entry` value | `:` | `=` (looks like assignment), `/` (path-like), `,` (list-like, collides) |
| Default `--return` if omitted | X11 primary monitor | First `--entry`'s monitor (surprising when entries are ordered arbitrarily), require explicit `--return` (ergonomically bad) |
| Legacy flag behavior (`--left`/`--right`/`--monitor`) when `--entry` is passed | Ignored with WARNING, not error | Hard error (breaks scripts migrating incrementally) |
| Return warp target | Center of `return_mon` in multi; lateral (as v0.1.1) in single | Center always (changes v0.1.1 UX), lateral in multi (ambiguous which side) |
| Return-detection axis | Per-active-entry (set at `switch_to_android`), stored on the class | Fixed per run (breaks if entries mix directions), inferred each tick (more state) |
| `return_sensitivity` for X vs Y | Single shared value, same as v0.1.1 | Separate `return_sensitivity_x` / `_y` (no evidence needed yet — YAGNI) |
| Edge values allowed in single-entry (config-driven) mode | `left` / `right` only (preserves v0.1.1 behavior bit-for-bit) | Allow all 4 (would require 4-way warp branch in `_release_to_desktop`; unnecessary because users who need top/bottom naturally want multi-entry anyway) |

## Interface

### CLI flags (additions)

```
multi-entry (v0.2+, disables --left/--right/--monitor + config edge/monitor):
  --entry SPEC        monitor:direction pair, repeatable
                      monitor: primary | auto-from-cursor | <xrandr output name> | <1-based index>
                      direction: left | right | top | bottom
                      Example: --entry primary:right --entry 3:bottom
  --return MONITOR    return monitor (default: primary)
                      Accepts: primary | auto-from-cursor | <xrandr name> | <1-based index>
                      (direction is NOT part of --return's value.)
```

### Example invocations

```bash
# v0.1.1 syntax still works (single-entry from config):
mouseferry --right

# New: single-entry via CLI in v0.2 (equivalent to --right --monitor primary,
# but runs through the new multi-entry codepath):
mouseferry --entry primary:right

# Real multi-entry: ferry from laptop's right OR from monitor 3's bottom,
# return lands on laptop:
mouseferry --entry primary:right --entry 3:bottom

# Equivalent with explicit return:
mouseferry --entry 1:right --entry 3:bottom --return 1

# Mixing all four directions on different monitors:
mouseferry --entry 1:right --entry 2:top --entry 3:bottom --return 1
```

### Conflict with v0.1.1 flags

When `--entry` is passed and any of `--left`, `--right`, `--monitor` is also passed (or `edge`/`monitor` is set in the config file), the process prints a single WARNING line listing what is ignored, then continues in multi-entry mode:

```
[mouseferry] WARNING: --right and --monitor are ignored because --entry is in use.
```

No hard error — a user migrating incrementally can leave their old flags in an alias without breaking the run.

### Startup output in multi-entry mode

```
[mouseferry] Mouse: Compx 2.4G Receiver Mouse
[mouseferry] Monitors detected: eDP-1 (primary 1920x1200+0+1080), HDMI-1 (1920x1080+0+0), DP-2 (1920x1080+1920+0)
[mouseferry] Entries:
  - eDP-1 (right)
  - DP-2 (bottom)
[mouseferry] Return: eDP-1
[mouseferry] Android: 1600x2560
[mouseferry] Ready — ferry triggers from any configured edge.
```

Any per-entry fallback (e.g. `--entry HDMI-99:right` when HDMI-99 is not connected) prints its own `WARNING:` line before the `Entries:` block.

### Single-entry startup (v0.1.1 unchanged)

Identical to v0.1.1 — same `Target monitor:` line, same `Ready — move the mouse to the EDGE edge of NAME to ferry over.` message. No visible change.

### `--help` output

Adds a fourth argument group (`multi-entry (v0.2+, …)`) with the two new flags. Existing groups (`direction`, `monitor`, `introspection`) are preserved for backward compatibility, clearly labeled as the v0.1.1-style entry point. Epilog gains one example line for multi-entry.

## Implementation

### Data model

```python
Entry = namedtuple("Entry", "monitor direction")
```

`Entry.monitor` is a `Monitor` namedtuple (unchanged from v0.1.1). `direction` is one of `"left"`, `"right"`, `"top"`, `"bottom"`.

### Pure helpers (module-level, testable)

```python
_VALID_DIRECTIONS = ("left", "right", "top", "bottom")


def parse_entry_spec(raw):
    """Parse a --entry CLI value like 'primary:right' into (spec, direction).

    Raises ValueError with a user-facing message on any malformed input.
    """
    if ":" not in raw:
        raise ValueError(f"invalid entry '{raw}': expected MONITOR:DIRECTION "
                         f"(e.g. primary:right)")
    spec, direction = raw.rsplit(":", 1)
    spec = spec.strip()
    direction = direction.strip()
    if not spec:
        raise ValueError(f"invalid entry '{raw}': monitor spec is empty")
    if direction not in _VALID_DIRECTIONS:
        raise ValueError(f"invalid direction '{direction}' in entry '{raw}': "
                         f"must be one of {'/'.join(_VALID_DIRECTIONS)}")
    return spec, direction


def entry_matches(entry, x, y, threshold):
    """True if the cursor at (x, y) is at the configured edge of entry.monitor."""
    m = entry.monitor
    d = entry.direction
    if d == "left":
        return m.y <= y < m.y + m.h and x <= m.x + threshold
    if d == "right":
        return m.y <= y < m.y + m.h and x >= m.x + m.w - threshold
    if d == "top":
        return m.x <= x < m.x + m.w and y <= m.y + threshold
    if d == "bottom":
        return m.x <= x < m.x + m.w and y >= m.y + m.h - threshold
    raise ValueError(f"unknown direction: {d}")


_DIRECTION_RETURN_CONFIG = {
    "left":   ("X", +1),
    "right":  ("X", -1),
    "top":    ("Y", +1),
    "bottom": ("Y", -1),
}


def direction_return_config(direction):
    """Return (axis_letter, sign) for sweep-return detection from direction.

    axis_letter is 'X' or 'Y' (caller maps to evdev.ecodes.REL_X / REL_Y at runtime).
    sign is +1 when the return sweep moves in the positive direction along the axis,
    -1 when it moves in the negative direction.
    """
    if direction not in _DIRECTION_RETURN_CONFIG:
        raise ValueError(f"unknown direction: {direction}")
    return _DIRECTION_RETURN_CONFIG[direction]
```

### `MouseFerry` class — state changes

Attributes removed:
- `self.target_mon` — v0.1.1 single target, replaced by `self.entries[0].monitor` in single-entry mode, irrelevant in multi
- `self.edge` — replaced by `self.entries[0].direction` in single, irrelevant in multi
- `self._return_sign` initialized in `__init__` — now set per-entry at `switch_to_android`

Attributes added:
- `self.entries: list[Entry]` — always >=1 element. In single-entry mode, exactly one `Entry(target_mon, edge_from_config)`.
- `self.return_mon: Monitor` — always set. In single-entry mode, same as `entries[0].monitor`.
- `self.multi_entry: bool` — True if the user passed `--entry`.
- `self._active_entry: Entry | None` — set by `switch_to_android`, cleared by `_release_to_desktop`.
- `self._return_axis: int` — evdev event code (`REL_X` or `REL_Y`), set by `switch_to_android` from `self._active_entry.direction`.
- `self._return_sign: int` — `+1` or `-1`, set by `switch_to_android`.

Rename: `self._recent_dx` → `self._recent_d` (axis-agnostic).

### `MouseFerry.__init__` — new signature

```python
def __init__(self, config, cli_entries=None, cli_return=None):
    # ...read basic config as before (threshold, poll_ms, sensitivity, serial, scrcpy args)...

    self.monitors = parse_xrandr()
    if not self.monitors:
        print(f"[{APP_NAME}] ERROR: cannot query xrandr (DISPLAY may be unavailable). "
              f"mouseferry requires a running X session.")
        sys.exit(1)

    cursor_pos = get_mouse_pos()
    self.multi_entry = bool(cli_entries)

    if self.multi_entry:
        self.entries = []
        for raw in cli_entries:
            spec, direction = parse_entry_spec(raw)
            monitor, fallback_reason = resolve_target(self.monitors, spec, cursor_pos)
            if fallback_reason:
                print(f"[{APP_NAME}] WARNING: {fallback_reason}")
            self.entries.append(Entry(monitor, direction))

        if cli_return:
            return_mon, return_reason = resolve_target(self.monitors, cli_return, cursor_pos)
            if return_reason:
                print(f"[{APP_NAME}] WARNING: (return) {return_reason}")
            self.return_mon = return_mon
        else:
            self.return_mon = self.entries[0].monitor
    else:
        # v0.1.1 single-entry path
        monitor_spec = config.get("general", "monitor", fallback="primary").strip() or "primary"
        target_mon, fallback_reason = resolve_target(self.monitors, monitor_spec, cursor_pos)
        if fallback_reason:
            print(f"[{APP_NAME}] WARNING: {fallback_reason}")
        edge = config.get("general", "edge", fallback="left").strip() or "left"
        # Single-entry only supports left/right (v0.1.1 compat).
        # For top/bottom, the user must opt into multi-entry mode via --entry.
        if edge not in ("left", "right"):
            print(f"[{APP_NAME}] ERROR: invalid edge '{edge}' in config "
                  f"(single-entry mode supports only 'left' or 'right'; "
                  f"use --entry for 'top'/'bottom').")
            sys.exit(1)
        self.entries = [Entry(target_mon, edge)]
        self.return_mon = target_mon

    self.android_w, self.android_h = get_android_screen(self.serial)
    # ...evdev / mouse device discovery as before...
    # ...startup print block updated to handle both modes...
```

### Runtime methods

**`_edge_match(x, y) -> Entry | None`** — new; replaces `_at_edge(x, y) -> bool`:

```python
def _edge_match(self, x, y):
    for entry in self.entries:
        if entry_matches(entry, x, y, self.threshold):
            return entry
    return None
```

**`switch_to_android(entry)`** — takes the entry that triggered:

```python
def switch_to_android(self, entry):
    if self.active:
        return
    # ...existing scrcpy startup + window activation...
    self._active_entry = entry

    import evdev
    axis_letter, sign = direction_return_config(entry.direction)
    self._return_axis = (evdev.ecodes.REL_X if axis_letter == "X"
                         else evdev.ecodes.REL_Y)
    self._return_sign = sign

    # ...tracker activation as before...
```

**`_track_loop`** — axis-aware:

```python
def _track_loop(self):
    import evdev
    while not self.stopping:
        # ...select + read as before...
        for event in self._mouse_dev.read():
            # ...
            if event.type == evdev.ecodes.EV_REL and event.code == self._return_axis:
                now = time.time()
                if now - self._track_started < self.CAPTURE_SETTLE:
                    continue
                self._recent_d.append((now, event.value))
                cutoff = now - self.RETURN_WINDOW
                self._recent_d = [e for e in self._recent_d if e[0] > cutoff]
                net = sum(v for _, v in self._recent_d) * self._return_sign
                if net >= self.RETURN_NET_THRESHOLD:
                    log(f"RETURN! net={net}")
                    self._want_release = True
                    self._track_active = False
```

**`_release_to_desktop`** — branched warp:

```python
def _release_to_desktop(self):
    # ...kill scrcpy + restore prev window as before...
    if self.multi_entry:
        m = self.return_mon
        warp_mouse(m.x + m.w // 2, m.y + m.h // 2)
    else:
        # v0.1.1 lateral warp, unchanged
        margin = 50
        m = self.entries[0].monitor
        cy = m.y + m.h // 2
        if self.entries[0].direction == "left":
            warp_mouse(m.x + margin, cy)
        else:
            warp_mouse(m.x + m.w - margin, cy)

    self._active_entry = None
    # ...log + print as before...
```

**`main_loop`** — uses the new `_edge_match`:

```python
def main_loop(self):
    start_time = time.time()
    while not self.stopping:
        now = time.time()
        if self.active:
            if self._want_release:
                self._release_to_desktop()
        else:
            if (now - start_time > self.STARTUP_DELAY and
                    now - self.last_release > self.ENTRY_COOLDOWN):
                x, y = get_mouse_pos()
                entry = self._edge_match(x, y)
                if entry:
                    self.switch_to_android(entry)
        time.sleep(self.poll_s)
```

### `main()` CLI plumbing

```python
# ...existing argparse setup (direction / monitor / introspection groups)...

multi = parser.add_argument_group(
    "multi-entry (v0.2+, disables --left/--right/--monitor + config edge/monitor)")
multi.add_argument("--entry", metavar="SPEC", action="append", default=[],
                   help="monitor:direction pair, repeatable. "
                        "monitor: primary | auto-from-cursor | <xrandr-name> | <1-based index>. "
                        "direction: left | right | top | bottom. "
                        "Example: --entry primary:right --entry 3:bottom")
multi.add_argument("--return", metavar="MONITOR", dest="return_monitor", default=None,
                   help="return monitor (default: primary). "
                        "Accepts the same monitor values as --entry (no :direction).")

# ...existing list_monitors short-circuit...
# ...existing config load...

# CLI conflict warning
if args.entry:
    conflicts = []
    if args.edge:
        conflicts.append("--" + args.edge)  # --left or --right
    if args.monitor:
        conflicts.append("--monitor")
    if conflicts:
        print(f"[{APP_NAME}] WARNING: {', '.join(conflicts)} ignored because --entry is in use.")
    # args.entry + args.return_monitor go straight to MouseFerry(..., cli_entries=..., cli_return=...)
else:
    # v0.1.1 path: apply args.edge / args.monitor to config as before
    ...

signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
MouseFerry(config, cli_entries=args.entry or None, cli_return=args.return_monitor).run()
```

### Validation of `--entry` at startup

`parse_entry_spec` raises `ValueError` with a user-facing message on bad input. `main()` catches these at parse time (before constructing `MouseFerry`) and prints the error + exits with code 2 (argparse-style).

### Tests

**Unit tests added to `tests/test_monitor.py`** (current: 24, after: ~38):

- `parse_entry_spec` — 8 cases:
  - happy: `"primary:right"`, `"3:bottom"`, `"eDP-1:top"`, `"auto-from-cursor:left"` (4)
  - error: `"primary"` (no colon), `":right"` (empty spec), `"primary:"` (empty direction), `"primary:sideways"` (invalid direction) (4)
- `entry_matches` — 8 cases:
  - For each of 4 directions: one hit position + one miss position (out-of-band on the orthogonal axis) (8)
- `direction_return_config` — 5 cases:
  - 4 happy (one per direction) + 1 error (unknown direction) (5)

No class-level integration tests. The class still relies on evdev / scrcpy / xrandr and is exercised by manual smoke tests at release.

### CI

No changes. `.github/workflows/ci.yml` already runs ruff + pytest; it will pick up the new tests automatically.

## Acceptance criteria

Implementation is done when:

1. **Backward compat:** running `mouseferry --right` or `mouseferry --right --monitor 1` on a v0.1.1 config produces identical behavior to v0.1.1 (same startup output, same warp logic, same tracker).
2. **Multi-entry happy path:** `mouseferry --entry primary:right --entry 3:bottom` on the user's real 3-monitor setup triggers the ferry both from the right edge of the primary AND from the bottom edge of monitor 3, and each return lands in the center of the primary monitor.
3. **Return axis switching:** when the ferry was triggered from a `top`/`bottom` entry, a vertical sweep of the mouse returns control (not a horizontal one).
4. **Fallback per entry:** `--entry HDMI-99:right` (nonexistent) prints a WARNING and falls back to primary for that entry; other entries are unaffected.
5. **Default `--return`:** omitting `--return` uses the X11 primary monitor (so the cursor lands on the user's main workspace by default); specifying `--return N` overrides.
6. **Legacy flag warning:** `mouseferry --right --entry primary:right` prints a single WARNING line listing `--right` as ignored.
7. **Validation error:** `mouseferry --entry primary:sideways` exits with a clear error mentioning the four valid directions.
8. **`--help` documented:** the four argument groups (`direction`, `monitor`, `introspection`, `multi-entry`) are all present and the epilog includes at least one multi-entry example.
9. **Unit tests:** all ~38 tests pass. `ruff check mouseferry` green.
10. **No regression:** existing 24 tests still pass.

## Out of scope (explicitly deferred)

- Config-file persistence of multi-entry (`[entries]` section, `monitor = a:right, b:bottom`, profile system)
- Multiple Android devices
- Hotplug re-detection
- Variable return monitor per entry
- TUI / interactive mode
- Wayland support
- Per-axis `return_sensitivity` (`sensitivity_x`, `sensitivity_y`)

## Risks

- **Mouse DPI asymmetry** — we assume the sweep threshold `return_sensitivity = 800` works for both X and Y axes. For most optical/laser mice this holds; for mice with separate X/Y DPI settings it may not. **Mitigation:** document in README, add a per-axis sensitivity key if user testing reveals a real asymmetry.
- **Entry ambiguity** — if a user passes `--entry 1:right --entry 1:right` (same entry twice), nothing breaks (first-match wins) but it's wasteful. **Decision:** allow it silently; a dedup warning would be noise.
- **Return sweep from middle of virtual desktop** — if the user has wandered to a non-entry monitor while in the ferry state, a REL_X/Y sweep still returns. This is desired (you want to come back regardless of where the cursor wandered while SDL had it grabbed). **No action.**
- **Argparse `dest="return_monitor"`** — `--return` can't be `dest="return"` because `return` is a Python keyword. Using `dest="return_monitor"` avoids that. Cosmetic but worth noting.
- **Entry direction validation timing** — current design validates via `parse_entry_spec` at `MouseFerry.__init__` time (not at argparse time). This is fine because `main()` wraps the constructor in a try/except and surfaces the error. **Alternative:** validate in argparse via `type=parse_entry_spec`; rejected because argparse error formatting is less friendly than our own print.
