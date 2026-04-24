# Multi-monitor edge detection — design

- Status: approved (interface + implementation), pending implementation
- Date: 2026-04-24
- Related: bug #N/A (multi-monitor "unnatural trigger" reported in conversation)
- Target version: `mouseferry` v0.1.1

## Problem

`mouseferry` v0.1.0 computes the trigger edge from the bounding box of the **entire X11 virtual desktop**:

```python
screen_w = max(x + w for each connected monitor)
# trigger fires when mouse_x >= screen_w - threshold
```

In single-monitor setups this matches user intent. In multi-monitor setups it does not: the rightmost edge of the virtual desktop coincides with the rightmost edge of the rightmost monitor, which may be far from where the Android device physically sits.

Concrete report from the user:

> 3 monitors: laptop (primary, bottom), one above the laptop, one above-and-to-the-right. Tablet next to the laptop. To trigger `--right`, the cursor must travel up onto the top-right monitor and reach its right edge. Unnatural.

## Goals

- Trigger fires from the edge of a **single, user-selectable monitor** ("target monitor"), not the virtual desktop
- Works in mobile setups: target can change as the laptop moves between docks
- Continues to work when external monitors are disconnected (graceful fallback)
- Trigger does not fire when the cursor crosses the same X coordinate but at a Y where the target monitor isn't (i.e., when the cursor has wandered to an adjacent monitor)
- Discoverable from the CLI: user can list available monitors without consulting `xrandr` directly

## Non-goals

- **Hotplug detection.** If the user changes monitor layout while `mouseferry` is running, they must restart it. Polling `xrandr` continuously adds overhead for a rare case.
- **Wayland support.** This design relies on `xrandr` and `xdotool`; Wayland support is a separate, larger effort.
- **Multi-monitor target.** Only one target monitor at a time. No "trigger on edge of either of these two monitors".
- **Per-direction target.** The same target monitor is used regardless of `--left`/`--right`. Splitting per direction adds config complexity for a marginal use case.

## Decisions

| Decision | Choice | Rejected alternatives |
|---|---|---|
| How to identify the monitor | `primary` (default) / `auto-from-cursor` / explicit xrandr name | name-only (less convenient), spatial labels like `bottom-left` (fragile) |
| Override mechanism | config key + CLI flag (CLI wins) | config-only (no quick override) |
| Behavior when target not connected | Fallback chain: target → primary → first available, with WARNING | Fail loud (breaks mobility), silent fallback (hides config drift) |
| Edge detection | 2D: X at edge of target **AND** Y inside target's vertical band | 1D X-only (false positives when cursor wanders to adjacent monitors) |
| Hotplug | Snapshot at startup, document restart requirement | Periodic re-poll (overhead), `SIGUSR1` re-detection (YAGNI for now) |
| Default `return_sensitivity` | Lower from 2000 to 800 (bundled in same release) | Keep 2000 (real-world data shows the typical gesture produces ~800; 2000 is the documented bug that the user already worked around manually in v0.1.0) |

## Interface

### Config schema (`~/.config/mouseferry/config.ini`)

New key inside `[general]`:

```ini
[general]
edge = right
threshold = 2
poll_ms = 50
return_sensitivity = 800

# Which monitor's edge counts as the trigger.
# Allowed values:
#   primary           use the X11 primary monitor (default)
#   auto-from-cursor  snapshot the monitor under the cursor at startup
#   <output-name>     exact xrandr output name, e.g. eDP-1, HDMI-1, DP-2
monitor = primary
```

Existing configs without the `monitor` key default to `primary` — fully backwards compatible.

### CLI flags (additions to existing argparse)

```
--monitor SPEC      override config; SPEC accepts the same values listed above
--list-monitors     print connected monitors with geometry + primary marker, then exit
```

### `--help` output (full)

