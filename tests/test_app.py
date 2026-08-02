"""Tests for the Screen Recording permission gate. Quartz is injected via
sys.modules so we exercise granted / denied / import-fail without real TCC."""
import os

import pytest
import sys
import types

import anthropic
import httpx

import app


@pytest.fixture(autouse=True)
def isolate_prefs(monkeypatch):
    """Keep tests off the developer's real prefs.json.

    Several tests stub only one of analyze_image/translate_image; whichever the
    live `quick_mode` preference happens to select then decides whether they
    pass. Default every test to a clean slate — tests that care about a mode
    override this themselves.
    """
    monkeypatch.setattr(app, "_load_prefs", lambda: {})


def _fake_quartz(preflight, calls):
    m = types.ModuleType("Quartz")
    m.CGPreflightScreenCaptureAccess = lambda: preflight

    def _request():
        calls.append(1)
        return False

    m.CGRequestScreenCaptureAccess = _request
    return m


def test_screen_recording_granted(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "Quartz", _fake_quartz(True, calls))
    assert app._screen_recording_ok() is True
    assert calls == []  # already granted → no prompt


def test_screen_recording_denied_triggers_prompt(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "Quartz", _fake_quartz(False, calls))
    assert app._screen_recording_ok() is False
    assert calls == [1]  # denied → prompt fired


def test_screen_recording_import_fail_opens(monkeypatch):
    empty = types.ModuleType("Quartz")  # missing the two names → ImportError inside
    monkeypatch.setitem(sys.modules, "Quartz", empty)
    assert app._screen_recording_ok() is True  # can't check → don't block


def test_prompt_for_api_key_saves_on_ok(monkeypatch):
    # The code under test sets os.environ["ANTHROPIC_API_KEY"] directly (not
    # via monkeypatch.setenv), so monkeypatch's own teardown won't undo it.
    # Swap in a copy of the real environ so mutations during this test revert
    # automatically when monkeypatch's context tears down.
    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    saved = []
    monkeypatch.setattr(app.keychain, "set_key", lambda v: saved.append(v))
    # Patch the dialog seam, not the UI toolkit: _ask_for_key() runs a real
    # NSAlert, which in a test run would block forever waiting to be clicked.
    monkeypatch.setattr(app, "_ask_for_key", lambda existing=False: "sk-typed-in")

    app._prompt_for_api_key()

    assert saved == ["sk-typed-in"]
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-typed-in"


def test_prompt_for_api_key_cancelled_does_nothing(monkeypatch):
    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    saved = []
    monkeypatch.setattr(app.keychain, "set_key", lambda v: saved.append(v))
    monkeypatch.setattr(app, "_ask_for_key", lambda existing=False: None)  # cancelled

    app._prompt_for_api_key()

    assert saved == []
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_prompt_for_api_key_ignores_blank_input(monkeypatch):
    """Clicking 保存 with an empty field must not store an empty key."""
    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    saved = []
    monkeypatch.setattr(app.keychain, "set_key", lambda v: saved.append(v))
    monkeypatch.setattr(app, "_ask_for_key", lambda existing=False: "")

    app._prompt_for_api_key()

    assert saved == []
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_prompt_for_api_key_survives_a_broken_dialog(monkeypatch):
    """A dialog that raises must not take the app down — it starts the app."""
    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    saved = []
    monkeypatch.setattr(app.keychain, "set_key", lambda v: saved.append(v))

    def _boom(existing=False):
        raise RuntimeError("NSAlert exploded")

    monkeypatch.setattr(app, "_ask_for_key", _boom)

    app._prompt_for_api_key()  # must not raise

    assert saved == []


def test_prompt_for_api_key_keychain_write_failure_shows_error(monkeypatch):
    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def _boom(_value):
        raise RuntimeError("keychain busy")

    monkeypatch.setattr(app.keychain, "set_key", _boom)
    shown = []
    monkeypatch.setattr(app, "_show_error", lambda *a: shown.append(a))
    monkeypatch.setattr(app, "_ask_for_key", lambda existing=False: "sk-typed-in")

    app._prompt_for_api_key()

    assert shown, "a Keychain write failure must surface in the UI"
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_authentication_error_deletes_bad_keychain_key(monkeypatch):
    """A rejected key must not linger in Keychain — otherwise the next launch's
    config.load_api_key() would just find it again and never re-prompt."""
    monkeypatch.setattr(app.capture, "capture_region", lambda: "/tmp/screen-coach-test-fake.png")
    monkeypatch.setattr(app.capture, "to_base64", lambda _path: "b64data")
    monkeypatch.setattr(app, "_get_client", lambda: object())

    request = httpx.Request("POST", "http://example.com")
    response = httpx.Response(401, request=request)
    auth_error = anthropic.AuthenticationError("bad key", response=response, body=None)
    monkeypatch.setattr(app.analyzer, "analyze_image", lambda *a, **kw: (_ for _ in ()).throw(auth_error))

    deleted = []
    monkeypatch.setattr(app.keychain, "delete_key", lambda: deleted.append(1))
    shown = []
    monkeypatch.setattr(app, "_show_error", lambda *a: shown.append(a))

    app._busy.acquire()  # normally done by _trigger() before spawning the worker thread
    app._run_analysis()

    assert deleted == [1]
    assert len(shown) == 1


