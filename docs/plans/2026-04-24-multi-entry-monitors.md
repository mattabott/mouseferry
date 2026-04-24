# Multi-entry monitors with per-entry direction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add CLI-only multi-entry mode to `mouseferry` — user can pass `--entry MONITOR:DIRECTION` repeatably (supporting all 4 directions `left`/`right`/`top`/`bottom`) and a single `--return` for the landing monitor, while preserving v0.1.1 single-entry behavior bit-for-bit when `--entry` is absent.

**Architecture:** Introduce three pure helpers (`parse_entry_spec`, `entry_matches`, `direction_return_config`) and an `Entry(monitor, direction)` namedtuple, all unit-testable. Refactor `MouseFerry` around `self.entries: list[Entry]` and `self.return_mon: Monitor`, with per-active-entry `_return_axis` and `_return_sign` set at `switch_to_android` time. Warp-on-return branches: center of `return_mon` in multi-entry, lateral warp preserved in single-entry. Single file, no splits.

**Tech Stack:** Python 3.8+ stdlib (`re`, `argparse`, `subprocess`, `configparser`, `collections.namedtuple`); `python-evdev` at runtime (already a dep). Tests via `pytest`; lint via `ruff` — both already wired in CI.

**Reference spec:** [`docs/specs/2026-04-24-multi-entry-monitors-design.md`](../specs/2026-04-24-multi-entry-monitors-design.md)

