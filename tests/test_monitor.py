import pytest

from tests.conftest import mouseferry


def test_module_imports():
    assert hasattr(mouseferry, "MouseFerry")


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


QUERY_CONNECTED_NO_MODE = """\
HDMI-2 connected (normal left inverted right x axis y axis)
   1920x1080     60.00
"""


def test_parse_query_skips_connected_without_mode():
    """A `connected` line without resolution (disabled output) must not produce a Monitor."""
    assert mouseferry.parse_xrandr_query(QUERY_CONNECTED_NO_MODE) == []


def test_parse_query_empty_input():
    assert mouseferry.parse_xrandr_query("") == []


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
    assert target.name == "HDMI-1"
    assert "no primary" in reason


def test_resolve_auto_from_cursor_picks_monitor_under_cursor(three_mons):
    target, reason = mouseferry.resolve_target(three_mons, "auto-from-cursor", (2500, 500))
    assert target.name == "DP-2"
    assert reason is None


def test_resolve_auto_from_cursor_on_primary(three_mons):
    target, reason = mouseferry.resolve_target(three_mons, "auto-from-cursor", (500, 1500))
    assert target.name == "eDP-1"


def test_resolve_auto_from_cursor_off_all_monitors(three_mons):
    target, reason = mouseferry.resolve_target(three_mons, "auto-from-cursor", (5000, 5000))
    assert target.name == "eDP-1"
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


def test_resolve_numeric_index_first(three_mons):
    target, reason = mouseferry.resolve_target(three_mons, "1", (0, 0))
    assert target.name == "HDMI-1"  # first in fixture
    assert reason is None


def test_resolve_numeric_index_middle(three_mons):
    target, reason = mouseferry.resolve_target(three_mons, "2", (0, 0))
    assert target.name == "eDP-1"
    assert reason is None


def test_resolve_numeric_index_last(three_mons):
    target, reason = mouseferry.resolve_target(three_mons, "3", (0, 0))
    assert target.name == "DP-2"
    assert reason is None


def test_resolve_numeric_index_zero_is_out_of_range(three_mons):
    """0 is NOT a valid 1-based index; must fall back."""
    target, reason = mouseferry.resolve_target(three_mons, "0", (0, 0))
    assert target.name == "eDP-1"  # primary fallback
    assert "out of range" in reason
    assert "'0'" in reason


def test_resolve_numeric_index_too_high_falls_back_to_primary(three_mons):
    target, reason = mouseferry.resolve_target(three_mons, "99", (0, 0))
    assert target.name == "eDP-1"
    assert "99" in reason and "out of range" in reason


def test_resolve_numeric_index_out_of_range_no_primary(three_mons):
    no_primary = [m._replace(primary=False) for m in three_mons]
    target, reason = mouseferry.resolve_target(no_primary, "99", (0, 0))
    assert target.name == "HDMI-1"
    assert "first available" in reason


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


def test_entry_matches_threshold_zero_exact_edge(entry_on_mon_at_origin):
    e = mouseferry.Entry(entry_on_mon_at_origin, "left")
    assert mouseferry.entry_matches(e, 0, 500, 0) is True     # exactly on edge
    assert mouseferry.entry_matches(e, 1, 500, 0) is False    # one pixel inside


def test_entry_matches_threshold_inclusive_boundary(entry_on_mon_at_origin):
    e = mouseferry.Entry(entry_on_mon_at_origin, "left")
    assert mouseferry.entry_matches(e, 2, 500, 2) is True     # x == m.x + threshold
    assert mouseferry.entry_matches(e, 3, 500, 2) is False    # x == m.x + threshold + 1


def test_parse_entry_spec_strips_whitespace():
    assert mouseferry.parse_entry_spec(" primary : right ") == ("primary", "right")


# --- entry_matches: cursor outside bounding box must NOT match ---
# Regression: before the fix, directions only checked the perpendicular band
# plus a one-sided inequality on the edge axis. A cursor far past the edge
# (on an adjacent monitor that happened to share the perpendicular band)
# would match as if it were ON that edge. Ships real-world bug spotted in
# v0.2.0-rc where --entry DisplayPort-2:bottom matched on cursor over a
# different monitor located below DisplayPort-2.


def test_entry_matches_right_miss_cursor_past_monitor(entry_on_mon_at_origin):
    entry = mouseferry.Entry(entry_on_mon_at_origin, "right")
    # Cursor 1000px past the monitor's right edge (on a hypothetical adjacent monitor)
    assert mouseferry.entry_matches(entry, 3000, 500, 2) is False


def test_entry_matches_left_miss_cursor_past_monitor(entry_on_mon_at_origin):
    entry = mouseferry.Entry(entry_on_mon_at_origin, "left")
    # Cursor to the left of the monitor (negative X)
    assert mouseferry.entry_matches(entry, -100, 500, 2) is False


def test_entry_matches_bottom_miss_cursor_past_monitor(entry_on_mon_at_origin):
    entry = mouseferry.Entry(entry_on_mon_at_origin, "bottom")
    # Cursor below the monitor (Y past m.y + m.h). This is the specific
    # v0.2.0-rc bug: cursor on a monitor located below the target would match.
    assert mouseferry.entry_matches(entry, 500, 3000, 2) is False


def test_entry_matches_top_miss_cursor_past_monitor(entry_on_mon_at_origin):
    entry = mouseferry.Entry(entry_on_mon_at_origin, "top")
    # Cursor above the monitor (Y negative, past the top edge)
    assert mouseferry.entry_matches(entry, 500, -100, 2) is False
