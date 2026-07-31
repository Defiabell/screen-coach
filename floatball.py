"""A small always-on-top, draggable button that triggers an analysis.

Exists because the menu-bar item lives on whichever display owns the menu bar —
with a second monitor attached it can end up on a screen you aren't looking at
(observed at y=-1104, i.e. the external display), leaving no reachable way to
start an analysis. This floats above everything on every space, remembers where
you put it, and works regardless of which display the menu bar is on.

Runs on the main run loop inside the menu-bar app — not as a pywebview window,
which brings its own event loop and fights rumps.
"""
from __future__ import annotations

import json
import traceback
from pathlib import Path

import objc
from AppKit import (
    NSApplication,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSEvent,
    NSFloatingWindowLevel,
    NSFont,
    NSForegroundColorAttributeName,
    NSFontAttributeName,
    NSMenu,
    NSScreen,
    NSString,
    NSView,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
)
from Foundation import NSMakePoint, NSMakeRect, NSObject, NSPoint

DIAMETER = 52.0
_DRAG_SLOP = 4.0        # movement beyond this counts as a drag, not a click
_MARGIN = 12.0          # keep at least this much of a gap when clamping on-screen

_state_path = Path.home() / "Library" / "Application Support" / "Screen Coach" / "ball.json"
_window = None          # module-level: an NSWindow that goes out of scope is torn down
_menu_builder = None    # callable returning the NSMenu for a right-click, or None


def _load_origin() -> tuple[float, float] | None:
    try:
        d = json.loads(_state_path.read_text(encoding="utf-8"))
        return float(d["x"]), float(d["y"])
    except Exception:  # noqa: BLE001 - missing/corrupt state just means "use the default"
        return None


def _save_origin(x: float, y: float) -> None:
    try:
        _state_path.parent.mkdir(parents=True, exist_ok=True)
        _state_path.write_text(json.dumps({"x": x, "y": y}), encoding="utf-8")
    except Exception:  # noqa: BLE001 - failing to persist a position must not break the app
        pass


def _default_screen():
    """The built-in display, i.e. the one whose frame starts at the origin.

    NOT NSScreen.mainScreen(): that's whichever screen currently has focus, so
    with an external monitor attached the ball would be placed on a display the
    user may not be looking at — the exact problem this button exists to solve.
    """
    for screen in NSScreen.screens():
        f = screen.frame()
        if f.origin.x == 0 and f.origin.y == 0:
            return screen
    return NSScreen.mainScreen()


def _default_origin() -> tuple[float, float]:
    """Bottom-right of the built-in display's visible area."""
    vf = _default_screen().visibleFrame()
    return (vf.origin.x + vf.size.width - DIAMETER - 40.0,
            vf.origin.y + 40.0)


def _clamp_on_screen(x: float, y: float) -> tuple[float, float]:
    """Keep the ball reachable.

    A saved position can land somewhere unusable after the display layout
    changes (monitor unplugged, resolution changed). Positions are accepted on
    any *currently attached* screen — dragging it to the external monitor on
    purpose is fine — but must be fully within that screen's visible frame, so
    it can't end up half-off an edge or on a display that's gone.
    """
    for screen in NSScreen.screens():
        vf = screen.visibleFrame()
        if (vf.origin.x <= x <= vf.origin.x + vf.size.width - DIAMETER
                and vf.origin.y <= y <= vf.origin.y + vf.size.height - DIAMETER):
            return x, y
    return _default_origin()