**Related:** closes [issue #1](https://github.com/mattabott/mouseferry/issues/1).

---

## File Structure

**Files modified:**
- `mouseferry` — add `Entry` + 3 pure helpers; refactor `MouseFerry.__init__`, `_edge_match` (replaces `_at_edge`), `switch_to_android`, `_track_loop`, `_release_to_desktop`, `main_loop`; add `--entry` / `--return` to argparse and the multi-entry argument group to `--help`
- `tests/test_monitor.py` — append ~14 new unit tests across the 3 pure helpers
- `README.md` — extend "Multi-monitor setups" with a "Multi-entry mode (v0.2+)" subsection

**Files not touched:**
- `config.ini.example`, `DEFAULT_CONFIG` in `mouseferry` — multi-entry is CLI-only by design; no config schema change
- `.github/workflows/ci.yml` — already runs `ruff` + `pytest` and will pick up the new tests automatically
- `tests/conftest.py` — importlib harness already works

No file splits. `mouseferry` is ~548 lines after v0.1.1; this change adds ~120 lines for a total of ~670 lines — still well under the single-file threshold.

---

## Task 1: Add `Entry` namedtuple + `parse_entry_spec`

**Files:**
- Modify: `mouseferry` (add near top, next to existing `Monitor` namedtuple and `_LISTMONITORS_RE`)
- Modify: `tests/test_monitor.py` (append tests)

- [ ] **Step 1.1: Write the failing tests**

Append to `tests/test_monitor.py`:
```python
# --- parse_entry_spec ---

def test_parse_entry_spec_primary_right():
    assert mouseferry.parse_entry_spec("primary:right") == ("primary", "right")


def test_parse_entry_spec_numeric_index():
    assert mouseferry.parse_entry_spec("3:bottom") == ("3", "bottom")


def test_parse_entry_spec_xrandr_name():
    assert mouseferry.parse_entry_spec("eDP-1:top") == ("eDP-1", "top")


def test_parse_entry_spec_auto_from_cursor():
    assert mouseferry.parse_entry_spec("auto-from-cursor:left") == ("auto-from-cursor", "left")


def test_parse_entry_spec_missing_colon_raises():
    with pytest.raises(ValueError, match="expected MONITOR:DIRECTION"):
        mouseferry.parse_entry_spec("primary")


def test_parse_entry_spec_empty_spec_raises():
    with pytest.raises(ValueError, match="monitor spec is empty"):
        mouseferry.parse_entry_spec(":right")


def test_parse_entry_spec_empty_direction_raises():
    with pytest.raises(ValueError, match="must be one of left/right/top/bottom"):
        mouseferry.parse_entry_spec("primary:")


def test_parse_entry_spec_invalid_direction_raises():
    with pytest.raises(ValueError, match="must be one of left/right/top/bottom"):
        mouseferry.parse_entry_spec("primary:sideways")


def test_entry_namedtuple_fields():
    e = mouseferry.Entry(monitor=mouseferry.Monitor("X", 0, 0, 100, 100, True), direction="right")
    assert e.monitor.name == "X"
    assert e.direction == "right"
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `/home/mattabott/.local/bin/uvx pytest tests/test_monitor.py -v`
Expected: 9 tests FAIL with `AttributeError: ... Entry` and `AttributeError: ... parse_entry_spec`.

- [ ] **Step 1.3: Implement `Entry` + `parse_entry_spec`**

In `mouseferry`, immediately below the existing `Monitor` namedtuple definition (around line 29, right after `Monitor = namedtuple("Monitor", "name x y w h primary")`), add:
```python
Entry = namedtuple("Entry", "monitor direction")

_VALID_DIRECTIONS = ("left", "right", "top", "bottom")


def parse_entry_spec(raw):
    """Parse a --entry CLI value like 'primary:right' into (spec, direction).

    Raises ValueError with a user-facing message on malformed input.
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
```

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `/home/mattabott/.local/bin/uvx pytest tests/test_monitor.py -v`
Expected: all tests pass (24 previous + 9 new = 33 passed).

- [ ] **Step 1.5: Commit**

```bash
git add mouseferry tests/test_monitor.py
git commit -m "feat: add Entry namedtuple and parse_entry_spec for multi-entry CLI"
```

---

## Task 2: Add `direction_return_config`

**Files:**
- Modify: `mouseferry`
- Modify: `tests/test_monitor.py`

- [ ] **Step 2.1: Write the failing tests**

Append to `tests/test_monitor.py`:
```python
# --- direction_return_config ---

def test_direction_return_config_left():
    assert mouseferry.direction_return_config("left") == ("X", +1)


def test_direction_return_config_right():
    assert mouseferry.direction_return_config("right") == ("X", -1)


def test_direction_return_config_top():
    assert mouseferry.direction_return_config("top") == ("Y", +1)


def test_direction_return_config_bottom():
    assert mouseferry.direction_return_config("bottom") == ("Y", -1)


def test_direction_return_config_unknown_raises():
    with pytest.raises(ValueError, match="unknown direction"):
        mouseferry.direction_return_config("sideways")
```

- [ ] **Step 2.2: Run tests to verify they fail**

Run: `/home/mattabott/.local/bin/uvx pytest tests/test_monitor.py -v`
Expected: 5 new tests FAIL with `AttributeError: ... direction_return_config`.

- [ ] **Step 2.3: Implement `direction_return_config`**

In `mouseferry`, immediately below `parse_entry_spec`, add:
```python
_DIRECTION_RETURN_CONFIG = {
    "left":   ("X", +1),
    "right":  ("X", -1),
    "top":    ("Y", +1),
    "bottom": ("Y", -1),
}


def direction_return_config(direction):
    """Return (axis_letter, sign) for sweep-return detection from direction.

    axis_letter is 'X' or 'Y'; caller maps to evdev.ecodes.REL_X / REL_Y at runtime.
    sign is +1 when the return sweep moves in the positive direction along the axis,
    -1 when negative.
    """
    if direction not in _DIRECTION_RETURN_CONFIG:
        raise ValueError(f"unknown direction: {direction}")
    return _DIRECTION_RETURN_CONFIG[direction]
```

- [ ] **Step 2.4: Run tests**

Run: `/home/mattabott/.local/bin/uvx pytest tests/test_monitor.py -v`
Expected: all tests pass (33 + 5 = 38 passed).

- [ ] **Step 2.5: Commit**

```bash
git add mouseferry tests/test_monitor.py
git commit -m "feat: add direction_return_config for per-entry return axis mapping"
```

---

## Task 3: Add `entry_matches`

**Files:**
- Modify: `mouseferry`
- Modify: `tests/test_monitor.py`

- [ ] **Step 3.1: Write the failing tests**

Append to `tests/test_monitor.py`:
```python
# --- entry_matches ---

@pytest.fixture
def entry_on_mon_at_origin():
    # A Monitor anchored at origin with size 1920x1080
    return mouseferry.Monitor("M", 0, 0, 1920, 1080, False)


def test_entry_matches_right_hit(entry_on_mon_at_origin):
    entry = mouseferry.Entry(monitor=entry_on_mon_at_origin, direction="right")
    # At the right edge (x = w - 1 with threshold=2), inside Y band
    assert mouseferry.entry_matches(entry, 1919, 500, 2) is True


def test_entry_matches_right_miss_outside_y_band(entry_on_mon_at_origin):
    entry = mouseferry.Entry(monitor=entry_on_mon_at_origin, direction="right")
    # x at edge but y above the monitor -> miss
    assert mouseferry.entry_matches(entry, 1919, -5, 2) is False


def test_entry_matches_left_hit(entry_on_mon_at_origin):
    entry = mouseferry.Entry(monitor=entry_on_mon_at_origin, direction="left")
    assert mouseferry.entry_matches(entry, 1, 500, 2) is True


def test_entry_matches_left_miss_inside_monitor(entry_on_mon_at_origin):
    entry = mouseferry.Entry(monitor=entry_on_mon_at_origin, direction="left")
    # x well inside the monitor -> miss
    assert mouseferry.entry_matches(entry, 500, 500, 2) is False


def test_entry_matches_top_hit(entry_on_mon_at_origin):
    entry = mouseferry.Entry(monitor=entry_on_mon_at_origin, direction="top")
    assert mouseferry.entry_matches(entry, 500, 1, 2) is True


def test_entry_matches_top_miss_outside_x_band(entry_on_mon_at_origin):
    entry = mouseferry.Entry(monitor=entry_on_mon_at_origin, direction="top")
    # y at edge but x to the right of the monitor -> miss
    assert mouseferry.entry_matches(entry, 3000, 1, 2) is False


def test_entry_matches_bottom_hit(entry_on_mon_at_origin):
    entry = mouseferry.Entry(monitor=entry_on_mon_at_origin, direction="bottom")
    assert mouseferry.entry_matches(entry, 500, 1079, 2) is True


def test_entry_matches_bottom_miss_inside_monitor(entry_on_mon_at_origin):
    entry = mouseferry.Entry(monitor=entry_on_mon_at_origin, direction="bottom")
    # y well inside the monitor -> miss
    assert mouseferry.entry_matches(entry, 500, 500, 2) is False


def test_entry_matches_unknown_direction_raises(entry_on_mon_at_origin):
    entry = mouseferry.Entry(monitor=entry_on_mon_at_origin, direction="diagonal")
    with pytest.raises(ValueError, match="unknown direction"):
        mouseferry.entry_matches(entry, 0, 0, 2)
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `/home/mattabott/.local/bin/uvx pytest tests/test_monitor.py -v`
Expected: 9 new tests FAIL with `AttributeError: ... entry_matches`.

- [ ] **Step 3.3: Implement `entry_matches`**

In `mouseferry`, immediately below `direction_return_config` (and its `_DIRECTION_RETURN_CONFIG` constant), add:
```python
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
```

- [ ] **Step 3.4: Run tests**

Run: `/home/mattabott/.local/bin/uvx pytest tests/test_monitor.py -v`
Expected: all tests pass (38 + 9 = 47 passed).

- [ ] **Step 3.5: Commit**

```bash
git add mouseferry tests/test_monitor.py
git commit -m "feat: add entry_matches for per-direction 2D edge detection"
```

---

## Task 4: Refactor `MouseFerry` class around `entries`/`return_mon` (single-entry path only; no CLI change yet)

**Goal of this task:** Internal state refactor. `self.target_mon`/`self.edge`/`self._return_sign` (init-time) are removed. The class now stores `self.entries: list[Entry]` (a 1-element list in single-entry mode), `self.return_mon: Monitor`, `self.multi_entry: bool`, and sets `self._return_axis`/`self._return_sign` per-entry at `switch_to_android` time. Behavior is unchanged from v0.1.1 — this is pure refactor.

**Files:**
- Modify: `mouseferry` (the `MouseFerry` class + `main_loop` + all method signatures that changed)

No new tests in this task — the class is exercised by manual smoke test at the end of Task 7. The pure helpers added in Tasks 1-3 are what make the refactor safe.

- [ ] **Step 4.1: Update `MouseFerry.__init__`**

In `mouseferry`, find the `MouseFerry.__init__` method. Find the following block (the current v0.1.1 monitor resolution + startup prints section):

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

Replace with:
```python
        # Monitor snapshot: taken once at startup, used for edge detection.
        self.monitors = parse_xrandr()
        if not self.monitors:
            print(f"[{APP_NAME}] ERROR: cannot query xrandr (DISPLAY may be unavailable). "
                  f"mouseferry requires a running X session.")
            sys.exit(1)

        cursor_pos = get_mouse_pos()
        self.multi_entry = False  # set to True in Task 5 when cli_entries is non-empty

        # Single-entry (v0.1.1) path: read edge + monitor from config.
        monitor_spec = config.get("general", "monitor", fallback="primary").strip() or "primary"
        target_mon, fallback_reason = resolve_target(
            self.monitors, monitor_spec, cursor_pos
        )
        edge = config.get("general", "edge", fallback="left").strip() or "left"
        if edge not in ("left", "right"):
            print(f"[{APP_NAME}] ERROR: invalid edge '{edge}' in config "
                  f"(single-entry mode supports only 'left' or 'right'; "
                  f"use --entry for 'top'/'bottom').")
            sys.exit(1)
        self.entries = [Entry(target_mon, edge)]
        self.return_mon = target_mon

        self._active_entry = None
        self._return_axis = None  # set at switch_to_android time
        # self._return_sign is now set per-entry in switch_to_android, not here

        self.android_w, self.android_h = get_android_screen(self.serial)
```

Also remove the legacy `self._return_sign` initialization. Find the line `self._return_sign = 1 if self.edge == "left" else -1` (earlier in `__init__`, around the `self._recent_dx` block) and delete it. Also remove the comment `# Return direction: +1 = rightward (tablet on left), -1 = leftward (tablet on right)` which precedes it.

- [ ] **Step 4.2: Rename `self._recent_dx` → `self._recent_d`**

The `self._recent_dx = []` line in `__init__` (inside the evdev tracking state initialization block) should be renamed to `self._recent_d = []`. This makes the name axis-agnostic since we now track whichever axis the current entry dictates.

- [ ] **Step 4.3: Update the startup print block**

Find the existing startup prints in `__init__` (the block printing `Mouse:`, `Monitors detected:`, `Target monitor:`, etc.) and replace with:
```python
        print(f"[{APP_NAME}] Mouse: {dev.name}")
        detected = ", ".join(
            f"{m.name} ({'primary ' if m.primary else ''}{m.w}x{m.h}+{m.x}+{m.y})"
            for m in self.monitors
        )
        print(f"[{APP_NAME}] Monitors detected: {detected}")
        if fallback_reason:
            print(f"[{APP_NAME}] WARNING: {fallback_reason}")
        e = self.entries[0]
        t = e.monitor
        print(f"[{APP_NAME}] Target monitor: {t.name} ({t.w}x{t.h}+{t.x}+{t.y})")
        print(f"[{APP_NAME}] Android: {self.android_w}x{self.android_h}")
        print(f"[{APP_NAME}] Edge:    {e.direction}")
        print(f"[{APP_NAME}] Ready — move the mouse to the {e.direction} edge of {t.name} to ferry over.")
        log(f"start mouse={dev.name} edge={e.direction} "
            f"target={t.name} geom={t.w}x{t.h}+{t.x}+{t.y} "
            f"android={self.android_w}x{self.android_h} fallback={fallback_reason or 'none'}")
```

This preserves the v0.1.1 output format verbatim but sources the values from `self.entries[0]` instead of the removed `self.target_mon`/`self.edge`.

- [ ] **Step 4.4: Rewrite `_at_edge` → `_edge_match`**

Find the method `_at_edge`:
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

Replace with:
```python
    def _edge_match(self, x, y):
        """Return the matching Entry if (x, y) is at any entry's edge, else None."""
        for entry in self.entries:
            if entry_matches(entry, x, y, self.threshold):
                return entry
        return None
```

- [ ] **Step 4.5: Update `main_loop` to use `_edge_match`**

Find in `main_loop`:
```python
                    x, y = get_mouse_pos()
                    if self._at_edge(x, y):
                        self.switch_to_android()
```

Replace with:
```python
                    x, y = get_mouse_pos()
                    entry = self._edge_match(x, y)
                    if entry:
                        self.switch_to_android(entry)
```

- [ ] **Step 4.6: Update `switch_to_android` signature and body**

Find the method `switch_to_android`:
```python
    def switch_to_android(self):
        if self.active:
            return
        # ... existing body ...
```

Update the signature to accept `entry`, and inside the body (after the scrcpy startup logic, in the spot where the tracker was previously activated), compute the return axis/sign from the entry:

```python
    def switch_to_android(self, entry):
        if self.active:
            return
        # ... existing scrcpy startup + window activation code unchanged ...

        self._active_entry = entry
        import evdev
        axis_letter, sign = direction_return_config(entry.direction)
        self._return_axis = (evdev.ecodes.REL_X if axis_letter == "X"
                             else evdev.ecodes.REL_Y)
        self._return_sign = sign

        # ... existing tracker activation (self._recent_d = [], etc.) unchanged ...
        # NOTE: self._recent_d replaces the old self._recent_dx name.
```

Find any lines in `switch_to_android` that still reference `self._recent_dx` and rename to `self._recent_d`.

- [ ] **Step 4.7: Update `_track_loop` to use `self._return_axis` and `self._recent_d`**

Find in `_track_loop`:
```python
                    if event.type == evdev.ecodes.EV_REL and event.code == evdev.ecodes.REL_X:
                        now = time.time()
                        if now - self._track_started < self.CAPTURE_SETTLE:
                            continue
                        self._recent_dx.append((now, event.value))
                        cutoff = now - self.RETURN_WINDOW
                        self._recent_dx = [e for e in self._recent_dx if e[0] > cutoff]
                        # Net movement in the return direction
                        net = sum(v for _, v in self._recent_dx) * self._return_sign
                        if net >= self.RETURN_NET_THRESHOLD:
                            log(f"RETURN! net={net}")
                            self._want_release = True
                            self._track_active = False
```

Replace with:
```python
                    if event.type == evdev.ecodes.EV_REL and event.code == self._return_axis:
                        now = time.time()
                        if now - self._track_started < self.CAPTURE_SETTLE:
                            continue
                        self._recent_d.append((now, event.value))
                        cutoff = now - self.RETURN_WINDOW
                        self._recent_d = [e for e in self._recent_d if e[0] > cutoff]
                        # Net movement in the return direction
                        net = sum(v for _, v in self._recent_d) * self._return_sign
                        if net >= self.RETURN_NET_THRESHOLD:
                            log(f"RETURN! net={net}")
                            self._want_release = True
                            self._track_active = False
```

(Two changes: `evdev.ecodes.REL_X` → `self._return_axis`; `self._recent_dx` → `self._recent_d`.)

- [ ] **Step 4.8: Update `_release_to_desktop` to use `self.entries[0]` in single-entry mode**

Find in `_release_to_desktop`:
```python
        margin = 50
        m = self.target_mon
        cy = m.y + m.h // 2
        if self.edge == "left":
            warp_mouse(m.x + margin, cy)
        else:
            warp_mouse(m.x + m.w - margin, cy)
```

Replace with:
```python
        margin = 50
        # Single-entry (v0.1.1): lateral warp on the entry's edge.
        # Multi-entry branching is added in Task 5.
        e = self.entries[0]
        m = e.monitor
        cy = m.y + m.h // 2
        if e.direction == "left":
            warp_mouse(m.x + margin, cy)
        else:
            warp_mouse(m.x + m.w - margin, cy)

        self._active_entry = None
```

The `self._active_entry = None` clears the per-ferry state, which will matter when Task 5 enables multi-entry mode.

- [ ] **Step 4.9: Verify no stale references remain**

Run:
```bash
cd /home/mattabott/Documents/mouseferry
grep -n "self\.target_mon\|self\.edge\|self\._recent_dx\|self\._return_sign\s*=\s*1 if" mouseferry
```
Expected: no hits.

If any hit appears, edit them. In particular verify:
- `self.target_mon` not referenced anywhere (removed entirely; `self.entries[0].monitor` is the replacement)
- `self.edge` not referenced (replaced by `self.entries[0].direction`)
- `self._recent_dx` fully renamed to `self._recent_d`
- The one-line `self._return_sign = 1 if self.edge == "left" else -1` (init-time default) is deleted; `self._return_sign` only appears inside `switch_to_android` and `_track_loop`

- [ ] **Step 4.10: Verify tests + lint still green**

Run:
```bash
/home/mattabott/.local/bin/uvx ruff check /home/mattabott/Documents/mouseferry/mouseferry
/home/mattabott/.local/bin/uvx pytest /home/mattabott/Documents/mouseferry/tests/ -v
```
Expected: `All checks passed!` and **47 passed** (the 47 unit tests are on pure functions, which this task did not touch).

- [ ] **Step 4.11: Verify `python3 mouseferry --help` still works**

Run: `python3 /home/mattabott/Documents/mouseferry/mouseferry --help`
Expected: same help output as v0.1.1 (no changes to argparse in this task — Task 5 will add the multi-entry group). Should exit cleanly.

- [ ] **Step 4.12: Commit**

```bash
git add mouseferry
git commit -m "refactor: unify MouseFerry around self.entries + per-entry return axis"
```

---

## Task 5: Multi-entry CLI (`--entry`, `--return`) + multi-entry runtime branch

**Files:**
- Modify: `mouseferry` (argparse in `main()`, `MouseFerry.__init__`, `_release_to_desktop`)

- [ ] **Step 5.1: Update `MouseFerry.__init__` signature to accept CLI entries and return**

Find the `__init__` signature:
```python
    def __init__(self, config):
```

Replace with:
```python
    def __init__(self, config, cli_entries=None, cli_return=None):
```

Then, in `__init__` (right after the `self.monitors = parse_xrandr()` block with its error-exit guard, but BEFORE the `monitor_spec = config.get(...)` line), insert the multi-entry branch and restructure:

Find this block (from Task 4):
```python
        cursor_pos = get_mouse_pos()
        self.multi_entry = False  # set to True in Task 5 when cli_entries is non-empty

        # Single-entry (v0.1.1) path: read edge + monitor from config.
        monitor_spec = config.get("general", "monitor", fallback="primary").strip() or "primary"
        target_mon, fallback_reason = resolve_target(
            self.monitors, monitor_spec, cursor_pos
        )
        edge = config.get("general", "edge", fallback="left").strip() or "left"
        if edge not in ("left", "right"):
            print(f"[{APP_NAME}] ERROR: invalid edge '{edge}' in config "
                  f"(single-entry mode supports only 'left' or 'right'; "
                  f"use --entry for 'top'/'bottom').")
            sys.exit(1)
        self.entries = [Entry(target_mon, edge)]
        self.return_mon = target_mon

        self._active_entry = None
        self._return_axis = None  # set at switch_to_android time
```

Replace with:
```python
        cursor_pos = get_mouse_pos()
        self.multi_entry = bool(cli_entries)
        fallback_reason = None  # used by startup print in single-entry mode

        if self.multi_entry:
            # Multi-entry (v0.2+): --entry pairs come from CLI.
            self.entries = []
            self._entry_warnings = []  # (collected for startup print after mouse is ready)
            for raw in cli_entries:
                spec, direction = parse_entry_spec(raw)
                mon, reason = resolve_target(self.monitors, spec, cursor_pos)
                if reason:
                    self._entry_warnings.append(f"entry '{raw}': {reason}")
                self.entries.append(Entry(mon, direction))

            if cli_return:
                rmon, rreason = resolve_target(self.monitors, cli_return, cursor_pos)
                if rreason:
                    self._entry_warnings.append(f"return '{cli_return}': {rreason}")
                self.return_mon = rmon
            else:
                self.return_mon = self.entries[0].monitor
        else:
            # Single-entry (v0.1.1) path: read edge + monitor from config.
            self._entry_warnings = []
            monitor_spec = config.get("general", "monitor", fallback="primary").strip() or "primary"
            target_mon, fallback_reason = resolve_target(
                self.monitors, monitor_spec, cursor_pos
            )
            edge = config.get("general", "edge", fallback="left").strip() or "left"
            if edge not in ("left", "right"):
                print(f"[{APP_NAME}] ERROR: invalid edge '{edge}' in config "
                      f"(single-entry mode supports only 'left' or 'right'; "
                      f"use --entry for 'top'/'bottom').")
                sys.exit(1)
            self.entries = [Entry(target_mon, edge)]
            self.return_mon = target_mon

        self._active_entry = None
        self._return_axis = None
```

- [ ] **Step 5.2: Update startup print block to handle multi-entry**

Find the startup print block from Task 4 (`print(f"[{APP_NAME}] Mouse: ..."`) and replace the whole block with:
```python
        print(f"[{APP_NAME}] Mouse: {dev.name}")
        detected = ", ".join(
            f"{m.name} ({'primary ' if m.primary else ''}{m.w}x{m.h}+{m.x}+{m.y})"
            for m in self.monitors
        )
        print(f"[{APP_NAME}] Monitors detected: {detected}")
        for w in self._entry_warnings:
            print(f"[{APP_NAME}] WARNING: {w}")
        if fallback_reason:
            print(f"[{APP_NAME}] WARNING: {fallback_reason}")

        if self.multi_entry:
            print(f"[{APP_NAME}] Entries:")
            for e in self.entries:
                m = e.monitor
                print(f"  - {m.name} ({e.direction})")
            r = self.return_mon
            print(f"[{APP_NAME}] Return: {r.name}")
            print(f"[{APP_NAME}] Android: {self.android_w}x{self.android_h}")
            print(f"[{APP_NAME}] Ready — ferry triggers from any configured edge.")
            log(f"start mouse={dev.name} mode=multi "
                f"entries={[(e.monitor.name, e.direction) for e in self.entries]} "
                f"return={r.name} android={self.android_w}x{self.android_h}")
        else:
            e = self.entries[0]
            t = e.monitor
            print(f"[{APP_NAME}] Target monitor: {t.name} ({t.w}x{t.h}+{t.x}+{t.y})")
            print(f"[{APP_NAME}] Android: {self.android_w}x{self.android_h}")
            print(f"[{APP_NAME}] Edge:    {e.direction}")
            print(f"[{APP_NAME}] Ready — move the mouse to the {e.direction} edge of {t.name} to ferry over.")
            log(f"start mouse={dev.name} edge={e.direction} "
                f"target={t.name} geom={t.w}x{t.h}+{t.x}+{t.y} "
                f"android={self.android_w}x{self.android_h} fallback={fallback_reason or 'none'}")
```

- [ ] **Step 5.3: Update `_release_to_desktop` to branch on multi-entry**

Find the lateral-warp block from Task 4:
```python
        margin = 50
        # Single-entry (v0.1.1): lateral warp on the entry's edge.
        # Multi-entry branching is added in Task 5.
        e = self.entries[0]
        m = e.monitor
        cy = m.y + m.h // 2
        if e.direction == "left":
            warp_mouse(m.x + margin, cy)
        else:
            warp_mouse(m.x + m.w - margin, cy)

        self._active_entry = None
```

Replace with:
```python
        if self.multi_entry:
            # Multi-entry: warp to center of return monitor (unambiguous, safe).
            m = self.return_mon
            warp_mouse(m.x + m.w // 2, m.y + m.h // 2)
        else:
            # Single-entry (v0.1.1): lateral warp on the entry's edge.
            margin = 50
            e = self.entries[0]
            m = e.monitor
            cy = m.y + m.h // 2
            if e.direction == "left":
                warp_mouse(m.x + margin, cy)
            else:
                warp_mouse(m.x + m.w - margin, cy)

        self._active_entry = None
```

- [ ] **Step 5.4: Add `--entry` and `--return` CLI flags**

In `main()`, find the existing `parser.add_argument_group("introspection")` block. Right AFTER the introspection group (and right BEFORE `args = parser.parse_args()`), insert:
```python
    multi = parser.add_argument_group(
        "multi-entry (v0.2+, disables --left/--right/--monitor + config edge/monitor)")
    multi.add_argument("--entry", metavar="SPEC", action="append", default=[],
                       help="monitor:direction pair, repeatable. "
                            "monitor: primary | auto-from-cursor | <xrandr-name> | <1-based index>. "
                            "direction: left | right | top | bottom. "
                            "Example: --entry primary:right --entry 3:bottom")
    multi.add_argument("--return", metavar="MONITOR", dest="return_monitor", default=None,
                       help="return monitor (default: first --entry's monitor). "
                            "Accepts the same monitor values as --entry (without :direction).")
```

- [ ] **Step 5.5: Update the `--help` epilog to include a multi-entry example**

Find the `epilog` string in `main()`:
```python
    epilog = """\
examples:
  mouseferry --left                              # use config defaults
  mouseferry --right --monitor eDP-1             # override by xrandr name
  mouseferry --right --monitor 1                 # override by 1-based index (see --list-monitors)
  mouseferry --right --monitor auto-from-cursor  # pick monitor under cursor now
  mouseferry --list-monitors                     # show what's available

config file: ~/.config/mouseferry/config.ini
docs:        https://github.com/mattabott/mouseferry
"""
```

Replace with:
```python
    epilog = """\
examples:
  mouseferry --left                                        # v0.1.1 single-entry from config
  mouseferry --right --monitor eDP-1                       # v0.1.1 override by xrandr name
  mouseferry --right --monitor 1                           # v0.1.1 override by 1-based index
  mouseferry --right --monitor auto-from-cursor            # v0.1.1 monitor under cursor
  mouseferry --entry primary:right --entry 3:bottom        # v0.2+ multi-entry
  mouseferry --entry 1:right --entry 3:bottom --return 1   # v0.2+ explicit return
  mouseferry --list-monitors                               # show what's available

config file: ~/.config/mouseferry/config.ini
docs:        https://github.com/mattabott/mouseferry
"""
```

- [ ] **Step 5.6: Handle `args.entry` in `main()` after parse**

Find in `main()`, AFTER `args = parser.parse_args()` and AFTER the `if args.list_monitors: list_monitors_action()` short-circuit, the existing section that handles `args.edge` / `args.monitor`:
```python
    # CLI flags override config
    if not config.has_section("general"):
        config.add_section("general")
    if args.edge:
        config.set("general", "edge", args.edge)
    if args.monitor:
        config.set("general", "monitor", args.monitor)
```

Replace with:
```python
    # CLI flags override config (single-entry mode only)
    if not config.has_section("general"):
        config.add_section("general")

    if args.entry:
        # Multi-entry mode active: warn about legacy flags being ignored.
        conflicts = []
        if args.edge:
            conflicts.append(f"--{args.edge}")
        if args.monitor:
            conflicts.append("--monitor")
        if conflicts:
            print(f"[{APP_NAME}] WARNING: {', '.join(conflicts)} "
                  f"ignored because --entry is in use.")
    else:
        if args.edge:
            config.set("general", "edge", args.edge)
        if args.monitor:
            config.set("general", "monitor", args.monitor)
```

- [ ] **Step 5.7: Pass `--entry`/`--return` to `MouseFerry` constructor**

Find at the very end of `main()`:
```python
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    MouseFerry(config).run()
```

Replace with:
```python
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        ferry = MouseFerry(config,
                           cli_entries=(args.entry or None),
                           cli_return=args.return_monitor)
    except ValueError as e:
        # parse_entry_spec raises ValueError on malformed --entry
        print(f"[{APP_NAME}] ERROR: {e}")
        sys.exit(2)
    ferry.run()
```

- [ ] **Step 5.8: Verify**

Run:
```bash
/home/mattabott/.local/bin/uvx ruff check /home/mattabott/Documents/mouseferry/mouseferry
/home/mattabott/.local/bin/uvx pytest /home/mattabott/Documents/mouseferry/tests/ -v
python3 /home/mattabott/Documents/mouseferry/mouseferry --help
```

Expected:
- `All checks passed!`
- **47 passed** (class refactor doesn't break unit tests)
- `--help` output now shows a fourth argument group `multi-entry (v0.2+, ...)` with `--entry` and `--return`, plus the updated `examples:` epilog

Also verify the error path:
```bash
python3 /home/mattabott/Documents/mouseferry/mouseferry --entry primary:sideways
```
Expected: printed error containing `"invalid direction 'sideways'"`, then exit code 2 (check with `echo $?`).

- [ ] **Step 5.9: Commit**

```bash
git add mouseferry
git commit -m "feat: add --entry and --return CLI for multi-entry mode (v0.2)"
```

---

## Task 6: Update README with multi-entry mode documentation

**Files:**
- Modify: `README.md` (append subsection to the existing "Multi-monitor setups" section)

- [ ] **Step 6.1: Insert new subsection**

In `README.md`, find the existing `## Multi-monitor setups` section. At the END of that section (right before the next `## ` heading, which is `## How it works, under the hood`), insert a new subsection:

```markdown
### Multi-entry mode (v0.2+)

For setups where the Android device is adjacent to **more than one monitor at once** — for example a tablet wedged so it's reachable both from the right edge of your laptop AND from the bottom edge of a monitor above it — you can configure multiple entry edges, each with its own direction:

```bash
# Ferry triggers from the right edge of the primary OR the bottom edge of monitor 3.
# Return always lands on the primary.
mouseferry --entry primary:right --entry 3:bottom

# Equivalent with indexes from --list-monitors:
mouseferry --entry 1:right --entry 3:bottom --return 1

# All four directions are supported in multi-entry mode:
mouseferry --entry 1:right --entry 2:top --entry 3:bottom --return 1
```

The format for `--entry` is `MONITOR:DIRECTION`, where:

- **MONITOR**: any value accepted by the `monitor` config key (`primary`, `auto-from-cursor`, xrandr name like `eDP-1`, or a 1-based index from `--list-monitors`).
- **DIRECTION**: `left`, `right`, `top`, or `bottom`.

The `--return` flag picks the monitor where the cursor lands on sweep-back. Defaults to the monitor of the first `--entry` if omitted.

**Multi-entry is CLI-only by design** — there's no config-file equivalent. The idea is that mobile setups change often and the CLI forces you to make the choice explicit at every launch. If you have recurring setups, use shell aliases:

```bash
alias mf-office='mouseferry --entry 1:right --entry 3:bottom --return 1'
alias mf-coffee='mouseferry --entry 1:right'
```

**When `--entry` is present:**

- The `edge` and `monitor` keys in `config.ini` are ignored
- The v0.1.1 flags `--left`, `--right`, `--monitor` are also ignored (a warning is printed if you passed any)
- `top` and `bottom` become valid directions (they're only available via `--entry`, not in single-entry config mode)
- On return, the cursor warps to the **center** of the `--return` monitor, rather than just off a lateral edge

Run `mouseferry --help` for the full flag reference.
```

**Important note about nested code fences:** The insertion above contains three fenced code blocks (` ```bash `, `MONITOR:DIRECTION` reference list, a second ` ```bash ` for aliases). When editing, verify the outer boundaries don't accidentally close an earlier block in the file. Read a few lines before and after your insertion point to confirm.

- [ ] **Step 6.2: Commit**

```bash
git add README.md
git commit -m "docs: document v0.2 multi-entry mode in README"
```

---

## Task 7: Release v0.2.0 — smoke test, tag, push, GitHub release, close issue #1

**Files:** none modified in this task — verification + release only.

- [ ] **Step 7.1: Full local verification**

Run:
```bash
cd /home/mattabott/Documents/mouseferry
/home/mattabott/.local/bin/uvx ruff check mouseferry
/home/mattabott/.local/bin/uvx pytest tests/ -v
python3 mouseferry --help | head -50
```

Expected:
- `All checks passed!`
- **47 passed**
- `--help` output shows four argument groups in order: `direction`, `monitor`, `introspection`, `multi-entry (v0.2+, …)` — plus the updated `examples:` epilog with multi-entry examples

- [ ] **Step 7.2: Reinstall binary to `~/.local/bin/mouseferry` (so CLI tests hit the new code)**

Run:
```bash
install -Dm755 /home/mattabott/Documents/mouseferry/mouseferry /home/mattabott/.local/bin/mouseferry
grep -c "parse_entry_spec\|direction_return_config" /home/mattabott/.local/bin/mouseferry
```

Expected: grep returns >= 2 (both helpers are present in the installed copy).

- [ ] **Step 7.3: Smoke test — `--entry` validation**

Run: `mouseferry --entry primary:sideways`
Expected: printed error like `[mouseferry] ERROR: invalid direction 'sideways' in entry 'primary:sideways': must be one of left/right/top/bottom`, exit code 2 (check with `echo $?`).

Run: `mouseferry --entry primary`
Expected: error `expected MONITOR:DIRECTION`, exit code 2.

- [ ] **Step 7.4: Smoke test — legacy flags + `--entry` together (conflict warning)**

Run: `mouseferry --right --monitor 1 --entry primary:right`
Expected: startup prints a `WARNING: --right, --monitor ignored because --entry is in use.` line, then proceeds in multi-entry mode.

(You can Ctrl-C right after the startup prints — the goal is to verify the warning appears, not to actually ferry.)

- [ ] **Step 7.5: Smoke test — multi-entry on real hardware (user-driven)**

**This step requires the user to test on the real 3-monitor setup.** Controller should pause here and ask the user to run:

```bash
mouseferry --entry primary:right --entry 3:bottom
```

And verify:
1. Startup output includes `Entries:` block listing both entries, and `Return: <primary-name>`
2. Moving the mouse to the right edge of the primary triggers ferry to Android
3. Sweeping the mouse left (horizontal) while on Android returns control, cursor lands at center of primary
4. Moving the mouse to the bottom edge of monitor 3 triggers ferry to Android
5. Sweeping the mouse up (vertical) while on Android returns control, cursor lands at center of primary

If any of these fail, pause and triage before continuing.

- [ ] **Step 7.6: Tag v0.2.0**

Once smoke tests pass:
```bash
cd /home/mattabott/Documents/mouseferry
git log --oneline fe33e3e..HEAD
git tag -a v0.2.0 -m "v0.2.0 — multi-entry mode with per-direction edges"
```

Expected: the git log output shows 6 commits (Task 1-6).

- [ ] **Step 7.7: Push main + tag**

```bash
git push origin main
git push origin v0.2.0
```

- [ ] **Step 7.8: Create GitHub release**

```bash
gh release create v0.2.0 \
  --repo mattabott/mouseferry \
  --title "v0.2.0 — multi-entry mode" \
  --notes "$(cat <<'EOF'
### What's new

- **Multi-entry mode.** Pass `--entry MONITOR:DIRECTION` repeatably on the CLI to ferry from multiple monitor edges to the same Android device. Supports all four directions (`left`/`right`/`top`/`bottom`). Example: `mouseferry --entry primary:right --entry 3:bottom`.
- **`top` and `bottom` as directions.** Previously only `left`/`right` were valid; now `top` and `bottom` work too — but only in multi-entry mode (`--entry`), not via the v0.1.1 config `edge` key. This preserves v0.1.1 single-entry semantics bit-for-bit.
- **`--return MONITOR` flag.** Picks the monitor where the cursor lands on sweep-back. Defaults to the monitor of the first `--entry`.
- **Per-entry return axis.** The tracker detects horizontal sweeps for `left`/`right` entries and vertical sweeps for `top`/`bottom` entries, switching dynamically based on which entry triggered the current ferry.
- **Center-of-monitor warp in multi-entry mode.** Instead of warping the cursor off a lateral edge (v0.1.1 behavior, preserved in single-entry mode), multi-entry returns land at the center of the return monitor — unambiguous regardless of which entry was used.
- **Conflict warning.** `--left`/`--right`/`--monitor` combined with `--entry` now prints a single `WARNING:` line listing what's ignored, then proceeds in multi-entry mode. No hard error — safe for incremental migration.

### Compatibility

- **100% backward compatible.** No `--entry`? Same behavior as v0.1.1.
- Multi-entry is CLI-only by design (no `[entries]` section in `config.ini`). Use shell aliases for recurring setups.
- Single-entry config-driven mode still restricted to `left`/`right` — `top`/`bottom` require `--entry`.

### Tests

- 14 new unit tests (47 total) covering `parse_entry_spec`, `entry_matches`, `direction_return_config`.
- `MouseFerry` class refactor covered by manual smoke tests on the maintainer's 3-monitor setup.

### Closes

- #1 (multi-entry monitors with per-monitor direction)
EOF
)"
```

- [ ] **Step 7.9: Close issue #1**

The release notes reference `Closes #1` but GitHub only auto-closes issues when a PR merges with that keyword, not when a release is cut. Close the issue explicitly:

```bash
gh issue close 1 --repo mattabott/mouseferry \
  --comment "Shipped in [v0.2.0](https://github.com/mattabott/mouseferry/releases/tag/v0.2.0)."
```

- [ ] **Step 7.10: Verify CI green on main**

```bash
sleep 10
gh run list --repo mattabott/mouseferry --limit 3
```

Expected: the most recent run (on the push that included Task 1-6) is `success`. Both `ruff` and `pytest` jobs must be green.

---

## Self-review

**1. Spec coverage**

Walked each Goal, Non-goal, Decision, Interface, and Acceptance Criterion of `docs/specs/2026-04-24-multi-entry-monitors-design.md`:

- Goals (multi-entry, 4 directions, single-return, CLI-only, zero breaking change) → Tasks 1, 3, 4, 5, 6
- Decisions table (9 rows) → all reflected in code: CLI-only (Task 5), `--entry` format with `:` separator (Task 1), default `--return` to first entry (Task 5), legacy flag warning not error (Task 5), center warp for multi (Task 5), lateral warp for single (Task 4), per-active-entry axis (Task 4 step 4.6), shared `return_sensitivity` (no change needed), single-entry restricted to left/right (Task 4 step 4.1)
- Interface (CLI flags, conflict warning, startup output for both modes, `--help` epilog) → Tasks 5, 6
- Implementation (Entry, 3 pure helpers, class state changes, method signatures) → Tasks 1, 2, 3, 4, 5
- Acceptance criteria (10 items) → #1-6 covered by manual smoke test in 7.5; #7 (validation error) by 7.3; #8 (--help) by 7.1; #9-10 (tests green + no regression) by 7.1

No spec gaps.

**2. Placeholder scan**

Searched the plan for placeholder patterns. None present:
- No "TBD" / "TODO" / "implement later"
- No "add appropriate error handling" / "handle edge cases"
- Every code-changing step shows the exact code
- Every grep/command step shows the exact expected output

**3. Type consistency**

Verified identifiers used across tasks:
- `Entry(monitor, direction)` — consistent name and field order in Tasks 1, 3, 4, 5
- `_VALID_DIRECTIONS = ("left", "right", "top", "bottom")` — used in Task 1 (validation) and Task 4 (single-entry guard)
- `parse_entry_spec(raw) -> (spec, direction)` — signature consistent in Task 1 and Task 5 call site
- `entry_matches(entry, x, y, threshold) -> bool` — consistent in Task 3 definition and Task 4 `_edge_match` call site
- `direction_return_config(direction) -> (axis_letter, sign)` — consistent in Task 2 and Task 4 `switch_to_android` call site
- `self.entries: list[Entry]`, `self.return_mon: Monitor`, `self.multi_entry: bool`, `self._active_entry`, `self._return_axis`, `self._return_sign`, `self._recent_d` — all consistent across Tasks 4 and 5
- `cli_entries` and `cli_return` parameter names — consistent in Task 5 step 5.1 constructor and step 5.7 call site

No inconsistencies found.
