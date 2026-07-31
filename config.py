"""Config for screen-coach: static constants, plus API-key resolution (env var > Keychain)."""
import os
import threading
from pathlib import Path

import keychain

MODEL = "claude-sonnet-5"          # vision-capable; supports analyzer.py's effort parameter
                                   # (opus-4-1 does not — it 400s with "does not support the
                                   # effort parameter"). Official-API id, not a gateway alias.
MAX_TOKENS = 4096                  # headroom so a dense breakdown's JSON isn't truncated
def _history_path() -> Path:
    """Per-user history file, outside the .app bundle.

    NOT Path(__file__).parent: in the py2app bundle __file__ lives inside
    lib/python39.zip, so .parent is that zip *file* and writing there fails with
    NotADirectoryError. App-bundle contents are also the wrong place for user
    data — reinstalling would wipe it.
    """
    d = Path.home() / "Library" / "Application Support" / "Screen Coach"
    d.mkdir(parents=True, exist_ok=True)
    return d / "history.jsonl"


HISTORY_PATH = _history_path()
RECENT_LIMIT = 20                  # how many past entries the window lists
SPEAK_WPM = 150                    # normal `say` reading pace (words/min); lower = slower
SPEAK_WPM_SLOW = 105               # the 🐢 button


KEYCHAIN_TIMEOUT = 5.0             # seconds; see load_api_key()


def load_api_key() -> None:
    """Populate ANTHROPIC_API_KEY from Keychain when it's not already in the
    environment. A .app launched from Finder / Login Items does NOT inherit
    the shell's env vars, so Keychain is the persistent store. An env var
    already set wins.

    The read is bounded by KEYCHAIN_TIMEOUT: SecItemCopyMatching can block
    forever inside securityd (observed after re-signing the bundle — the
    Keychain item's ACL no longer matches the new ad-hoc signature and
    securityd waits on an authorization dialog that an LSUIElement app never
    gets to show). Timing out leaves the key unset, which surfaces as a normal
    "no API key" error instead of a hung process."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    result: list[str | None] = []
    # daemon: if securityd never answers, this thread stays blocked in mach_msg
    # for the life of the process — it must not keep the app alive.
    reader = threading.Thread(target=lambda: result.append(keychain.get_key()), daemon=True)
    reader.start()
    reader.join(KEYCHAIN_TIMEOUT)
    key = result[0] if result else None
    if key:
        os.environ["ANTHROPIC_API_KEY"] = key