class _BallView(NSView):
    """Draws the circle and handles click-vs-drag."""

    def initWithFrame_callback_(self, frame, callback):
        # objc.super, not the builtin: an Objective-C subclass's superclass
        # chain isn't the Python one, and builtin super() can't find the
        # inherited selector.
        self = objc.super(_BallView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._callback = callback
        self._down_at = None      # screen point where the mouse went down
        self._origin_at = None    # window origin at mouse-down
        self._moved = False
        self._hot = False
        return self

    def drawRect_(self, rect):
        inset = NSMakeRect(2, 2, self.bounds().size.width - 4, self.bounds().size.height - 4)
        circle = NSBezierPath.bezierPathWithOvalInRect_(inset)
        if self._hot:
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.16, 0.47, 0.96, 0.96).set()
        else:
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.12, 0.12, 0.14, 0.88).set()
        circle.fill()
        NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.35).set()
        circle.setLineWidth_(1.5)
        circle.stroke()

        glyph = NSString.stringWithString_("📖")
        attrs = {
            NSFontAttributeName: NSFont.systemFontOfSize_(24),
            NSForegroundColorAttributeName: NSColor.whiteColor(),
        }
        size = glyph.sizeWithAttributes_(attrs)
        glyph.drawAtPoint_withAttributes_(
            NSMakePoint((self.bounds().size.width - size.width) / 2.0,
                        (self.bounds().size.height - size.height) / 2.0),
            attrs,
        )

    # -- hover feedback -------------------------------------------------
    def resetCursorRects(self):
        pass

    def mouseEntered_(self, event):
        self._hot = True
        self.setNeedsDisplay_(True)

    def mouseExited_(self, event):
        self._hot = False
        self.setNeedsDisplay_(True)

    # -- click vs drag ---------------------------------------------------
    def mouseDown_(self, event):
        self._down_at = NSEvent.mouseLocation()
        origin = self.window().frame().origin
        self._origin_at = (origin.x, origin.y)
        self._moved = False

    def mouseDragged_(self, event):
        if self._down_at is None:
            return
        now = NSEvent.mouseLocation()
        dx, dy = now.x - self._down_at.x, now.y - self._down_at.y
        if abs(dx) > _DRAG_SLOP or abs(dy) > _DRAG_SLOP:
            self._moved = True
        self.window().setFrameOrigin_(
            NSPoint(self._origin_at[0] + dx, self._origin_at[1] + dy)
        )

    def mouseUp_(self, event):
        if self._moved:
            o = self.window().frame().origin
            _save_origin(o.x, o.y)
        elif self._callback is not None:
            try:
                self._callback()
            except Exception:  # noqa: BLE001 - never let a callback kill the UI
                traceback.print_exc()
        self._down_at = None

    def rightMouseDown_(self, event):
        """Show the same menu the menu-bar icon shows.

        The ball exists because the menu-bar item can end up on a display the
        user isn't watching; without this, the ball could only trigger its one
        default action and the rest of the menu stayed unreachable.
        """
        if _menu_builder is None:
            return
        try:
            menu = _menu_builder()
        except Exception:  # noqa: BLE001 - a broken menu must not kill the ball
            traceback.print_exc()
            return
        if menu is not None:
            NSMenu.popUpContextMenu_withEvent_forView_(menu, event, self)


def show(callback, menu_builder=None) -> None:
    """Create the floating ball.

    `callback` runs on a left click (not on a drag). `menu_builder`, if given,
    is called on right-click and must return an NSMenu — it's a callable rather
    than a menu so the caller can rebuild it with current checkbox states each
    time instead of handing over a snapshot that goes stale.
    """
    global _window, _menu_builder
    _menu_builder = menu_builder
    if _window is not None:
        _window.orderFrontRegardless()
        return

    x, y = _clamp_on_screen(*(_load_origin() or _default_origin()))
    rect = NSMakeRect(x, y, DIAMETER, DIAMETER)
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        rect, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
    )
    win.setOpaque_(False)
    win.setBackgroundColor_(NSColor.clearColor())
    win.setLevel_(NSFloatingWindowLevel)          # above normal windows
    win.setCollectionBehavior_(
        NSWindowCollectionBehaviorCanJoinAllSpaces
        | NSWindowCollectionBehaviorStationary    # visible on every space
    )
    win.setIgnoresMouseEvents_(False)
    win.setHasShadow_(True)

    view = _BallView.alloc().initWithFrame_callback_(
        NSMakeRect(0, 0, DIAMETER, DIAMETER), callback
    )
    win.setContentView_(view)
    win.orderFrontRegardless()

    _window = win


def hide() -> None:
    global _window
    if _window is not None:
        _window.orderOut_(None)
        _window = None


def is_visible() -> bool:
    return _window is not None
