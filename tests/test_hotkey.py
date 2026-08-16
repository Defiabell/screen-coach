"""Pure hotkey logic: matching, recording outcomes, formatting, prefs handling.
No AppKit here — flags are plain ints using NSEvent's device-independent bits."""
import hotkey

CMD = 1 << 20
SHIFT = 1 << 17
ALT = 1 << 19
CTRL = 1 << 18

SHIFT_CMD_E = {"keycode": 14, "modifiers": ["cmd", "shift"], "display": "E"}


# --- matches: exact match on the four modifier bits -------------------------

def test_matches_the_configured_combo():
    assert hotkey.matches(SHIFT_CMD_E, 14, CMD | SHIFT)


def test_rejects_wrong_keycode():
    assert not hotkey.matches(SHIFT_CMD_E, 15, CMD | SHIFT)


def test_rejects_missing_modifier():
    assert not hotkey.matches(SHIFT_CMD_E, 14, CMD)


def test_rejects_extra_modifier():
    # ⌃⇧⌘E must NOT fire a ⇧⌘E binding (the old subset match did).
    assert not hotkey.matches(SHIFT_CMD_E, 14, CMD | SHIFT | CTRL)


def test_ignores_device_dependent_bits():
    # Real NSEvent flags carry extra low bits (e.g. left-vs-right cmd);
    # only the four device-independent bits may matter.
    assert hotkey.matches(SHIFT_CMD_E, 14, CMD | SHIFT | 0x108)


# --- record_outcome: what a keydown in the recorder window means ------------

def test_recording_a_valid_combo_returns_binding():
    action, binding = hotkey.record_outcome(1, CMD | ALT, "s")
    assert action == "set"
    assert binding == {"keycode": 1, "modifiers": ["alt", "cmd"], "display": "S"}


def test_recording_escape_cancels():
    assert hotkey.record_outcome(53, 0, "\x1b") == ("cancel", None)


def test_recording_escape_with_modifiers_still_cancels():
    assert hotkey.record_outcome(53, CMD, "\x1b") == ("cancel", None)


def test_recording_without_cmd_alt_ctrl_is_ignored():
    # A bare letter (or shift+letter) would fire on normal typing.
    assert hotkey.record_outcome(14, 0, "e") == ("ignore", None)
    assert hotkey.record_outcome(14, SHIFT, "E") == ("ignore", None)


def test_recording_non_printable_key_falls_back_to_keycode_label():
    action, binding = hotkey.record_outcome(126, CMD, "")  # cmd+up-arrow
    assert action == "set"
    assert binding["display"] == "#126"


# --- format_binding: menu-title rendering ------------------------------------

def test_format_renders_symbols_in_standard_order():
    b = {"keycode": 1, "modifiers": ["cmd", "shift", "alt", "ctrl"], "display": "S"}
    assert hotkey.format_binding(b) == "⌃⌥⇧⌘S"


def test_format_default_binding():
    assert hotkey.format_binding(SHIFT_CMD_E) == "⇧⌘E"


# --- normalize: whatever prefs.json held → a usable binding ------------------

def test_normalize_missing_pref_gives_default():
    assert hotkey.normalize(None) == hotkey.DEFAULT


def test_normalize_valid_binding_round_trips():
    assert hotkey.normalize(dict(SHIFT_CMD_E)) == SHIFT_CMD_E


def test_normalize_malformed_pref_gives_default():
    for bad in ("garbage", {}, {"keycode": "x", "modifiers": ["cmd"], "display": "E"},
                {"keycode": 14, "modifiers": ["hyper"], "display": "E"},
                {"keycode": 14, "modifiers": [], "display": "E"}):
        assert hotkey.normalize(bad) == hotkey.DEFAULT


def test_normalize_returns_a_copy_not_the_default_itself():
    got = hotkey.normalize(None)
    got["modifiers"].append("ctrl")
    assert hotkey.DEFAULT["modifiers"] == ["cmd", "shift"]
