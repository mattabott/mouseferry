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


def test_parse_query_empty_input():
    assert mouseferry.parse_xrandr_query("") == []
