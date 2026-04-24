# Multi-monitor edge detection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `mouseferry`'s virtual-desktop-wide edge detection with per-monitor targeting (configurable via `primary` / `auto-from-cursor` / xrandr name, with CLI override and fallback chain), plus 2D edge checking that respects the target monitor's Y band.

**Architecture:** Keep the single-file script. Introduce a `Monitor` namedtuple and three pure helper functions (`parse_xrandr_listmonitors`, `parse_xrandr_query`, `resolve_target`) with unit tests via pytest. Thin wrapper `parse_xrandr()` shells out and falls through parsers. `MouseFerry.__init__` snapshots monitors once at startup; `_at_edge(x, y)` and `_release_to_desktop()` use the resolved target monitor's bounding box.

**Tech Stack:** Python 3.8+ (stdlib only: `re`, `subprocess`, `configparser`, `argparse`, `evdev` already listed). Test runner: `pytest` via `uvx pytest` (no new runtime deps). Lint: `ruff` via `uvx ruff` (existing).

**Reference spec:** [`docs/specs/2026-04-24-multi-monitor-edge-detection-design.md`](../specs/2026-04-24-multi-monitor-edge-detection-design.md)

---

## File Structure

**Files modified:**
- `mouseferry` — add `Monitor` namedtuple, parser functions, resolver, CLI flags, integrate into class
- `config.ini.example` — add `monitor = primary`, lower `return_sensitivity = 800`
- `README.md` — new "Multi-monitor setups" section, hotplug restart note
- `.github/workflows/lint.yml` → renamed `ci.yml`, adds pytest step

**Files created:**
- `tests/__init__.py` — empty marker
- `tests/test_monitor.py` — unit tests for the three pure functions

No file splits. `mouseferry` stays as a single-file script — it's still small enough (~450 lines after this) that adding internal modules would be overkill for a hobby tool. Future split point is the CLI layer vs the runtime loop, if the script crosses ~800 lines.

---

## Task 1: Set up test infrastructure

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_monitor.py` (placeholder that imports from `mouseferry`)

- [ ] **Step 1.1: Create empty package marker**

File: `tests/__init__.py`
```python
```
(empty file — just marks `tests/` as a package)

- [ ] **Step 1.2: Create conftest.py to make the `mouseferry` script importable**

The script has no `.py` extension, so pytest cannot import it as-is. `conftest.py` adds the repo root to `sys.path` and imports the script as a module via `importlib`.

File: `tests/conftest.py`
```python
"""Make the extension-less `mouseferry` script importable as a module."""
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "mouseferry"


