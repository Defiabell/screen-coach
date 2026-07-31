import pytest

import loginitem


def test_bundle_path_walks_up_to_app(monkeypatch):
    monkeypatch.setattr(
        loginitem.sys, "executable",
        "/Applications/Screen Coach.app/Contents/MacOS/Screen Coach",
    )
    assert loginitem._bundle_path() == "/Applications/Screen Coach.app"


def test_bundle_path_raises_outside_app_bundle(monkeypatch):
    monkeypatch.setattr(loginitem.sys, "executable", "/usr/bin/python3")
    with pytest.raises(RuntimeError):
        loginitem._bundle_path()


def test_is_login_item_true_when_osascript_returns_a_path(monkeypatch):
    monkeypatch.setattr(loginitem, "_bundle_path", lambda: "/Applications/Screen Coach.app")
    monkeypatch.setattr(loginitem, "_osascript", lambda script: "/Applications/Screen Coach.app")

    assert loginitem.is_login_item() is True


def test_is_login_item_false_when_osascript_returns_empty(monkeypatch):
    monkeypatch.setattr(loginitem, "_bundle_path", lambda: "/Applications/Screen Coach.app")
    monkeypatch.setattr(loginitem, "_osascript", lambda script: "")

    assert loginitem.is_login_item() is False


def test_set_login_item_enable_calls_make(monkeypatch):
    monkeypatch.setattr(loginitem, "_bundle_path", lambda: "/Applications/Screen Coach.app")
    monkeypatch.setattr(loginitem, "is_login_item", lambda: False)
    calls = []
    monkeypatch.setattr(loginitem, "_osascript", lambda script: calls.append(script) or "")

    loginitem.set_login_item(True)

    assert len(calls) == 1
    assert "make login item" in calls[0]
    assert "/Applications/Screen Coach.app" in calls[0]


def test_set_login_item_enable_is_noop_if_already_present(monkeypatch):
    monkeypatch.setattr(loginitem, "_bundle_path", lambda: "/Applications/Screen Coach.app")
    monkeypatch.setattr(loginitem, "is_login_item", lambda: True)
    calls = []
    monkeypatch.setattr(loginitem, "_osascript", lambda script: calls.append(script) or "")

    loginitem.set_login_item(True)

    assert calls == []


def test_set_login_item_disable_calls_delete(monkeypatch):
    monkeypatch.setattr(loginitem, "_bundle_path", lambda: "/Applications/Screen Coach.app")
    calls = []
    monkeypatch.setattr(loginitem, "_osascript", lambda script: calls.append(script) or "")

    loginitem.set_login_item(False)

    assert len(calls) == 1
    assert "delete" in calls[0]
    assert "/Applications/Screen Coach.app" in calls[0]
