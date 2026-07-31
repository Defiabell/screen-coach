import json

import pytest

import region


# --- 坐标换算：AppKit 左下原点 → screencapture 左上原点 -----------------
def test_to_capture_rect_matches_verified_formula():
    """实测过的换算：内建屏高 982，AppKit (1000,100,400,120) → (1000,762,400,120)。"""
    assert region.to_capture_rect(1000.0, 100.0, 400.0, 120.0, 982.0) == (
        1000.0, 762.0, 400.0, 120.0
    )


def test_to_capture_rect_bottom_edge_maps_to_screen_bottom():
    # 贴屏幕底部（y=0）的框，其 top-left y 应为 屏高 - 框高
    assert region.to_capture_rect(0.0, 0.0, 100.0, 50.0, 982.0) == (
        0.0, 932.0, 100.0, 50.0
    )


def test_to_capture_rect_preserves_width_height():
    x, y, w, h = region.to_capture_rect(5.0, 7.0, 111.0, 33.0, 982.0)
    assert (w, h) == (111.0, 33.0)


# --- 钳制：越界/过小/显示器消失 ----------------------------------------
BUILTIN = (0.0, 0.0, 1512.0, 982.0)          # 内建屏可见区域
EXTERNAL = (-185.0, 982.0, 1920.0, 1080.0)   # 外接屏（实测拓扑）


def test_clamp_keeps_a_rect_that_already_fits():
    assert region.clamp_rect(100.0, 100.0, 300.0, 120.0, [BUILTIN]) == (
        100.0, 100.0, 300.0, 120.0
    )


def test_clamp_allows_rect_on_external_screen():
    """故意拖到外接屏是合法的，不该被拉回来。"""
    r = region.clamp_rect(0.0, 1100.0, 400.0, 150.0, [BUILTIN, EXTERNAL])
    assert r == (0.0, 1100.0, 400.0, 150.0)


def test_clamp_falls_back_when_screen_gone():
    """区域原在外接屏，拔线后只剩内建屏 → 落回内建屏内。"""
    x, y, w, h = region.clamp_rect(0.0, 1100.0, 400.0, 150.0, [BUILTIN])
    assert BUILTIN[0] <= x and x + w <= BUILTIN[0] + BUILTIN[2]
    assert BUILTIN[1] <= y and y + h <= BUILTIN[1] + BUILTIN[3]


def test_clamp_enforces_minimum_size():
    _, _, w, h = region.clamp_rect(100.0, 100.0, 10.0, 5.0, [BUILTIN])
    assert w >= region.MIN_W
    assert h >= region.MIN_H


def test_clamp_pulls_back_rect_hanging_off_right_edge():
    x, y, w, h = region.clamp_rect(1400.0, 100.0, 400.0, 120.0, [BUILTIN])
    assert x + w <= BUILTIN[0] + BUILTIN[2]


# --- 持久化 -------------------------------------------------------------
def test_save_then_load_roundtrip(monkeypatch, tmp_path):
    p = tmp_path / "region.json"
    monkeypatch.setattr(region, "STATE_PATH", p)
    region.save_rect(11.0, 22.0, 333.0, 44.0)
    assert region.load_rect() == (11.0, 22.0, 333.0, 44.0)


def test_load_returns_none_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(region, "STATE_PATH", tmp_path / "nope.json")
    assert region.load_rect() is None


def test_load_returns_none_on_corrupt_file(monkeypatch, tmp_path):
    p = tmp_path / "region.json"
    p.write_text("not json at all", encoding="utf-8")
    monkeypatch.setattr(region, "STATE_PATH", p)
    assert region.load_rect() is None