```
usage: mouseferry [-h] [--config PATH] [--left | --right] [--monitor SPEC]
                  [--list-monitors]

mouseferry — seamless mouse sharing: Linux PC <-> Android via scrcpy

options:
  -h, --help          show this help message and exit
  --config PATH       path to config file (default: ~/.config/mouseferry/config.ini)

direction (overrides config):
  --left              Android device is to the left of the PC
  --right             Android device is to the right of the PC

monitor (overrides config):
  --monitor SPEC      which monitor's edge counts as the trigger.
                      Accepted values for SPEC:
                        primary           the X11 primary monitor (default)
                        auto-from-cursor  whichever monitor the cursor is on at startup
                        <output-name>     exact xrandr output name (e.g. eDP-1, HDMI-1)
                      Use --list-monitors to see what's connected.

introspection:
  --list-monitors     print connected monitors with geometry + primary marker, then exit

examples:
  mouseferry --left                              # use config defaults
  mouseferry --right --monitor eDP-1             # explicit override
  mouseferry --right --monitor auto-from-cursor  # pick monitor under cursor now
  mouseferry --list-monitors                     # show what's available

config file: ~/.config/mouseferry/config.ini
docs:        https://github.com/mattabott/mouseferry
```

`--help` does not invoke `xrandr` and works without a running X server.

### Startup output (normal)

```
[mouseferry] Mouse: Compx 2.4G Receiver Mouse
[mouseferry] Monitors detected: eDP-1 (primary 1920x1200+0+1080), HDMI-1 (1920x1080+0+0), DP-2 (1920x1080+1920+0)
[mouseferry] Target monitor: eDP-1 (1920x1200+0+1080)
[mouseferry] Edge: right
[mouseferry] Ready — move the mouse to the right edge of eDP-1 to ferry over.
```

### Startup output (fallback)

```
[mouseferry] WARNING: monitor 'HDMI-2' not connected (available: eDP-1, HDMI-1, DP-2). Falling back to 'primary'.
[mouseferry] Target monitor: eDP-1 (1920x1200+0+1080)
```

### Startup output (irrecoverable)

```
[mouseferry] ERROR: cannot query xrandr (DISPLAY may be unavailable). mouseferry requires a running X session.
```
Exit code 1.

### `--list-monitors` output

```
Connected monitors:
  eDP-1   1920x1200+0+1080   primary
  HDMI-1  1920x1080+0+0
  DP-2    1920x1080+1920+0

To target one of these in your config, set:
  [general]
  monitor = eDP-1
```

## Implementation

### Data model

```python
Monitor = namedtuple("Monitor", "name x y w h primary")
```

### Parser (`parse_xrandr() -> list[Monitor]`)

Primary path: `xrandr --listmonitors`. Format example:

```
Monitors: 3
 0: +*eDP-1 1920/344x1200/215+0+1080  eDP-1
 1: +HDMI-1 1920/477x1080/268+0+0  HDMI-1
 2: +DP-2 1920/477x1080/268+1920+0  DP-2
```

Regex:
```python
_MON_RE = re.compile(
    r"^\s*\d+:\s*\+(\*?)(\S+)\s+(\d+)/\d+x(\d+)/\d+\+(-?\d+)\+(-?\d+)"
)
```

Captures: `primary_marker`, `name`, `w`, `h`, `x`, `y`. The `-?` on coordinates handles vertically-stacked monitors (negative Y).

If `--listmonitors` returns no matched lines, fallback to parsing `xrandr --query` for `connected` lines (existing approach in v0.1.0). If both fail or `xrandr` itself errors → return empty list; caller exits with the irrecoverable error message above.

### Resolver (`resolve_target(monitors, spec, cursor_pos) -> tuple[Monitor, str | None]`)

Pure function, no I/O. Returns `(target_monitor, fallback_reason_or_None)`. The reason is logged + printed only when non-`None`.

Behavior table:

| `spec`              | Resolution | Fallback reason if any |
|---------------------|------------|------------------------|
| `"primary"`         | the monitor with `primary=True` | "no primary marker, using first available" if none marked |
| `"auto-from-cursor"`| monitor whose box contains `(cx, cy)` | "cursor not over any monitor, using primary" if cursor between monitors |
| `<name>`            | monitor with `name == spec` | "monitor '<name>' not connected, using primary" if name not found |

Final fallback (if even `primary` is missing): use `monitors[0]` with reason "...using first available".

If `monitors` is empty → `ValueError`; caller catches and exits with the irrecoverable error.

### Edge check (replaces `_at_edge(x)` with `_at_edge(x, y)`)

