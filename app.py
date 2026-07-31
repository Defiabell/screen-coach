"""screen-coach menu-bar app: hotkey -> capture -> Claude -> floating window."""
from __future__ import annotations

import atexit
import os
import subprocess
import sys
import tempfile
import threading
import traceback
from datetime import datetime
from pathlib import Path

import anthropic
import objc
import rumps
from Foundation import NSObject

import analyzer
import capture
import config
import floatball
import history
import keychain
import loginitem
import region
import render

_HERE = Path(__file__).parent
_client = None
_viewer_proc: subprocess.Popen | None = None
_viewer_html: str | None = None       # temp HTML backing the current viewer, for cleanup
_busy = threading.Lock()              # debounce: one analysis at a time
_hotkey_monitor = None                # retain the NSEvent global monitor


def _get_client():
    global _client
    if _client is None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        # Pin the official API explicitly. anthropic.Anthropic() otherwise honours
        # ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN from the environment, so a
        # launch from a shell that points at an internal gateway would silently
        # route there — and reject config.MODEL, which is an official model id.
        _client = anthropic.Anthropic(api_key=key, base_url="https://api.anthropic.com")
    return _client


def _kill_viewer() -> None:
    """Terminate the current viewer process and delete its temp HTML."""
    global _viewer_proc, _viewer_html
    if _viewer_proc and _viewer_proc.poll() is None:
        _viewer_proc.terminate()
    _viewer_proc = None
    if _viewer_html:
        try:
            os.unlink(_viewer_html)
        except OSError:
            pass
        _viewer_html = None