def test_authentication_error_keychain_delete_failure_still_shows_error(monkeypatch):
    """A Keychain delete failure during cleanup must not shadow/replace the
    auth-error reporting to the user."""
    monkeypatch.setattr(app.capture, "capture_region", lambda: "/tmp/screen-coach-test-fake.png")
    monkeypatch.setattr(app.capture, "to_base64", lambda _path: "b64data")
    monkeypatch.setattr(app, "_get_client", lambda: object())

    request = httpx.Request("POST", "http://example.com")
    response = httpx.Response(401, request=request)
    auth_error = anthropic.AuthenticationError("bad key", response=response, body=None)
    monkeypatch.setattr(app.analyzer, "analyze_image", lambda *a, **kw: (_ for _ in ()).throw(auth_error))

    def _boom():
        raise RuntimeError("keychain busy")

    monkeypatch.setattr(app.keychain, "delete_key", _boom)
    shown = []
    monkeypatch.setattr(app, "_show_error", lambda *a: shown.append(a))

    app._busy.acquire()
    app._run_analysis()  # must not raise despite delete_key() blowing up

    assert len(shown) == 1


def test_toggle_login_item_success_flips_state(monkeypatch):
    calls = []
    monkeypatch.setattr(app.loginitem, "set_login_item", lambda v: calls.append(v))

    assert app._toggle_login_item(False) is True
    assert calls == [True]


def test_toggle_login_item_failure_keeps_state_and_shows_error(monkeypatch):
    def _boom(_enabled):
        raise RuntimeError("automation denied")

    monkeypatch.setattr(app.loginitem, "set_login_item", _boom)
    shown = []
    monkeypatch.setattr(app, "_show_error", lambda *a: shown.append(a))

    assert app._toggle_login_item(False) is False
    assert len(shown) == 1


def test_current_login_item_state_dev_mode_is_false(monkeypatch):
    monkeypatch.setattr(app.sys, "frozen", False, raising=False)
    assert app._current_login_item_state() is False


def test_current_login_item_state_frozen_queries_loginitem(monkeypatch):
    monkeypatch.setattr(app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app.loginitem, "is_login_item", lambda: True)
    assert app._current_login_item_state() is True


def test_current_login_item_state_frozen_error_degrades_to_false(monkeypatch):
    monkeypatch.setattr(app.sys, "frozen", True, raising=False)

    def _boom():
        raise RuntimeError("not in a bundle")

    monkeypatch.setattr(app.loginitem, "is_login_item", _boom)
    assert app._current_login_item_state() is False


def test_run_analysis_uses_injected_grab(monkeypatch):
    """_run_analysis 必须通过 grab 参数取图，而非硬编码 capture_region。"""
    calls = []
    monkeypatch.setattr(app.capture, "to_base64", lambda p: "B64")
    monkeypatch.setattr(app.analyzer, "analyze_image",
                        lambda c, b: {"sentence": "x", "translation": "y"})
    monkeypatch.setattr(app, "_get_client", lambda: object())
    monkeypatch.setattr(app.history, "append_entry", lambda p, e: None)
    monkeypatch.setattr(app.history, "load_recent", lambda p: [])
    monkeypatch.setattr(app.render, "render_html", lambda a, r: "<html>")
    monkeypatch.setattr(app, "_show", lambda h: calls.append("shown"))
    monkeypatch.setattr(app.os, "unlink", lambda p: None)

    app._busy.acquire(blocking=False)
    app._run_analysis(grab=lambda: calls.append("grabbed") or "/tmp/x.png")

    assert "grabbed" in calls
    assert "shown" in calls


def test_trigger_region_offers_setup_when_no_region(monkeypatch):
    """没设过区域时应进编辑态并且本次不分析，也不能留下 _busy 死锁。"""
    events = []
    monkeypatch.setattr(app, "_screen_recording_ok", lambda: True)
    monkeypatch.setattr(app.region, "has_region", lambda: False)
    monkeypatch.setattr(app.region, "enter_edit_mode",
                        lambda: events.append("edit"))
    monkeypatch.setattr(app, "_show_error",
                        lambda *a: events.append("informed"))
    started = []
    monkeypatch.setattr(app.threading, "Thread",
                        lambda **k: type("T", (), {"start": lambda s: started.append(1)})())

    app._trigger_region()

    assert "edit" in events
    assert started == []                       # 本次不分析
    assert app._busy.acquire(blocking=False)   # 锁已释放
    app._busy.release()