def _load_mouseferry():
    spec = importlib.util.spec_from_loader(
        "mouseferry_script",
        importlib.machinery.SourceFileLoader("mouseferry_script", str(SCRIPT_PATH)),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mouseferry_script"] = mod
    spec.loader.exec_module(mod)
    return mod


mouseferry = _load_mouseferry()
```

- [ ] **Step 1.3: Create a minimal placeholder test to verify import works**

File: `tests/test_monitor.py`
```python
from tests.conftest import mouseferry


def test_module_imports():
    assert hasattr(mouseferry, "MouseFerry")
```

- [ ] **Step 1.4: Run pytest to confirm infrastructure works**

Run: `uvx pytest tests/ -v`
Expected: `1 passed` (the placeholder test finds the `MouseFerry` class).

If pytest complains about `main()` running at import time: it won't, because the script has `if __name__ == "__main__": main()` — importlib's executor sets `__name__ = "mouseferry_script"`, so `main()` is not called. Good.

- [ ] **Step 1.5: Commit**

```bash
git add tests/
git commit -m "test: bootstrap pytest harness importing the extension-less script"
```

---

## Task 2: `Monitor` namedtuple + `parse_xrandr_listmonitors`

**Files:**
- Modify: `mouseferry` (add namedtuple + function near the top, before `# -- X11 helpers --`)
- Modify: `tests/test_monitor.py`

- [ ] **Step 2.1: Write the failing tests**

Append to `tests/test_monitor.py`:
```python
LISTMONITORS_SAMPLE = """\
Monitors: 3
 0: +*eDP-1 1920/344x1200/215+0+1080  eDP-1
 1: +HDMI-1 1920/477x1080/268+0+0  HDMI-1
 2: +DP-2 1920/477x1080/268+1920+0  DP-2
"""

LISTMONITORS_SINGLE = """\
Monitors: 1
 0: +*eDP-1 1920/344x1200/215+0+0  eDP-1
"""

LISTMONITORS_NEGATIVE_Y = """\
Monitors: 2
 0: +HDMI-1 1920/477x1080/268+0+-1080  HDMI-1
 1: +*eDP-1 1920/344x1200/215+0+0  eDP-1
"""


def test_parse_listmonitors_three_monitors():
    mons = mouseferry.parse_xrandr_listmonitors(LISTMONITORS_SAMPLE)
    assert len(mons) == 3
    edp = next(m for m in mons if m.name == "eDP-1")
    assert edp.x == 0 and edp.y == 1080
    assert edp.w == 1920 and edp.h == 1200
    assert edp.primary is True
    hdmi = next(m for m in mons if m.name == "HDMI-1")
    assert hdmi.primary is False


def test_parse_listmonitors_single_monitor():
    mons = mouseferry.parse_xrandr_listmonitors(LISTMONITORS_SINGLE)
    assert len(mons) == 1
    assert mons[0].name == "eDP-1" and mons[0].primary is True


def test_parse_listmonitors_handles_negative_y():
    mons = mouseferry.parse_xrandr_listmonitors(LISTMONITORS_NEGATIVE_Y)
    hdmi = next(m for m in mons if m.name == "HDMI-1")
    assert hdmi.y == -1080


def test_parse_listmonitors_empty_input():
    assert mouseferry.parse_xrandr_listmonitors("") == []
```

- [ ] **Step 2.2: Run tests to verify they fail**

Run: `uvx pytest tests/test_monitor.py -v`
Expected: 4 FAIL with `AttributeError: module 'mouseferry_script' has no attribute 'parse_xrandr_listmonitors'`.

- [ ] **Step 2.3: Implement `Monitor` + `parse_xrandr_listmonitors`**

In `mouseferry`, after the imports (around line 24, right after `import select`), add:
```python
from collections import namedtuple

Monitor = namedtuple("Monitor", "name x y w h primary")

_LISTMONITORS_RE = re.compile(
    r"^\s*\d+:\s*\+(\*?)(\S+)\s+(\d+)/\d+x(\d+)/\d+\+(-?\d+)\+(-?\d+)"
)


def parse_xrandr_listmonitors(text):
    """Parse `xrandr --listmonitors` output into a list of Monitor."""
    monitors = []
    for line in text.splitlines():
        m = _LISTMONITORS_RE.match(line)
        if m:
            prim, name, w, h, x, y = m.groups()
            monitors.append(Monitor(
                name=name,
                x=int(x), y=int(y),
                w=int(w), h=int(h),
                primary=(prim == "*"),
            ))
    return monitors
```

- [ ] **Step 2.4: Run tests to verify they pass**

Run: `uvx pytest tests/test_monitor.py -v`
Expected: 5 passed (4 new + the placeholder).

- [ ] **Step 2.5: Commit**

```bash
git add mouseferry tests/test_monitor.py
git commit -m "feat: add Monitor namedtuple and parse_xrandr_listmonitors"
```

---

## Task 3: `parse_xrandr_query` fallback parser

**Files:**
- Modify: `mouseferry` (add function next to `parse_xrandr_listmonitors`)
- Modify: `tests/test_monitor.py`

- [ ] **Step 3.1: Write the failing tests**

Append to `tests/test_monitor.py`:
```python
QUERY_SAMPLE = """\
Screen 0: minimum 320 x 200, current 3840 x 2280, maximum 16384 x 16384
eDP-1 connected primary 1920x1200+0+1080 (normal left inverted right x axis y axis) 344mm x 215mm
   1920x1200     60.00*+
HDMI-1 connected 1920x1080+0+0 (normal left inverted right x axis y axis) 477mm x 268mm
   1920x1080     60.00*+
DP-2 connected 1920x1080+1920+0 (normal left inverted right x axis y axis) 477mm x 268mm
   1920x1080     60.00*+
DP-3 disconnected (normal left inverted right x axis y axis)
"""


def test_parse_query_three_monitors():
    mons = mouseferry.parse_xrandr_query(QUERY_SAMPLE)
    assert len(mons) == 3
    names = sorted(m.name for m in mons)
    assert names == ["DP-2", "HDMI-1", "eDP-1"]
    edp = next(m for m in mons if m.name == "eDP-1")
    assert edp.primary is True
    hdmi = next(m for m in mons if m.name == "HDMI-1")
    assert hdmi.primary is False


def test_parse_query_skips_disconnected():
    mons = mouseferry.parse_xrandr_query(QUERY_SAMPLE)
    assert not any(m.name == "DP-3" for m in mons)


def test_parse_query_empty_input():
    assert mouseferry.parse_xrandr_query("") == []
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `uvx pytest tests/test_monitor.py -v`
Expected: 3 new tests FAIL with `AttributeError: ... parse_xrandr_query`.

- [ ] **Step 3.3: Implement `parse_xrandr_query`**

In `mouseferry`, right below `parse_xrandr_listmonitors`, add:
```python
_QUERY_RE = re.compile(
    r"^(\S+)\s+connected\s+(primary\s+)?(\d+)x(\d+)\+(-?\d+)\+(-?\d+)"
)


def parse_xrandr_query(text):
    """Parse `xrandr --query` output into a list of Monitor (fallback parser)."""
    monitors = []
    for line in text.splitlines():
        m = _QUERY_RE.match(line)
        if m:
            name, prim, w, h, x, y = m.groups()
            monitors.append(Monitor(
                name=name,
                x=int(x), y=int(y),
                w=int(w), h=int(h),
                primary=bool(prim),
            ))
    return monitors
```

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `uvx pytest tests/test_monitor.py -v`
Expected: 8 passed.

- [ ] **Step 3.5: Commit**

```bash
git add mouseferry tests/test_monitor.py
git commit -m "feat: add parse_xrandr_query as fallback parser for listmonitors failures"
```

---

## Task 4: `parse_xrandr` wrapper (shells out, tries listmonitors then query)

**Files:**
- Modify: `mouseferry` (replace `get_screen_geometry` call site later; for now just add the wrapper)

- [ ] **Step 4.1: Implement `parse_xrandr` wrapper**

In `mouseferry`, add below `parse_xrandr_query`:
```python
def parse_xrandr():
    """Shell out to xrandr and return monitors. Tries --listmonitors, falls back to --query."""
    out = run("xrandr", "--listmonitors")
    monitors = parse_xrandr_listmonitors(out.stdout) if out.returncode == 0 else []
    if not monitors:
        out = run("xrandr", "--query")
        if out.returncode == 0:
            monitors = parse_xrandr_query(out.stdout)
    return monitors
```

No unit test for this one — it's a thin I/O wrapper. It'll be exercised by the integration smoke test in Task 11.

- [ ] **Step 4.2: Commit**

```bash
git add mouseferry
git commit -m "feat: add parse_xrandr wrapper that tries --listmonitors then --query"
```

---

## Task 5: `resolve_target` resolver

**Files:**
- Modify: `mouseferry`
- Modify: `tests/test_monitor.py`

- [ ] **Step 5.1: Write the failing tests**

Append to `tests/test_monitor.py`:
```python
@pytest.fixture
def three_mons():
    return [
        mouseferry.Monitor("HDMI-1",    0,    0, 1920, 1080, False),
        mouseferry.Monitor("eDP-1",     0, 1080, 1920, 1200, True),
        mouseferry.Monitor("DP-2",   1920,    0, 1920, 1080, False),
    ]


def test_resolve_primary_happy_path(three_mons):
    target, reason = mouseferry.resolve_target(three_mons, "primary", (100, 1200))
    assert target.name == "eDP-1"
    assert reason is None


def test_resolve_primary_no_marker_falls_back_to_first(three_mons):
    no_primary = [m._replace(primary=False) for m in three_mons]
    target, reason = mouseferry.resolve_target(no_primary, "primary", (0, 0))
    assert target.name == "HDMI-1"  # first in list
    assert "no primary" in reason


def test_resolve_auto_from_cursor_picks_monitor_under_cursor(three_mons):
    # cursor at (2500, 500) is on DP-2 (x=1920..3839, y=0..1079)
    target, reason = mouseferry.resolve_target(three_mons, "auto-from-cursor", (2500, 500))
    assert target.name == "DP-2"
    assert reason is None


def test_resolve_auto_from_cursor_on_primary(three_mons):
    target, reason = mouseferry.resolve_target(three_mons, "auto-from-cursor", (500, 1500))
    assert target.name == "eDP-1"


def test_resolve_auto_from_cursor_off_all_monitors(three_mons):
    # cursor at (5000, 5000) is nowhere
    target, reason = mouseferry.resolve_target(three_mons, "auto-from-cursor", (5000, 5000))
    assert target.name == "eDP-1"  # falls back to primary
    assert "cursor not over any monitor" in reason


def test_resolve_named_happy_path(three_mons):
    target, reason = mouseferry.resolve_target(three_mons, "HDMI-1", (0, 0))
    assert target.name == "HDMI-1"
    assert reason is None


def test_resolve_named_not_connected_falls_back_to_primary(three_mons):
    target, reason = mouseferry.resolve_target(three_mons, "HDMI-99", (0, 0))
    assert target.name == "eDP-1"
    assert "HDMI-99" in reason and "not connected" in reason


def test_resolve_named_not_connected_no_primary_falls_back_to_first(three_mons):
    no_primary = [m._replace(primary=False) for m in three_mons]
    target, reason = mouseferry.resolve_target(no_primary, "HDMI-99", (0, 0))
    assert target.name == "HDMI-1"
    assert "first available" in reason


def test_resolve_empty_monitors_raises():
    with pytest.raises(ValueError):
        mouseferry.resolve_target([], "primary", (0, 0))
```

Also add `import pytest` at the top of `tests/test_monitor.py` if it's not there yet.

- [ ] **Step 5.2: Run tests to verify they fail**

Run: `uvx pytest tests/test_monitor.py -v`
Expected: 9 new tests FAIL with `AttributeError: ... resolve_target`.

- [ ] **Step 5.3: Implement `resolve_target`**

In `mouseferry`, below `parse_xrandr`, add:
```python
def resolve_target(monitors, spec, cursor_pos):
    """Pick the target monitor from a list based on spec.

    Returns (Monitor, fallback_reason_or_None). Non-None reason means a
    fallback happened and should be surfaced to the user.
    """
    if not monitors:
        raise ValueError("no monitors available")

    primary = next((m for m in monitors if m.primary), None)

    if spec == "primary":
        if primary:
            return primary, None
        return monitors[0], "no primary marker, using first available"

    if spec == "auto-from-cursor":
        cx, cy = cursor_pos
        for m in monitors:
            if m.x <= cx < m.x + m.w and m.y <= cy < m.y + m.h:
                return m, None
        if primary:
            return primary, "cursor not over any monitor, using primary"
        return monitors[0], "cursor not over any monitor, using first available"

    # named
    target = next((m for m in monitors if m.name == spec), None)
    if target:
        return target, None
    if primary:
        return primary, f"monitor '{spec}' not connected, using primary"
    return monitors[0], f"monitor '{spec}' not connected, using first available"
```

- [ ] **Step 5.4: Run tests to verify they pass**

Run: `uvx pytest tests/test_monitor.py -v`
Expected: 17 passed (8 parser + 9 resolver).

- [ ] **Step 5.5: Commit**

```bash
git add mouseferry tests/test_monitor.py
git commit -m "feat: add resolve_target with primary/auto-from-cursor/named + fallbacks"
```

---

## Task 6: Integrate monitor selection into `MouseFerry.__init__`

**Files:**
- Modify: `mouseferry` (class `MouseFerry`, method `__init__`; also the startup print section)

- [ ] **Step 6.1: Replace `get_screen_geometry` call and add monitor snapshot**

In `MouseFerry.__init__`, find these lines (they're near the top of the method):
```python
        self.screen_w, self.screen_h = get_screen_geometry()
        self.android_w, self.android_h = get_android_screen(self.serial)
```

Replace with:
```python
        # Monitor snapshot: taken once at startup, used for edge detection.
        self.monitors = parse_xrandr()
        if not self.monitors:
            print(f"[{APP_NAME}] ERROR: cannot query xrandr (DISPLAY may be unavailable). "
                  f"mouseferry requires a running X session.")
            sys.exit(1)

        monitor_spec = config.get("general", "monitor", fallback="primary").strip() or "primary"
        cursor_pos = get_mouse_pos()
        self.target_mon, fallback_reason = resolve_target(
            self.monitors, monitor_spec, cursor_pos
        )

        self.android_w, self.android_h = get_android_screen(self.serial)
```

- [ ] **Step 6.2: Replace startup print block**

Find the existing startup prints:
```python
        print(f"[{APP_NAME}] Mouse: {dev.name}")
        print(f"[{APP_NAME}] PC:      {self.screen_w}x{self.screen_h}")
        print(f"[{APP_NAME}] Android: {self.android_w}x{self.android_h}")
        print(f"[{APP_NAME}] Edge:    {self.edge}")
        print(f"[{APP_NAME}] Ready — move the mouse to the {self.edge} edge to ferry over.")
        log(f"start mouse={dev.name} edge={self.edge} "
            f"screen={self.screen_w}x{self.screen_h} android={self.android_w}x{self.android_h}")
```

Replace with:
```python
        print(f"[{APP_NAME}] Mouse: {dev.name}")
        detected = ", ".join(
            f"{m.name} ({'primary ' if m.primary else ''}{m.w}x{m.h}+{m.x}+{m.y})"
            for m in self.monitors
        )
        print(f"[{APP_NAME}] Monitors detected: {detected}")
        if fallback_reason:
            print(f"[{APP_NAME}] WARNING: {fallback_reason}")
        t = self.target_mon
        print(f"[{APP_NAME}] Target monitor: {t.name} ({t.w}x{t.h}+{t.x}+{t.y})")
        print(f"[{APP_NAME}] Android: {self.android_w}x{self.android_h}")
        print(f"[{APP_NAME}] Edge:    {self.edge}")
        print(f"[{APP_NAME}] Ready — move the mouse to the {self.edge} edge of {t.name} to ferry over.")
        log(f"start mouse={dev.name} edge={self.edge} "
            f"target={t.name} geom={t.w}x{t.h}+{t.x}+{t.y} "
            f"android={self.android_w}x{self.android_h} fallback={fallback_reason or 'none'}")
```

- [ ] **Step 6.3: Remove the now-unused `get_screen_geometry` function**

Delete the entire `get_screen_geometry` function from the file (currently around lines 60-68 — look for `def get_screen_geometry():`).

- [ ] **Step 6.4: Verify tests still pass (no regression)**

Run: `uvx pytest tests/test_monitor.py -v`
Expected: 17 passed. The class-level changes don't break the pure-function tests.

- [ ] **Step 6.5: Commit**

```bash
git add mouseferry
git commit -m "feat: snapshot monitors at startup and resolve target via new helpers"
```

---

## Task 7: Update `_at_edge` to 2D check

**Files:**
- Modify: `mouseferry` (methods `_at_edge` and `main_loop`)

- [ ] **Step 7.1: Update `_at_edge` signature and logic**

Find the method (around line 175):
```python
    def _at_edge(self, x):
        if self.edge == "left":
            return x <= self.threshold
        return x >= self.screen_w - self.threshold
```

Replace with:
```python
    def _at_edge(self, x, y):
        m = self.target_mon
        # Y must be inside the target monitor's vertical band
        if not (m.y <= y < m.y + m.h):
            return False
        if self.edge == "left":
            return x <= m.x + self.threshold
        return x >= m.x + m.w - self.threshold
```

- [ ] **Step 7.2: Update `main_loop` to pass `y`**

Find in `main_loop`:
```python
                    x, _ = get_mouse_pos()
                    if self._at_edge(x):
                        self.switch_to_android()
```

Replace with:
```python
                    x, y = get_mouse_pos()
                    if self._at_edge(x, y):
                        self.switch_to_android()
```

- [ ] **Step 7.3: Commit**

```bash
git add mouseferry
git commit -m "feat: 2D edge detection (X at edge AND Y inside target monitor band)"
```

---

## Task 8: Update `_release_to_desktop` warp to target monitor

**Files:**
- Modify: `mouseferry` (method `_release_to_desktop`)

- [ ] **Step 8.1: Update warp logic**

Find in `_release_to_desktop`:
```python
        margin = 50
        if self.edge == "left":
            warp_mouse(margin, self.screen_h // 2)
        else:
            warp_mouse(self.screen_w - margin, self.screen_h // 2)
```

Replace with:
```python
        margin = 50
        m = self.target_mon
        cy = m.y + m.h // 2
        if self.edge == "left":
            warp_mouse(m.x + margin, cy)
        else:
            warp_mouse(m.x + m.w - margin, cy)
```

- [ ] **Step 8.2: Commit**

```bash
git add mouseferry
git commit -m "feat: warp cursor back to target monitor center on return"
```

---

## Task 9: Add CLI flags `--monitor`, `--list-monitors`, restructured `--help`

**Files:**
- Modify: `mouseferry` (function `main` and add helper `list_monitors_action`)

- [ ] **Step 9.1: Add `list_monitors_action` helper**

In `mouseferry`, above `def main():`, add:
```python
def list_monitors_action():
    """Print connected monitors and exit. Does not require scrcpy/adb/evdev."""
    monitors = parse_xrandr()
    if not monitors:
        print("No monitors detected (is X running and DISPLAY set?)")
        sys.exit(1)
    print("Connected monitors:")
    for m in monitors:
        marker = "   primary" if m.primary else ""
        print(f"  {m.name:8} {m.w}x{m.h}+{m.x}+{m.y}{marker}")
    print()
    default_name = next((m.name for m in monitors if m.primary), monitors[0].name)
    print("To target one of these in your config, set:")
    print("  [general]")
    print(f"  monitor = {default_name}")
    sys.exit(0)
```

- [ ] **Step 9.2: Replace `argparse` setup in `main()`**

Find in `main()`:
```python
    import argparse
    parser = argparse.ArgumentParser(
        description="mouseferry — seamless mouse sharing: Linux PC <-> Android via scrcpy")
    parser.add_argument("--config", default=CONFIG_FILE,
                        help="Path to config file (default: ~/.config/mouseferry/config.ini)")
    parser.add_argument("--left", action="store_const", const="left", dest="edge",
                        help="Android device is to the left of the PC")
    parser.add_argument("--right", action="store_const", const="right", dest="edge",
                        help="Android device is to the right of the PC")
    args = parser.parse_args()
```

Replace with:
```python
    import argparse
    epilog = """\
examples:
  mouseferry --left                              # use config defaults
  mouseferry --right --monitor eDP-1             # explicit override
  mouseferry --right --monitor auto-from-cursor  # pick monitor under cursor now
  mouseferry --list-monitors                     # show what's available

config file: ~/.config/mouseferry/config.ini
docs:        https://github.com/mattabott/mouseferry
"""
    parser = argparse.ArgumentParser(
        prog="mouseferry",
        description="mouseferry — seamless mouse sharing: Linux PC <-> Android via scrcpy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
    )
    parser.add_argument("--config", metavar="PATH", default=CONFIG_FILE,
                        help="path to config file (default: ~/.config/mouseferry/config.ini)")

    direction = parser.add_argument_group("direction (overrides config)")
    direction_excl = direction.add_mutually_exclusive_group()
    direction_excl.add_argument("--left", action="store_const", const="left", dest="edge",
                                 help="Android device is to the left of the PC")
    direction_excl.add_argument("--right", action="store_const", const="right", dest="edge",
                                 help="Android device is to the right of the PC")

    monitor = parser.add_argument_group("monitor (overrides config)")
    monitor.add_argument("--monitor", metavar="SPEC", default=None,
                         help="which monitor's edge counts as the trigger. "
                              "Accepted: primary | auto-from-cursor | <xrandr output name> "
                              "(e.g. eDP-1). Use --list-monitors to see what's connected.")

    introspection = parser.add_argument_group("introspection")
    introspection.add_argument("--list-monitors", action="store_true",
                                help="print connected monitors with geometry + primary marker, "
                                     "then exit")

    args = parser.parse_args()

    if args.list_monitors:
        list_monitors_action()
```

- [ ] **Step 9.3: Propagate `--monitor` into config**

Still in `main()`, find:
```python
    # CLI flag overrides config
    if args.edge:
        if not config.has_section("general"):
            config.add_section("general")
        config.set("general", "edge", args.edge)
```

Replace with:
```python
    # CLI flags override config
    if not config.has_section("general"):
        config.add_section("general")
    if args.edge:
        config.set("general", "edge", args.edge)
    if args.monitor:
        config.set("general", "monitor", args.monitor)
```

- [ ] **Step 9.4: Lint check**

Run: `uvx ruff check mouseferry`
Expected: `All checks passed!`

- [ ] **Step 9.5: Verify `--help` output manually**

Run: `python3 mouseferry --help`
Expected: help text with three argument groups (`direction`, `monitor`, `introspection`) and the epilog with examples.

- [ ] **Step 9.6: Commit**

```bash
git add mouseferry
git commit -m "feat: add --monitor and --list-monitors CLI flags, restructured --help"
```

---

## Task 10: Update config template and example

**Files:**
- Modify: `mouseferry` (constant `DEFAULT_CONFIG`)
- Modify: `config.ini.example`

- [ ] **Step 10.1: Update `DEFAULT_CONFIG` in `mouseferry`**

Find:
```python
DEFAULT_CONFIG = """\
# mouseferry — configuration

[general]
# Screen edge that triggers the switch to Android: left | right
edge = left

# Pixels from the edge required to trigger the switch
threshold = 2

# Mouse polling interval in ms
poll_ms = 50

# Return sensitivity: how strongly you have to sweep the mouse back toward
# the PC to return control. Higher values = a more decisive gesture is
# required. Recommended: 1500-3000.
return_sensitivity = 2000

[scrcpy]
# Android device serial (empty = auto-detect via adb)
serial =

# Extra flags passed to scrcpy (space-separated)
extra_args =
"""
```

Replace with:
```python
DEFAULT_CONFIG = """\
# mouseferry — configuration

[general]
# Screen edge that triggers the switch to Android: left | right
edge = left

# Pixels from the edge required to trigger the switch
threshold = 2

# Mouse polling interval in ms
poll_ms = 50

# Return sensitivity: how strongly you have to sweep the mouse back toward
# the PC to return control. Higher values = a more decisive gesture is
# required. Typical real-world range: 600-1200 depending on mouse DPI
# (the gesture produces a net REL_X delta in this range over ~300 ms).
return_sensitivity = 800

# Which monitor's edge counts as the trigger.
# Allowed values:
#   primary           use the X11 primary monitor (default)
#   auto-from-cursor  snapshot the monitor under the cursor at startup
#   <output-name>     exact xrandr output name, e.g. eDP-1, HDMI-1, DP-2
# Use `mouseferry --list-monitors` to see what's connected.
monitor = primary

[scrcpy]
# Android device serial (empty = auto-detect via adb)
serial =

# Extra flags passed to scrcpy (space-separated)
extra_args =
"""
```

- [ ] **Step 10.2: Update `config.ini.example`**

Overwrite `config.ini.example` with the same content as the new `DEFAULT_CONFIG` body (without the surrounding triple-quotes).

- [ ] **Step 10.3: Commit**

```bash
git add mouseferry config.ini.example
git commit -m "feat: add monitor key to default config, lower return_sensitivity to 800"
```

---

## Task 11: Extend CI to run pytest, rename workflow file

**Files:**
- Delete: `.github/workflows/lint.yml`
- Create: `.github/workflows/ci.yml`

- [ ] **Step 11.1: Create new workflow file**

File: `.github/workflows/ci.yml`
```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    name: ruff
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install ruff
        run: pip install --upgrade ruff
      - name: Run ruff
        run: ruff check mouseferry

  test:
    name: pytest
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install pytest
        run: pip install --upgrade pytest
      - name: Run pytest
        run: pytest tests/ -v
```

- [ ] **Step 11.2: Remove old workflow**

```bash
git rm .github/workflows/lint.yml
git add .github/workflows/ci.yml
```

- [ ] **Step 11.3: Commit**

```bash
git commit -m "ci: add pytest job alongside ruff, rename workflow to ci.yml"
```

---

## Task 12: Update README with multi-monitor section

**Files:**
- Modify: `README.md`

- [ ] **Step 12.1: Add new section `## Multi-monitor setups`**

Insert the following section between the existing "## Configuration" and "## How it works, under the hood" sections:

```markdown
## Multi-monitor setups

By default `mouseferry` binds the trigger to the **X11 primary monitor**. In a single-monitor setup that's exactly what you want. In a multi-monitor setup it means the trigger fires from the edge of whichever display `xrandr` reports as `primary`, regardless of where that display sits in your virtual desktop.

If the primary is not the monitor next to your Android device, change the target:

```bash
# See what's connected
mouseferry --list-monitors

# Pick a specific output
mouseferry --right --monitor eDP-1

# Or snapshot whichever monitor the cursor is on right now
mouseferry --right --monitor auto-from-cursor
```

You can also set it permanently in `~/.config/mouseferry/config.ini`:

```ini
[general]
monitor = eDP-1
```

Values:

| Value | Meaning |
|---|---|
| `primary` *(default)* | The monitor marked `primary` in `xrandr`. Change it with `xrandr --output <name> --primary`. |
| `auto-from-cursor` | Whichever monitor the cursor is on at startup. Position the mouse on the target monitor, then launch. |
| `<output-name>` | Exact xrandr output name (e.g. `eDP-1`, `HDMI-1`, `DP-2`). Stable across sessions for the same hardware. |

The edge check is 2D: the trigger only fires when the cursor is both at the configured edge and inside the target monitor's vertical band. This prevents false positives when the cursor wanders onto a monitor stacked above or below.

**Fallback:** if the monitor name you set is not connected (e.g. you undocked), `mouseferry` prints a warning and falls back to `primary`, then to the first available monitor. It keeps working.

**Hotplug:** the monitor layout is snapshotted at startup. If you plug or unplug a display while `mouseferry` is running, restart it to pick up the change.
```

- [ ] **Step 12.2: Add `tests/` to `.gitignore`'s exclusion list** (actually: remove from ignore)

The existing `.gitignore` ignores `__pycache__/`. That's fine; no change needed. But make sure `tests/` is tracked (it is, since we committed it in Task 1).

- [ ] **Step 12.3: Commit**

```bash
git add README.md
git commit -m "docs: document multi-monitor setup, --list-monitors, fallback, hotplug"
```

---

## Task 13: Smoke tests, release tag, push

**Files:** none modified in this task — verification + release only.

- [ ] **Step 13.1: Full local verification**

Run:
```bash
uvx ruff check mouseferry
uvx pytest tests/ -v
```
Expected: `All checks passed!` + 17 passed.

- [ ] **Step 13.2: Smoke test — `--help`**

Run: `python3 mouseferry --help`
Expected: the help block from the spec shows, with three argument groups and the epilog.

- [ ] **Step 13.3: Smoke test — `--list-monitors`**

Run: `python3 mouseferry --list-monitors`
Expected: the connected monitors of the current machine, with primary marker, plus the config suggestion block. On the user's 3-monitor setup, the laptop's `eDP-1` (or whatever the laptop output is) should be marked `primary`.

- [ ] **Step 13.4: Smoke test — full run with primary target**

Run: `mouseferry --right --monitor primary` (on the user's actual setup).
Expected from acceptance criterion #8: the trigger fires when the cursor reaches the right edge of the primary monitor at any Y inside its band, and does NOT fire when the cursor crosses the same X coordinate at a Y on a non-primary monitor above.

Check `~/.config/mouseferry/last.log` to confirm `RETURN! net=…` lines when sweeping back.

- [ ] **Step 13.5: Smoke test — fallback**

Run: `mouseferry --right --monitor HDMI-99`
Expected: startup prints include `WARNING: monitor 'HDMI-99' not connected, using primary`, then proceeds normally.

- [ ] **Step 13.6: Tag v0.1.1 and push**

```bash
git log --oneline -20   # sanity check the commits look right
git tag -a v0.1.1 -m "v0.1.1 — multi-monitor edge detection + return_sensitivity default fix"
git push origin main
git push origin v0.1.1
```

- [ ] **Step 13.7: Create GitHub release for v0.1.1**

```bash
gh release create v0.1.1 \
  --repo mattabott/mouseferry \
  --title "v0.1.1 — multi-monitor edge detection" \
  --notes "$(cat <<'EOF'
### What's new

- **Multi-monitor support.** The trigger edge is now bound to a single target monitor instead of the whole virtual desktop. Configure via `monitor = primary | auto-from-cursor | <xrandr-name>` in `config.ini`, or override per-run with `--monitor`. See [README → Multi-monitor setups](https://github.com/mattabott/mouseferry#multi-monitor-setups).
- **2D edge check.** The trigger only fires when the cursor is at the configured edge **and** inside the target monitor's vertical band — no more false positives when the cursor wanders onto a stacked monitor.
- **New `--list-monitors` flag** — prints connected monitors with geometry and primary marker, then exits. Useful for discovering what to put in `config.ini`.
- **Restructured `--help`** with argument groups and inline examples.
- **Graceful fallback.** If the configured monitor is not connected, `mouseferry` warns and falls back to `primary` (then to the first available). Keeps working when you undock.

### Fixed

- **`return_sensitivity` default lowered from `2000` to `800`.** The previous default was too stiff for typical mouse DPI values — the average sweep back to the PC produces a net REL_X delta around 800, so the old default required an unnaturally decisive gesture. Existing users with a custom value are unaffected.

### Compatibility

- Fully backwards-compatible configs. Configs without a `monitor` key default to `primary` behavior.
- Still Linux / X11 only. Wayland support remains out of scope.
- **Hotplug:** the monitor layout is snapshotted at startup; restart `mouseferry` if you plug or unplug a display.
EOF
)"
```

- [ ] **Step 13.8: Verify CI is green on main**

```bash
gh run list --repo mattabott/mouseferry --limit 3
```
Expected: the most recent run for the new commit is `success`.

---

## Self-review

**Spec coverage:**
- Goals (sec 2): target monitor binding → Tasks 2-8 ✓; mobile/disconnect fallback → Task 5, 6 ✓; no false positives at wrong Y → Task 7 ✓; `--list-monitors` discoverability → Task 9 ✓.
- Non-goals: respected (no hotplug polling, no Wayland, no multi-target).
- Decisions table: all 6 rows implemented (monitor id scheme, override mechanism, fallback chain, 2D edge, snapshot-only, `return_sensitivity` default bundled).
- Interface (config + CLI + help + startup + fallback + error output): Tasks 6, 9, 10.
- Implementation details (Monitor namedtuple, parsers, resolver, edge check, release warp, list action): Tasks 2-9.
- Acceptance criteria #1-10: all mapped to Tasks 6, 7, 9, 10, 11, 13.

**Placeholder scan:** No TBD/TODO/"add error handling"/"similar to Task N". Every code-change step shows the exact code.

**Type consistency:** `Monitor` namedtuple fields (`name, x, y, w, h, primary`) match across Task 2 definition and Tasks 5-8 usage. `resolve_target` signature `(monitors, spec, cursor_pos) -> (Monitor, str | None)` consistent in Tasks 5 and 6. `parse_xrandr` return type (list of `Monitor`) consistent across Tasks 2, 3, 4.

**No residual issues.**