def _show(html: str) -> None:
    global _viewer_proc, _viewer_html
    _kill_viewer()  # replace any prior window and clean up its temp file
    fd, path = tempfile.mkstemp(suffix=".html", prefix="screen-coach-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(html)
    _viewer_html = path
    # Re-exec this same script in --viewer mode. sys.executable is a real
    # python interpreter both in dev and in the py2app bundle (Contents/MacOS/python)
    # — it needs an explicit script path or it parses "--viewer" as an
    # (unrecognized) interpreter flag and exits before running any code.
    args = [sys.executable, str(_HERE / "app.py"), "--viewer", path]
    env = os.environ.copy()
    if getattr(sys, "frozen", False):
        # py2app's bootstrap sets sys.path in-process (not via an inheritable
        # env var), so a bare `sys.executable` subprocess otherwise starts with
        # no knowledge of the bundle's dependencies — every import beyond
        # stdlib fails. Hand it the same sys.path this (already-bootstrapped)
        # process is using.
        env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    _viewer_proc = subprocess.Popen(args, env=env)


def _screen_recording_ok() -> bool:
    """True if we have Screen Recording permission. If not, trigger the system
    prompt and return False — otherwise screencapture silently produces nothing
    and the capture looks like a no-op."""
    try:
        from Quartz import CGPreflightScreenCaptureAccess, CGRequestScreenCaptureAccess
    except Exception:  # noqa: BLE001 - can't check → don't block
        return True
    if CGPreflightScreenCaptureAccess():
        return True
    CGRequestScreenCaptureAccess()  # prompt + register Screen Coach in the Settings list
    return False


def _run_analysis(grab=None) -> None:
    """Analyze one image. `grab` returns a PNG path (or None for a clean
    cancel) — it's injected so the same pipeline serves both the drag-select
    path and the fixed-region path.
    """
    if grab is None:
        grab = capture.capture_region
    try:
        try:
            png = grab()
        except capture.CaptureError as exc:
            _show_error("截图失败", str(exc), "先在 系统设置→隐私与安全性→屏幕录制 里允许 Screen Coach")
            return
        except region.NoRegionError as exc:
            _show_error("尚未设定区域", str(exc), "菜单 → Adjust Region… 先摆好取景框")
            return
        if not png:
            return  # user pressed Esc — clean cancel, no noise
        try:
            b64 = capture.to_base64(png)
        finally:
            try:
                os.unlink(png)  # don't leave screenshots around
            except OSError:
                pass
        analysis = analyzer.analyze_image(_get_client(), b64)
        analysis["ts"] = datetime.now().isoformat(timespec="seconds")
        history.append_entry(config.HISTORY_PATH, analysis)
        _show(render.render_html(analysis, history.load_recent(config.HISTORY_PATH)))
    except anthropic.AuthenticationError:
        try:
            keychain.delete_key()  # clear the bad key so the next launch re-prompts instead of reusing it
        except Exception:
            pass  # a cleanup failure here shouldn't hide the auth error being reported below
        _show_error("API key 无效", "ANTHROPIC_API_KEY 被拒绝", "Keychain 里的 key 可能不对，重新打开 Screen Coach 会再次询问")
    except Exception as exc:  # noqa: BLE001 - surface any failure in the window (reliable UI)
        traceback.print_exc()  # full trace to console for post-mortem
        _show_error(type(exc).__name__, str(exc), "确认 Keychain 里存了 ANTHROPIC_API_KEY（首次启动的弹窗会存）")
    finally:
        _busy.release()


def _show_error(title: str, msg: str, hint: str) -> None:
    """Show an error in the floating window (rumps notifications are unreliable
    from a background thread / when the notification center can't init)."""
    err = {
        "sentence": "", "translation": f"⚠️ {title}：{msg}",
        "breakdown": "", "words": [], "usage": [], "summary": hint,
    }
    try:
        _show(render.render_html(err, []))
    except Exception:  # noqa: BLE001 - last resort: console only
        traceback.print_exc()


def _trigger() -> None:
    if not _busy.acquire(blocking=False):
        return  # an analysis is already in flight; ignore the extra trigger
    # Check Screen Recording here (main thread — menu callback / NSEvent handler),
    # so the TCC prompt fires reliably, before spawning the worker.
    if not _screen_recording_ok():
        _busy.release()
        _show_error(
            "需要屏幕录制权限",
            "已弹出授权请求（没弹就去设置里手动开）",
            "系统设置 → 隐私与安全性 → 屏幕录制 → 打开 Screen Coach，然后退出重开 app",
        )
        return
    threading.Thread(target=_run_analysis, daemon=True).start()


def _trigger_region() -> None:
    """Analyze the persistent region. Same guards as _trigger()."""
    if not _busy.acquire(blocking=False):
        return
    if not _screen_recording_ok():
        _busy.release()
        _show_error(
            "需要屏幕录制权限",
            "已弹出授权请求（没弹就去设置里手动开）",
            "系统设置 → 隐私与安全性 → 屏幕录制 → 打开 Screen Coach，然后退出重开 app",
        )
        return
    if not region.has_region():
        # First use: let the user place the frame instead of burning an API call
        # on an arbitrary default rect. They click again once it's positioned.
        _busy.release()
        region.enter_edit_mode()
        _show_error(
            "已打开取景框",
            "拖动调整到想翻译的位置，按 Esc 完成",
            "然后再点一次小球或菜单的 Analyze Region",
        )
        return
    threading.Thread(target=_run_analysis, kwargs={"grab": region.capture},
                     daemon=True).start()


def _use_region_pref() -> bool:
    """Whether region mode is on.

    Falls back to the retired `region_frame` key so an install that had turned
    the old border off doesn't silently come back in region mode.
    """
    prefs = _load_prefs()
    return bool(prefs.get("use_region", prefs.get("region_frame", True)))


def _ball_click() -> None:
    """What a left click on the floating ball does, decided at click time.

    Reads the preference on every click rather than being bound to one action
    when the ball is created, so toggling the mode takes effect immediately
    without tearing the ball down and rebuilding it.
    """
    if _use_region_pref():
        _trigger_region()
    else:
        _trigger()


def _current_login_item_state() -> bool:
    if not getattr(sys, "frozen", False):
        return False  # dev run isn't an .app bundle — nothing to query
    try:
        return loginitem.is_login_item()
    except Exception:
        traceback.print_exc()
        return False


def _toggle_login_item(current_state: bool) -> bool:
    """Flip the login item; returns the new state. On failure, shows the
    existing error window and returns the state unchanged so the caller's
    checkbox doesn't lie about what actually happened."""
    try:
        loginitem.set_login_item(not current_state)
        return not current_state
    except Exception as exc:
        traceback.print_exc()
        _show_error(
            "Launch at Login 设置失败", str(exc),
            "系统设置 → 隐私与安全性 → 自动化 → 允许 Screen Coach 控制 System Events",
        )
        return current_state


_PREFS_PATH = Path.home() / "Library" / "Application Support" / "Screen Coach" / "prefs.json"


def _load_prefs() -> dict:
    try:
        import json

        return json.loads(_PREFS_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - missing/corrupt prefs just mean "use defaults"
        return {}


def _save_pref(key: str, value) -> None:
    try:
        import json

        prefs = _load_prefs()
        prefs[key] = value
        _PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PREFS_PATH.write_text(json.dumps(prefs), encoding="utf-8")
    except Exception:  # noqa: BLE001 - a preference that won't persist isn't fatal
        traceback.print_exc()


class _MenuAction(NSObject):
    """Objective-C target for a plain Python callable.

    NSMenuItem sends its action to an ObjC object; it can't call a Python
    function directly, so each ball-menu item gets one of these.
    """

    def initWithHandler_(self, handler):
        self = objc.super(_MenuAction, self).init()
        if self is None:
            return None
        self._handler = handler
        return self

    def invoke_(self, sender):
        try:
            self._handler()
        except Exception:  # noqa: BLE001 - a failing menu action must not kill the app
            traceback.print_exc()


class ScreenCoach(rumps.App):
    def __init__(self):
        # quit_button=None so we can run cleanup before Cocoa tears the app down
        super().__init__("📖", quit_button=None)
        self._ball_menu_actions = []  # retain trampolines; NSMenuItem targets are weak
        login_item = rumps.MenuItem("Launch at Login", callback=self._on_toggle_login_item)
        login_item.state = _current_login_item_state()
        if not getattr(sys, "frozen", False):
            # Dev run (.venv/bin/python app.py) isn't a .app bundle, so
            # loginitem.set_login_item() would raise "not running from a
            # .app bundle" — grey the item out instead of surfacing that as
            # a misleading Automation-permission error.
            login_item.set_callback(None)

        # Default ON: with a second display attached the menu-bar item can land
        # on a screen the user isn't looking at, and then this is the only
        # reachable way to start an analysis.
        ball_on = _load_prefs().get("float_ball", True)
        ball_item = rumps.MenuItem("Floating Button", callback=self._on_toggle_ball)
        ball_item.state = bool(ball_on)

        # `Use Region` is a MODE switch, not just border visibility: checked
        # means a left click on the ball analyzes the persistent region (and the
        # frame is shown so you can see what that is); unchecked means it
        # drag-selects instead. One button covers both without opening a menu.
        use_region = _use_region_pref()
        region_item = rumps.MenuItem("Use Region", callback=self._on_toggle_region)
        region_item.state = bool(use_region)
        if use_region:
            region.show()
        if ball_on:
            floatball.show(_ball_click, menu_builder=self._build_ball_menu)

        self.menu = [
            rumps.MenuItem("Analyze Selection", callback=lambda _: _trigger()),
            rumps.MenuItem("Analyze Region", callback=lambda _: _trigger_region()),
            None,
            region_item,
            rumps.MenuItem("Adjust Region…", callback=lambda _: region.enter_edit_mode()),
            ball_item,
            login_item,
            None,
            rumps.MenuItem("Quit", callback=self._quit),
        ]

    def _on_toggle_login_item(self, sender):
        sender.state = _toggle_login_item(sender.state)

    def _on_toggle_ball(self, sender):
        sender.state = not sender.state
        if sender.state:
            floatball.show(_ball_click, menu_builder=self._build_ball_menu)
        else:
            floatball.hide()
        _save_pref("float_ball", bool(sender.state))

    def _on_toggle_region(self, sender):
        sender.state = not sender.state
        if sender.state:
            region.show()
        else:
            region.hide()
        _save_pref("use_region", bool(sender.state))

    def _build_ball_menu(self):
        """The ball's right-click menu — same actions as the menu-bar menu.

        Built fresh on each right click so the checkmarks reflect current state.
        It's a separate NSMenu rather than rumps' own: rumps owns its menu as the
        status item's, and handing the same NSMenu to popUpContextMenu_ makes
        AppKit fight over ownership.
        """
        from AppKit import NSMenu, NSMenuItem

        menu = NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)
        self._ball_menu_actions = []  # drop the previous menu's trampolines

        def add(title, action, checked=None, enabled=True):
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                title, "invoke:", ""
            )
            # Retain the trampoline: NSMenuItem's target is a weak reference, so
            # a trampoline that goes out of scope leaves a dead menu item.
            tramp = _MenuAction.alloc().initWithHandler_(action)
            self._ball_menu_actions.append(tramp)
            item.setTarget_(tramp)
            item.setEnabled_(enabled)
            if checked is not None:
                item.setState_(1 if checked else 0)
            menu.addItem_(item)

        add("Analyze Selection", _trigger)
        add("Analyze Region", _trigger_region)
        menu.addItem_(NSMenuItem.separatorItem())
        add("Use Region", self._toggle_region_from_ball,
            checked=_use_region_pref())
        add("Adjust Region…", region.enter_edit_mode)
        add("Floating Button", self._toggle_ball_from_ball,
            checked=_load_prefs().get("float_ball", True))
        # Read the checkmark off the menu-bar item rather than re-querying:
        # _current_login_item_state() shells out to osascript, which is a
        # blocking IPC round-trip (and can raise an Automation-permission
        # dialog). Fine once at launch; not on every right click, on the main
        # thread, with the menu waiting to appear.
        login = self._menu_item("Launch at Login")
        add("Launch at Login", self._toggle_login_from_ball,
            checked=bool(login.state) if login is not None else False,
            enabled=getattr(sys, "frozen", False))
        menu.addItem_(NSMenuItem.separatorItem())
        add("Quit", lambda: self._quit(None))
        return menu

    # The ball's menu and the menu-bar menu must not drift apart, so the ball's
    # toggles drive the same rumps MenuItems rather than duplicating the logic.
    def _menu_item(self, title):
        try:
            return self.menu[title]
        except KeyError:
            return None

    def _toggle_region_from_ball(self):
        item = self._menu_item("Use Region")
        if item is not None:
            self._on_toggle_region(item)

    def _toggle_ball_from_ball(self):
        item = self._menu_item("Floating Button")
        if item is not None:
            self._on_toggle_ball(item)

    def _toggle_login_from_ball(self):
        item = self._menu_item("Launch at Login")
        if item is not None:
            self._on_toggle_login_item(item)

    def _quit(self, _):
        _kill_viewer()
        floatball.hide()
        region.hide()
        rumps.quit_application()


