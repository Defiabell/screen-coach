"""Config for screen-coach: static constants, plus API-key resolution (env var > Keychain)."""
import os
import threading
from pathlib import Path

import keychain

MODEL = "claude-sonnet-5"          # vision-capable; official-API id, not a gateway alias
MAX_TOKENS = 4096                  # headroom so a dense breakdown's JSON isn't truncated

# Quick mode: translation only, no breakdown. Measured on the same sentence and
# image — full breakdown 7.0-8.0s / 493 output tokens, translation-only 1.3-1.7s
# / 31. The latency is dominated by tokens generated, not by reading the image,
# so dropping the breakdown is what makes it fast; the smaller model is then
# free, since translating a sentence needs no reasoning headroom.
QUICK_MODEL = "claude-haiku-4-5-20251001"
QUICK_MAX_TOKENS = 1024
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
