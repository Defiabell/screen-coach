"""Show an HTML file in a floating, always-on-top window. Run as its own process.

TTS goes through macOS `say` (via a pywebview js_api bridge) instead of the
webview's Web Speech API, because WKWebView does not reliably expose installed
Premium/Enhanced system voices. `say` always uses the real system voices.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import webview

_PREF = ("premium", "enhanced")
_NAMED = ("Ava", "Zoe", "Evan", "Allison", "Serena", "Samantha")


def _best_voice() -> str | None:
    """Pick the best installed en_US voice for `say` (Premium/Enhanced first)."""
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    except Exception:
        return None
    names = []
    for line in out.splitlines():
        parts = re.split(r"\s{2,}", line.strip(), maxsplit=2)
        if len(parts) >= 2 and "en_US" in parts[1]:
            names.append(parts[0])
    for kw in _PREF:
        for name in names:
            if kw in name.lower():
                return name
    for kw in _NAMED:  # honor _NAMED's declared preference order, not alphabetical
        for name in names:
            if name.split()[0] == kw:
                return name
    return names[0] if names else None


class Api:
    """Exposed to the page as window.pywebview.api."""

    def __init__(self):
        self._voice = _best_voice()
        self._proc: subprocess.Popen | None = None

    def speak(self, text: str, wpm: int = 190) -> None:
        if not text:
            return
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()  # cut off the previous utterance
        cmd = ["say"]
        if self._voice:
            cmd += ["-v", self._voice]
        # "--" ends option parsing so a sentence starting with "-" isn't read as a flag
        cmd += ["-r", str(int(wpm)), "--", text]
        self._proc = subprocess.Popen(cmd)


def main() -> None:
    # argv may be [viewer.py, html], [app.py, --viewer, html], or [appbin, --viewer, html]
    args = [a for a in sys.argv[1:] if a != "--viewer"]
    if not args:
        raise SystemExit("usage: viewer.py <html-path>")
    html = args[-1]
    webview.create_window(
        "screen-coach",
        url=Path(html).as_uri(),
        width=560,
        height=680,
        on_top=True,
        js_api=Api(),
    )
    webview.start()


if __name__ == "__main__":
    main()