```python
def _at_edge(self, x, y):
    m = self.target_mon
    if not (m.y <= y < m.y + m.h):
        return False
    if self.edge == "left":
        return x <= m.x + self.threshold
    return x >= m.x + m.w - self.threshold
```

`main_loop` already discards `y`; change to `x, y = get_mouse_pos()` and pass both.

### Return-to-desktop warp (`_release_to_desktop`)

Warp to the center of the target monitor (currently warps relative to virtual-desktop dimensions):

```python
m = self.target_mon
margin = 50
cy = m.y + m.h // 2
if self.edge == "left":
    warp_mouse(m.x + margin, cy)
else:
    warp_mouse(m.x + m.w - margin, cy)
```

### `--list-monitors` action

Bypasses scrcpy/adb checks, evdev setup, and config loading. Just: parse → format → print → `sys.exit(0)`. Allows running it on machines that have X but not the rest of the toolchain.

### `MouseFerry.__init__` changes

- Remove call to `get_screen_geometry()`
- Call `parse_xrandr()` → `monitors`
- Call `resolve_target(monitors, config["monitor"], cursor_pos)` → `target_mon, reason`
- Store `self.target_mon`, `self.monitors`
- Print "Monitors detected" + "Target monitor" lines (and warning if `reason`)
- Replace any reference to `self.screen_w`/`self.screen_h` with `self.target_mon.w`/`self.target_mon.h` (only in `_at_edge` and `_release_to_desktop`)

### Config / argparse

- `DEFAULT_CONFIG`: add `monitor = primary` line; **also** lower `return_sensitivity = 2000 → 800` (bundled in this release as a bug fix surfaced by the same investigation)
- `config.ini.example`: same changes
- `argparse`:
  - Add `--monitor` (string, default `None` so we can detect "not passed")
  - Add `--list-monitors` (`action="store_true"`)
  - Restructure help into argument groups (`direction`, `monitor`, `introspection`) — argparse supports this with `add_argument_group`
  - Add `epilog` with examples and config-file path

## Acceptance criteria

A change is considered done when:

1. **Default config**: existing users with no `monitor` key get `primary` behavior (no behavior change for single-monitor setups).
2. **Config override**: setting `monitor = HDMI-1` in config and restarting `mouseferry` makes the trigger fire from `HDMI-1`'s edge only, with no false positive when the cursor passes the same X coord at a Y outside `HDMI-1`'s band.
3. **CLI override**: `mouseferry --right --monitor eDP-1` overrides any config value.
4. **`auto-from-cursor`**: positioning the cursor on a non-primary monitor and launching with `--monitor auto-from-cursor` selects that monitor.
5. **Fallback**: setting `monitor = HDMI-99` (nonexistent) prints the WARNING line and uses `primary`.
6. **`--list-monitors`**: prints the connected monitors with primary marker and exits with code 0.
7. **`--help`**: prints the help block above (verbatim or close), works without `DISPLAY` set.
8. **Multi-monitor regression test (manual)**: in the user's specific 3-monitor setup (laptop + above + above-right), with `monitor = primary` and `--right`, the trigger fires when the cursor reaches the right edge of the laptop screen (at any Y inside the laptop band) and does NOT fire when the cursor crosses the same X coord at a Y on one of the upper monitors.
9. **Return warp**: after returning from Android, the cursor lands at the center-edge of the target monitor (not somewhere on the virtual desktop).
10. `ruff check mouseferry` passes (CI green).

## Out of scope (explicitly deferred)

- Wayland support
- `SIGUSR1` re-detection on hotplug
- Multi-target monitors (`monitor = eDP-1,HDMI-1`)
- Per-direction targets (`monitor.left = …`, `monitor.right = …`)
- Spatial labels (`bottom-left`, `top-right`) as monitor identifiers
- A `--config-write` flag to update the config file from CLI

## Risks

- **xrandr output format drift**: very stable historically (no breaking format change in many years), but if a distro ships a custom `xrandr`, the regex may fail. Mitigated by the `--query` fallback parser and the irrecoverable-error path.
- **`Monitor` namedtuple immutability**: snapshot taken at startup; if hotplug happens, the namedtuple is stale. Mitigated by documenting the restart requirement in `--help` and README.
- **Negative coordinates** (monitors above the primary): handled explicitly in the regex via `-?\d+` and tested in the resolver. Already part of the user's actual setup.