def test_ball_click_uses_region_when_mode_on(monkeypatch):
    """Use Region checked → a ball click analyzes the persistent region."""
    called = []
    monkeypatch.setattr(app, "_load_prefs", lambda: {"use_region": True})
    monkeypatch.setattr(app, "_trigger_region", lambda: called.append("region"))
    monkeypatch.setattr(app, "_trigger", lambda: called.append("selection"))
    app._ball_click()
    assert called == ["region"]


def test_ball_click_drag_selects_when_mode_off(monkeypatch):
    """Use Region unchecked → a ball click drag-selects instead."""
    called = []
    monkeypatch.setattr(app, "_load_prefs", lambda: {"use_region": False})
    monkeypatch.setattr(app, "_trigger_region", lambda: called.append("region"))
    monkeypatch.setattr(app, "_trigger", lambda: called.append("selection"))
    app._ball_click()
    assert called == ["selection"]


def test_ball_click_reads_pref_every_time(monkeypatch):
    """The mode is read per click, not bound when the ball was created.

    Otherwise toggling Use Region would need the ball torn down and rebuilt to
    take effect.
    """
    mode = {"use_region": True}
    called = []
    monkeypatch.setattr(app, "_load_prefs", lambda: dict(mode))
    monkeypatch.setattr(app, "_trigger_region", lambda: called.append("region"))
    monkeypatch.setattr(app, "_trigger", lambda: called.append("selection"))
    app._ball_click()
    mode["use_region"] = False       # flip the pref with no rebuild
    app._ball_click()
    assert called == ["region", "selection"]


def test_ball_click_defaults_to_region_when_pref_absent(monkeypatch):
    """A fresh install has no prefs file; region mode is the intended default."""
    called = []
    monkeypatch.setattr(app, "_load_prefs", lambda: {})
    monkeypatch.setattr(app, "_trigger_region", lambda: called.append("region"))
    monkeypatch.setattr(app, "_trigger", lambda: called.append("selection"))
    app._ball_click()
    assert called == ["region"]


def test_use_region_pref_honours_retired_region_frame_key(monkeypatch):
    """An install that turned the old border off must not come back in region mode.

    `region_frame` used to mean "draw the border"; `use_region` now means "use
    the region". Ignoring the old key would silently reverse a preference the
    user had explicitly set.
    """
    monkeypatch.setattr(app, "_load_prefs", lambda: {"region_frame": False})
    assert app._use_region_pref() is False


def test_use_region_pref_prefers_new_key_over_old(monkeypatch):
    """Once the new key exists it wins — the old one is only a fallback."""
    monkeypatch.setattr(app, "_load_prefs", lambda: {"use_region": True, "region_frame": False})
    assert app._use_region_pref() is True


def test_use_region_pref_defaults_true_on_fresh_install(monkeypatch):
    monkeypatch.setattr(app, "_load_prefs", lambda: {})
    assert app._use_region_pref() is True


def _analysis_harness(monkeypatch, calls):
    """Stub everything _run_analysis touches except the analyzer choice."""
    monkeypatch.setattr(app.capture, "to_base64", lambda p: "B64")
    monkeypatch.setattr(app, "_get_client", lambda: object())
    monkeypatch.setattr(app.history, "append_entry", lambda p, e: None)
    monkeypatch.setattr(app.history, "load_recent", lambda p: [])
    monkeypatch.setattr(app.render, "render_html", lambda a, r: "<html>")
    monkeypatch.setattr(app, "_show", lambda h: None)
    monkeypatch.setattr(app.os, "unlink", lambda p: None)
    monkeypatch.setattr(app.analyzer, "analyze_image",
                        lambda c, b: calls.append("full") or {"translation": "x"})
    monkeypatch.setattr(app.analyzer, "translate_image",
                        lambda c, b: calls.append("quick") or {"translation": "x"})


def test_run_analysis_uses_quick_path_when_enabled(monkeypatch):
    calls = []
    _analysis_harness(monkeypatch, calls)
    monkeypatch.setattr(app, "_load_prefs", lambda: {"quick_mode": True})
    app._busy.acquire(blocking=False)
    app._run_analysis(grab=lambda: "/tmp/x.png")
    assert calls == ["quick"]


def test_run_analysis_uses_full_path_by_default(monkeypatch):
    calls = []
    _analysis_harness(monkeypatch, calls)
    monkeypatch.setattr(app, "_load_prefs", lambda: {})
    app._busy.acquire(blocking=False)
    app._run_analysis(grab=lambda: "/tmp/x.png")
    assert calls == ["full"]


def test_quick_mode_pref_read_per_analysis(monkeypatch):
    """Toggling the menu must apply to the next trigger without a restart."""
    mode = {"quick_mode": False}
    calls = []
    _analysis_harness(monkeypatch, calls)
    monkeypatch.setattr(app, "_load_prefs", lambda: dict(mode))
    app._busy.acquire(blocking=False)
    app._run_analysis(grab=lambda: "/tmp/x.png")
    mode["quick_mode"] = True
    app._busy.acquire(blocking=False)
    app._run_analysis(grab=lambda: "/tmp/x.png")
    assert calls == ["full", "quick"]
