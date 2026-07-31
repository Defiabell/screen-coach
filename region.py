"""A persistent, always-on-top framing rectangle plus the pixels inside it.

Deliberately knows nothing about analyzer/render/API keys — it deals only in
geometry and pixels, so it can be tested with no GUI, no Screen Recording
permission and no API key. app.py decides what to do with the image.

The window's own frame IS the region definition: there is no second copy of the
coordinates to drift out of sync with what's drawn.
"""
from __future__ import annotations

import json
import time
import traceback
from pathlib import Path

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSEvent,
    NSEventMaskKeyDown,
    NSFloatingWindowLevel,
    NSScreen,
    NSView,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
)
from Foundation import NSMakeRect, NSPoint

import capture as _capture_mod

MIN_W = 80.0            # narrower than this can't hold a full sentence
MIN_H = 40.0
DEFAULT_SIZE = (600.0, 200.0)

STATE_PATH = (Path.home() / "Library" / "Application Support"
              / "Screen Coach" / "region.json")


def to_capture_rect(x: float, y: float, w: float, h: float,
                    builtin_height: float) -> tuple[float, float, float, float]:
    """Convert an AppKit rect to screencapture -R coordinates.

    AppKit measures y upward from the bottom-left of the built-in display;
    `screencapture -R` measures it downward from that display's top. Verified
    empirically: built-in 1512x982, AppKit (1000,100,400,120) captures the same
    pixels as -R 1000,762,400,120.
    """
    return (x, builtin_height - (y + h), w, h)


def clamp_rect(x: float, y: float, w: float, h: float,
               screens: list[tuple[float, float, float, float]],
               ) -> tuple[float, float, float, float]:
    """Keep a rect usable: at least MIN_W x MIN_H and fully inside one of the
    currently attached screens' visible areas.

    `screens` is a list of (origin_x, origin_y, width, height) so this stays a
    pure function — callers pass NSScreen values, tests pass literals.

    A rect that already fits on ANY attached screen is returned untouched:
    dragging the frame onto the external monitor on purpose is legitimate. Only
    when it fits nowhere (monitor unplugged, resolution changed) is it pulled
    back onto the first screen, which is the built-in display.
    """
    w = max(w, MIN_W)
    h = max(h, MIN_H)
    for ox, oy, sw, sh in screens:
        if ox <= x and y >= oy and x + w <= ox + sw and y + h <= oy + sh:
            return (x, y, w, h)
    ox, oy, sw, sh = screens[0]
    w = min(w, sw)
    h = min(h, sh)
    return (
        min(max(x, ox), ox + sw - w),
        min(max(y, oy), oy + sh - h),
        w,
        h,
    )


def load_rect() -> tuple[float, float, float, float] | None:
    try:
        d = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return float(d["x"]), float(d["y"]), float(d["w"]), float(d["h"])
    except Exception:  # noqa: BLE001 - missing/corrupt state means "not set yet"
        return None


def save_rect(x: float, y: float, w: float, h: float) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(
            json.dumps({"x": x, "y": y, "w": w, "h": h}), encoding="utf-8"
        )
    except Exception:  # noqa: BLE001 - failing to persist must not break the app
        traceback.print_exc()


HANDLE = 8.0            # corner grab square, points
EDGE_BAND = 6.0         # inner band that drags the whole frame
_window = None          # module-level: a window that goes out of scope is torn down
_editing = False
_key_monitor = None


def _visible_frames() -> list[tuple[float, float, float, float]]:
    """NSScreen visible areas as plain tuples, built-in display first."""
    out = []
    for s in NSScreen.screens():
        f, vf = s.frame(), s.visibleFrame()
        entry = (vf.origin.x, vf.origin.y, vf.size.width, vf.size.height)
        if f.origin.x == 0 and f.origin.y == 0:
            out.insert(0, entry)   # built-in first: clamp_rect falls back to screens[0]
        else:
            out.append(entry)
    return out or [(0.0, 0.0, 1440.0, 900.0)]