# --- 内建屏必须排第一（clamp_rect 回落到 screens[0]） ---------------------
def test_visible_frames_puts_builtin_display_first(monkeypatch):
    """clamp_rect falls back to screens[0], so the built-in display must lead.

    NSScreen.screens() order only guarantees the menu-bar screen first, which is
    the external monitor when the user makes it primary — and pulling an orphaned
    region onto the external display is exactly the failure this feature exists
    to prevent.
    """
    class FakeScreen:
        def __init__(self, ox, oy, w, h):
            self._f = type("R", (), {
                "origin": type("P", (), {"x": ox, "y": oy})(),
                "size": type("S", (), {"width": w, "height": h})(),
            })()

        def frame(self):
            return self._f

        def visibleFrame(self):
            return self._f

    # external listed FIRST (as happens when it's the primary display)
    fake = [FakeScreen(-185.0, 982.0, 1920.0, 1080.0), FakeScreen(0.0, 0.0, 1512.0, 982.0)]

    # NOTE on monkeypatch target: NSScreen is a bridged ObjC class whose
    # metaclass blocks clean patch/restore of its native `screens` selector —
    # verified empirically: `monkeypatch.setattr(region.NSScreen, "screens",
    # staticmethod(lambda: fake))` (as literally given in the task brief)
    # silently no-ops and the real NSScreen.screens() still runs; overriding
    # with `classmethod(...)` instead does take effect, but then cannot be
    # cleanly restored (`NSScreen.screens = <original>` raises `TypeError:
    # Assigning native selectors is not supported`), and pytest's own
    # monkeypatch teardown crashes with `AttributeError: Cannot remove
    # selector 'screens' in 'NSScreen'` because `NSScreen.__dict__` never
    # actually holds a `screens` entry to restore from — permanently
    # corrupting NSScreen.screens() for the rest of the test process either
    # way. So instead of touching the real AppKit NSScreen class, swap the
    # module-level `NSScreen` name that `region._visible_frames()` actually
    # looks up at call time — a plain module attribute, freely and safely
    # reversible by monkeypatch.
    class FakeNSScreen:
        @staticmethod
        def screens():
            return fake

    monkeypatch.setattr(region, "NSScreen", FakeNSScreen)
    frames = region._visible_frames()
    assert frames[0] == (0.0, 0.0, 1512.0, 982.0), "built-in display must be first"


# --- capture(): 藏框 → 等重绘 → 截图 → 恢复 -------------------------------
def test_capture_raises_when_no_region(monkeypatch, tmp_path):
    monkeypatch.setattr(region, "STATE_PATH", tmp_path / "none.json")
    monkeypatch.setattr(region, "_window", None)
    with pytest.raises(region.NoRegionError):
        region.capture()


def test_capture_converts_coords_and_hides_frame(monkeypatch, tmp_path):
    """capture() 必须：先藏框 → 用换算后的坐标截图 → 再恢复框。"""
    monkeypatch.setattr(region, "STATE_PATH", tmp_path / "region.json")
    region.save_rect(1000.0, 100.0, 400.0, 120.0)
    monkeypatch.setattr(region, "_window", None)
    monkeypatch.setattr(region, "builtin_height", lambda: 982.0)

    order = []
    monkeypatch.setattr(region, "_set_frame_hidden",
                        lambda hidden: order.append("hide" if hidden else "showback"))

    seen = {}

    def fake_capture_rect(x, y, w, h):
        order.append("capture")
        seen["rect"] = (x, y, w, h)
        return "/tmp/fake.png"

    monkeypatch.setattr(region, "_capture_rect", fake_capture_rect)

    assert region.capture() == "/tmp/fake.png"
    assert order == ["hide", "capture", "showback"]
    # 982 - (100 + 120) = 762
    assert seen["rect"] == (1000.0, 762.0, 400.0, 120.0)


def test_capture_restores_frame_even_on_failure(monkeypatch, tmp_path):
    """截图失败也必须恢复边框——否则一次失败就把框永久藏没。"""
    monkeypatch.setattr(region, "STATE_PATH", tmp_path / "region.json")
    region.save_rect(10.0, 10.0, 200.0, 100.0)
    monkeypatch.setattr(region, "_window", None)
    monkeypatch.setattr(region, "builtin_height", lambda: 982.0)

    order = []
    monkeypatch.setattr(region, "_set_frame_hidden",
                        lambda hidden: order.append("hide" if hidden else "showback"))

    def boom(x, y, w, h):
        raise RuntimeError("screencapture blew up")

    monkeypatch.setattr(region, "_capture_rect", boom)

    with pytest.raises(RuntimeError):
        region.capture()
    assert order == ["hide", "showback"]
