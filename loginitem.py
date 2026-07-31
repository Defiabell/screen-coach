"""Toggle Screen Coach as a macOS login item via System Events (AppleScript).
Chosen over ServiceManagement/SMAppService: no extra pyobjc framework or
entitlement plumbing needed for a single-user menu-bar tool — the tradeoff
is a one-time Automation permission prompt for System Events.

Login items are looked up and removed by `path`, not `name`: System Events
reports a login item's name in the system display locale (verified: adding
Calculator.app shows up with name "计算器" on a zh-Hans system), so matching
by name is unreliable. `path` is stable regardless of locale."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _bundle_path() -> str:
    """Path to the running .app bundle. In a py2app build, sys.executable is
    .../Contents/MacOS/Screen Coach; walk up to the first *.app ancestor."""
    for parent in Path(sys.executable).parents:
        if parent.suffix == ".app":
            return str(parent)
    raise RuntimeError("not running from a .app bundle")


def _osascript(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def is_login_item() -> bool:
    path = _bundle_path()
    result = _osascript(
        f'tell application "System Events" to get the path of every login item '
        f'whose path is "{path}"'
    )
    return bool(result)


def set_login_item(enabled: bool) -> None:
    path = _bundle_path()
    if enabled:
        if is_login_item():
            return
        _osascript(
            f'tell application "System Events" to make login item at end of login items '
            f'with properties {{path:"{path}", hidden:false}}'
        )
    else:
        _osascript(
            f'tell application "System Events" to delete (every login item whose path is "{path}")'
        )