def builtin_height() -> float:
    """Height of the built-in display — the reference for to_capture_rect()."""
    for s in NSScreen.screens():
        f = s.frame()
        if f.origin.x == 0 and f.origin.y == 0:
            return f.size.height
    return NSScreen.screens()[0].frame().size.height


def _default_rect() -> tuple[float, float, float, float]:
    """Upper-middle of the built-in display — where a sentence usually sits."""
    ox, oy, sw, sh = _visible_frames()[0]
    w, h = DEFAULT_SIZE
    return (ox + (sw - w) / 2.0, oy + sh * 0.62, w, h)


class _RegionView(NSView):
    """Draws the frame; in edit mode also handles move/resize."""

    def initWithFrame_(self, frame):
        self = objc.super(_RegionView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._drag = None      # (mode, mouse_down_point, window_frame_at_down)
        return self

    def drawRect_(self, rect):
        b = self.bounds()
        inset = NSMakeRect(1.0, 1.0, b.size.width - 2.0, b.size.height - 2.0)
        path = NSBezierPath.bezierPathWithRect_(inset)
        if _editing:
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.16, 0.47, 0.96, 1.0).set()
            path.setLineWidth_(2.0)
        else:
            NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.75).set()
            path.setLineWidth_(1.5)
        path.stroke()
        if not _editing:
            return
        NSColor.colorWithCalibratedRed_green_blue_alpha_(0.16, 0.47, 0.96, 1.0).set()
        for hx, hy in (
            (0.0, 0.0),
            (b.size.width - HANDLE, 0.0),
            (0.0, b.size.height - HANDLE),
            (b.size.width - HANDLE, b.size.height - HANDLE),
        ):
            NSBezierPath.bezierPathWithRect_(
                NSMakeRect(hx, hy, HANDLE, HANDLE)
            ).fill()

    def _mode_at(self, p):
        b = self.bounds()
        near_l, near_r = p.x <= HANDLE, p.x >= b.size.width - HANDLE
        near_b, near_t = p.y <= HANDLE, p.y >= b.size.height - HANDLE
        if near_l and near_b:
            return "bl"
        if near_r and near_b:
            return "br"
        if near_l and near_t:
            return "tl"
        if near_r and near_t:
            return "tr"
        return "move"

    def mouseDown_(self, event):
        if not _editing:
            return
        p = self.convertPoint_fromView_(event.locationInWindow(), None)
        f = self.window().frame()
        self._drag = (
            self._mode_at(p),
            NSEvent.mouseLocation(),
            (f.origin.x, f.origin.y, f.size.width, f.size.height),
        )

    def mouseDragged_(self, event):
        if not _editing or self._drag is None:
            return
        mode, down, (ox, oy, ow, oh) = self._drag
        now = NSEvent.mouseLocation()
        dx, dy = now.x - down.x, now.y - down.y
        if mode == "move":
            x, y, w, h = ox + dx, oy + dy, ow, oh
        elif mode == "br":
            x, y, w, h = ox, oy + dy, ow + dx, oh - dy
        elif mode == "bl":
            x, y, w, h = ox + dx, oy + dy, ow - dx, oh - dy
        elif mode == "tr":
            x, y, w, h = ox, oy, ow + dx, oh + dy
        else:  # "tl"
            x, y, w, h = ox + dx, oy, ow - dx, oh + dy
        x, y, w, h = clamp_rect(x, y, w, h, _visible_frames())
        self.window().setFrame_display_(NSMakeRect(x, y, w, h), True)

    def mouseUp_(self, event):
        self._drag = None
        f = self.window().frame()
        save_rect(f.origin.x, f.origin.y, f.size.width, f.size.height)

    # Clicking outside the frame ends edit mode; AppKit delivers this when the
    # borderless window loses its click-through exemption.
    def mouseExited_(self, event):
        pass