def _debug_log(msg: str) -> None:
    """Append to a log file. The bundle has no console, so this is the only way
    to see what the hotkey path actually does in the installed app."""
    try:
        p = Path.home() / "Library" / "Logs" / "screen-coach-debug.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except Exception:  # noqa: BLE001 - logging must never break the app
        pass


def _start_hotkey() -> None:
    """Register the global ⇧⌘E hotkey via a CGEventTap on the MAIN run loop.

    NOT NSEvent.addGlobalMonitorForEventsMatchingMask_handler_: that monitor is
    passive and — measured, not guessed — never receives Command-modified
    keydowns at all (plain letters arrive fine, ⌘/⇧⌘ combos never do), because
    macOS routes command-key equivalents ahead of passive observers. Three
    different modifier combinations were tried on top of that monitor before the
    monitor itself turned out to be the wrong mechanism.

    A CGEventTap does see them. It's installed listen-only so the keystroke
    still reaches the focused app, and its run-loop source goes on the MAIN run
    loop — pynput's tap ran on its own thread and fought rumps, freezing the
    menu-bar menu. Requires Accessibility permission; CGEventTapCreate returns
    NULL without it, which is logged rather than crashing the app (the menu-bar
    'Analyze selection' path keeps working either way).
    """
    global _hotkey_monitor
    from AppKit import NSEvent
    from Quartz import (
        CFMachPortCreateRunLoopSource,
        CFRunLoopAddSource,
        CFRunLoopGetMain,
        CGEventGetIntegerValueField,
        CGEventMaskBit,
        CGEventTapCreate,
        CGEventTapEnable,
        kCFRunLoopCommonModes,
        kCGEventKeyDown,
        kCGEventTapOptionListenOnly,
        kCGHeadInsertEventTap,
        kCGKeyboardEventKeycode,
        kCGSessionEventTap,
    )

    CMD, SHIFT = 1 << 20, 1 << 17   # NSCommandKeyMask, NSShiftKeyMask
    KEY_E = 14                      # macOS virtual key code for 'e'

    try:
        from ApplicationServices import (
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )

        # Check silently first, and only ask the system to show its "grant
        # Accessibility access" dialog when we don't have it. Prompting
        # unconditionally would surface an OS dialog on every single launch once
        # the grant is in place — build_app.sh now signs with a stable identity,
        # so a granted permission survives rebuilds and re-prompting is noise.
        # The prompt is still needed on the first launch after a signing-identity
        # change, because macOS then treats this as a different app and any
        # existing (even visibly enabled) Accessibility entry doesn't apply.
        trusted = bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: False}))
        if not trusted:
            trusted = bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}))
    except Exception as exc:  # noqa: BLE001
        trusted = f"check failed: {exc}"
    _debug_log(f"_start_hotkey: pid={os.getpid()} AXIsProcessTrusted={trusted}")

    def _callback(proxy, etype, event, refcon):
        try:
            keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
            ns = NSEvent.eventWithCGEvent_(event)
            flags = ns.modifierFlags() if ns else 0
            if (flags & CMD) and (flags & SHIFT) and keycode == KEY_E:
                _debug_log(f"MATCH ⇧⌘E (flags={flags:#x}) -> _trigger()")
                _trigger()
        except Exception:  # noqa: BLE001 - a raising tap callback gets disabled by the system
            _debug_log(f"tap callback error: {traceback.format_exc()}")
        return event  # listen-only: hand the event back untouched

    tap = CGEventTapCreate(
        kCGSessionEventTap,
        kCGHeadInsertEventTap,
        kCGEventTapOptionListenOnly,
        CGEventMaskBit(kCGEventKeyDown),
        _callback,
        None,
    )
    if not tap:
        # Almost always missing Accessibility permission. (A diagnostic probe of
        # every tap location/placement/option combination lived here while this
        # was being investigated; all four returned NULL together, so the extra
        # detail bought nothing and its NSEvent probe leaked a monitor on every
        # permission-less launch.)
        _debug_log("CGEventTapCreate returned NULL — no Accessibility permission; hotkey disabled")
        return
    source = CFMachPortCreateRunLoopSource(None, tap, 0)
    CFRunLoopAddSource(CFRunLoopGetMain(), source, kCFRunLoopCommonModes)
    CGEventTapEnable(tap, True)
    # Retain both the tap and its run-loop source: if either is garbage-collected
    # the tap stops delivering events.
    _hotkey_monitor = (tap, source, _callback)
    _debug_log(f"CGEventTap installed on main run loop: {tap!r}")


