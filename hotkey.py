"""Pure hotkey logic: matching, recording, formatting, prefs normalization.

Deliberately AppKit-free so it's unit-testable; app.py owns the CGEventTap and
the recorder window and calls in here for every decision.
"""

# NSEvent device-independent modifier bits. Listed in the order macOS renders
# modifier symbols (⌃⌥⇧⌘), which format_binding relies on.
_MODIFIERS = [
    ("ctrl", 1 << 18, "⌃"),
    ("alt", 1 << 19, "⌥"),
    ("shift", 1 << 17, "⇧"),
    ("cmd", 1 << 20, "⌘"),
]
_MASKS = {name: mask for name, mask, _ in _MODIFIERS}

_ESCAPE_KEYCODE = 53

DEFAULT = {"keycode": 14, "modifiers": ["cmd", "shift"], "display": "E"}


def matches(binding: dict, keycode: int, flags: int) -> bool:
    """True when the keydown is exactly this binding: same keycode, and each of
    the four modifier bits present iff the binding names it. Extra modifiers
    (⌃⇧⌘E against a ⇧⌘E binding) don't match; device-dependent low bits
    (left-vs-right cmd etc.) are ignored."""
    if keycode != binding["keycode"]:
        return False
    wanted = set(binding["modifiers"])
    return all(bool(flags & mask) == (name in wanted) for name, mask in _MASKS.items())


def record_outcome(keycode: int, flags: int, chars: str) -> tuple:
    """Classify a keydown seen by the recorder window.

    Returns ("cancel", None) on Esc, ("ignore", None) for combos that would
    fire on normal typing (no ⌘/⌥/⌃), or ("set", binding). The display label
    comes from charactersIgnoringModifiers; non-printables fall back to the
    raw keycode so the menu still shows *something* identifiable."""
    if keycode == _ESCAPE_KEYCODE:
        return ("cancel", None)
    mods = [name for name, mask, _ in _MODIFIERS if flags & mask]
    if not any(m in mods for m in ("cmd", "alt", "ctrl")):
        return ("ignore", None)
    display = chars.upper() if chars and chars.isprintable() else f"#{keycode}"
    return ("set", {"keycode": keycode, "modifiers": sorted(mods), "display": display})


def format_binding(binding: dict) -> str:
    """Render as macOS shows shortcuts, e.g. ⌃⌥⇧⌘S."""
    wanted = set(binding["modifiers"])
    symbols = "".join(sym for name, _, sym in _MODIFIERS if name in wanted)
    return symbols + binding["display"]


def normalize(value) -> dict:
    """Turn whatever prefs.json held into a usable binding; anything malformed
    (or absent) means the stock ⇧⌘E. Always returns a fresh copy so callers
    can't mutate DEFAULT through it."""
    try:
        keycode = value["keycode"]
        mods = value["modifiers"]
        display = value["display"]
        if (isinstance(keycode, int)
                and isinstance(display, str)
                and mods
                and all(m in _MASKS for m in mods)):
            return {"keycode": keycode, "modifiers": list(mods), "display": display}
    except (TypeError, KeyError):
        pass
    return {"keycode": DEFAULT["keycode"],
            "modifiers": list(DEFAULT["modifiers"]),
            "display": DEFAULT["display"]}