def show() -> None:
    """Show the frame, creating it (at the saved or default rect) if needed."""
    global _window
    if _window is not None:
        _window.orderFrontRegardless()
        return
    rect = load_rect() or _default_rect()
    x, y, w, h = clamp_rect(*rect, _visible_frames())
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(x, y, w, h), NSWindowStyleMaskBorderless,
        NSBackingStoreBuffered, False,
    )
    win.setOpaque_(False)
    win.setBackgroundColor_(NSColor.clearColor())
    win.setLevel_(NSFloatingWindowLevel)
    win.setCollectionBehavior_(
        NSWindowCollectionBehaviorCanJoinAllSpaces
        | NSWindowCollectionBehaviorStationary
    )
    win.setHasShadow_(False)          # a shadow would be captured with the region
    win.setIgnoresMouseEvents_(True)  # click-through until edit mode
    win.setContentView_(_RegionView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h)))
    win.orderFrontRegardless()
    _window = win


def hide() -> None:
    global _window
    _exit_edit_mode()
    if _window is not None:
        _window.orderOut_(None)
        _window = None


def is_visible() -> bool:
    return _window is not None


def has_region() -> bool:
    return load_rect() is not None or _window is not None


def current_rect() -> tuple[float, float, float, float] | None:
    """The live window frame if shown, else the persisted rect, else None."""
    if _window is not None:
        f = _window.frame()
        return (f.origin.x, f.origin.y, f.size.width, f.size.height)
    return load_rect()


def _exit_edit_mode() -> None:
    global _editing, _key_monitor
    if not _editing:
        return
    _editing = False
    if _key_monitor is not None:
        NSEvent.removeMonitor_(_key_monitor)
        _key_monitor = None
    if _window is not None:
        _window.setIgnoresMouseEvents_(True)
        _window.contentView().setNeedsDisplay_(True)
        f = _window.frame()
        save_rect(f.origin.x, f.origin.y, f.size.width, f.size.height)


def enter_edit_mode() -> None:
    """Make the frame draggable/resizable until Esc."""
    global _editing, _key_monitor
    show()
    if _editing:
        return
    _editing = True
    _window.setIgnoresMouseEvents_(False)
    _window.contentView().setNeedsDisplay_(True)

    # Local (not global) monitor: during edit mode this window is the one being
    # interacted with, and a borderless window can't become key, so Esc would
    # otherwise never reach us.
    def _on_key(event):
        if event.keyCode() == 53:  # Esc
            _exit_edit_mode()
            return None            # swallow it
        return event

    _key_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
        NSEventMaskKeyDown, _on_key
    )


REDRAW_WAIT = 0.08     # seconds to let the compositor finish a frame after hiding


class NoRegionError(Exception):
    """No region has been defined yet — the caller should offer to set one."""


def _set_frame_hidden(hidden: bool) -> None:
    """Hide/show the frame window ON THE MAIN THREAD.

    capture() runs on a worker thread (the screencapture call is blocking I/O
    and must not sit on the main thread — that's how this app previously
    deadlocked on Keychain). AppKit window ops, however, are main-thread only,
    so they're marshalled across here.
    """
    if _window is None:
        return
    from Foundation import NSThread

    selector = "orderOut:" if hidden else "orderFrontRegardless"
    if NSThread.isMainThread():
        if hidden:
            _window.orderOut_(None)
        else:
            _window.orderFrontRegardless()
    else:
        # waitUntilDone=True: the next step (screencapture) depends on this
        # having actually happened, not merely been queued.
        _window.performSelectorOnMainThread_withObject_waitUntilDone_(
            selector, None, True
        )


def _capture_rect(x: float, y: float, w: float, h: float) -> str:
    """Seam for tests; real work goes to capture.capture_rect."""
    return _capture_mod.capture_rect(x, y, w, h)


def capture() -> str:
    """Return a PNG path of the region's current contents.

    Hides the frame first so its own border isn't part of the shot, and always
    restores it — leaving it hidden on failure would look like the feature
    silently disappeared.
    """
    rect = current_rect()
    if rect is None:
        raise NoRegionError("尚未设定区域")
    cx, cy, cw, ch = to_capture_rect(*rect, builtin_height())
    _set_frame_hidden(True)
    try:
        # orderOut_ only removes the window from the list; it does NOT guarantee
        # the screen has been recomposited. Without this pause screencapture
        # frequently still catches the border.
        time.sleep(REDRAW_WAIT)
        return _capture_rect(cx, cy, cw, ch)
    finally:
        _set_frame_hidden(False)
