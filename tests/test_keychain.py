import pytest

import keychain


@pytest.fixture(autouse=True)
def isolate_keychain_service(monkeypatch):
    monkeypatch.setattr(keychain, "SERVICE", "com.jinkun.screen-coach.test")
    yield
    keychain.delete_key()  # clean up regardless of pass/fail


def test_get_key_returns_none_when_absent():
    assert keychain.get_key() is None


def test_set_then_get_round_trips():
    keychain.set_key("sk-ant-test-123")
    assert keychain.get_key() == "sk-ant-test-123"


def test_set_key_overwrites_existing_value():
    keychain.set_key("sk-ant-first")
    keychain.set_key("sk-ant-second")
    assert keychain.get_key() == "sk-ant-second"


def test_delete_key_is_safe_when_nothing_stored():
    keychain.delete_key()  # must not raise
    assert keychain.get_key() is None


def test_set_key_times_out_instead_of_hanging(monkeypatch):
    """A wedged securityd must surface as an error, not a silent freeze.

    set_key() runs before the menu bar and hotkey exist, so an unbounded block
    there leaves no usable UI at all.
    """
    import threading

    monkeypatch.setattr(keychain, "WRITE_TIMEOUT", 0.1)
    release = threading.Event()

    def _hang(value):
        release.wait(30)  # simulate securityd never answering

    monkeypatch.setattr(keychain, "_write", _hang)
    try:
        with pytest.raises(RuntimeError, match="超时"):
            keychain.set_key("sk-ant-whatever")
    finally:
        release.set()  # let the daemon thread exit instead of lingering


def test_set_key_propagates_real_write_errors(monkeypatch):
    """A genuine OSStatus failure must not be swallowed by the timeout wrapper."""
    def _boom(value):
        raise RuntimeError("Keychain write failed (OSStatus -25299)")

    monkeypatch.setattr(keychain, "_write", _boom)
    with pytest.raises(RuntimeError, match="-25299"):
        keychain.set_key("sk-ant-whatever")