def _prompt_for_api_key() -> None:
    # Activate first. LSUIElement apps start unactivated with no window layer for
    # a modal to attach to, and rumps.Window then blocks in runModal on a dialog
    # that never renders — an invisible hang at the very first line of main(),
    # before the menu bar exists. Observed repeatedly on this app.
    try:
        from AppKit import NSApplication

        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except Exception:  # noqa: BLE001 - if activation fails, still try the dialog
        traceback.print_exc()
    response = rumps.Window(
        message="首次使用需要 Anthropic API key，会存入 macOS Keychain，之后不用再输入。",
        title="设置 Screen Coach",
        secure=True,
        ok="保存",
        cancel="取消",
    ).run()
    if not (response.clicked == 1 and response.text.strip()):
        return
    key = response.text.strip()
    try:
        keychain.set_key(key)
    except Exception as exc:
        traceback.print_exc()
        _show_error("Keychain 写入失败", str(exc), "重新打开 Screen Coach 会再次询问 API key")
        return
    os.environ["ANTHROPIC_API_KEY"] = key


def main() -> None:
    config.load_api_key()  # env > Keychain
    atexit.register(_kill_viewer)  # belt-and-suspenders if the app exits another way
    _start_hotkey()
    # Ask for a missing key AFTER the menu bar is up, not before. Prompting here
    # used to be the first thing main() did, so anything that stalled the dialog
    # — a wedged Keychain, an unrendered modal in an LSUIElement app — took the
    # whole app down with it: no icon, no ball, no hotkey, nothing to click.
    # Scheduled on the run loop so it fires once rumps has finished starting.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        _schedule_api_key_prompt()
    ScreenCoach().run()


def _schedule_api_key_prompt(delay: float = 1.0) -> None:
    """Run _prompt_for_api_key on the main run loop, shortly after startup."""
    try:
        from Foundation import NSTimer

        NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
            delay, False, lambda _t: _prompt_for_api_key()
        )
    except Exception:  # noqa: BLE001 - worst case the user gets the error card instead
        traceback.print_exc()


if __name__ == "__main__":
    if "--viewer" in sys.argv:
        # re-exec'd by _show(): show the floating window (heavy webview import kept here)
        import viewer

        viewer.main()
    else:
        main()
