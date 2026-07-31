import os

import config
import keychain


def test_load_api_key_from_keychain(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(keychain, "get_key", lambda: "sk-from-keychain")

    config.load_api_key()

    assert os.environ["ANTHROPIC_API_KEY"] == "sk-from-keychain"


def test_existing_env_var_wins(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    monkeypatch.setattr(keychain, "get_key", lambda: "sk-from-keychain")

    config.load_api_key()

    assert os.environ["ANTHROPIC_API_KEY"] == "sk-from-env"


def test_no_key_anywhere_is_silent(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(keychain, "get_key", lambda: None)

    config.load_api_key()  # must not raise

    assert "ANTHROPIC_API_KEY" not in os.environ
