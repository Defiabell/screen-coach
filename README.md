# screen-coach

Mac menu-bar tool: pick an English sentence on screen → Claude breaks it down
(translation, 拆句, 生词, 用法) in a floating window with pronunciation playback
and a history list.

## Two ways to grab the text

- **A persistent region** — leave a thin framing rectangle over the area you
  read (subtitles, a document pane) and analyze whatever is inside it. The
  frame is click-through, so it never gets in the way of the app underneath.
  Menu → `Adjust Region…` makes it draggable and resizable; Esc finishes.
- **Drag-select** — pick a one-off area with the crosshair, as in any
  screenshot tool.

## Three ways to trigger it

- **The floating 📖 ball** — draggable, always on top, remembers where you put
  it. A left click runs whichever grab mode `Use Region` selects; a right click
  opens the same menu as the menu-bar icon. It exists because the menu-bar item
  lives on whichever display owns the menu bar — with an external monitor
  attached it can sit on a screen you aren't watching, and then there is
  nothing to click. The ball anchors itself to the built-in display instead.
- **The menu bar** — `Analyze Region` and `Analyze Selection` are always both
  available there regardless of the mode switch.
- **⇧⌘E** — a global hotkey for drag-select. Needs Accessibility permission;
  everything else works without it. Rebindable: menu → `Set Hotkey…` opens a
  small panel — press the new combo (it must include ⌘/⌥/⌃; Esc cancels) and
  it applies immediately, no restart. The menu item shows the current binding.

`Use Region` in the menu is a mode switch, not a display toggle: checked means
a ball click analyzes the persistent region (and shows the frame so you can see
what that is), unchecked means it drag-selects.

Playback is never automatic: click 🔊 (normal speed) or 🐢 (slow) to hear a
sentence or a word.

Analyses are appended to `~/Library/Application Support/Screen Coach/history.jsonl`
and the last 20 are listed in the window; clicking one re-renders it.

## Build and install

One-time setup (skip if `.venv` already exists):

    cd personal-projects/english-learning/screen-coach
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

Then build and install:

    ./build_app.sh

This builds `Screen Coach.app`, signs it with a stable certificate (see
[Permissions](#permissions-macos)), installs it to `/Applications` with `rsync`,
and launches it. After that, launch it like any other app — Spotlight,
Launchpad, or `/Applications`.

First launch:
1. The 📖 menu-bar icon and the floating ball appear. **No API key is needed to
   try it**: with no key set, requests route through a small trial proxy
   (`trial-worker/`, a Cloudflare Worker holding the author's key) with daily
   limits — per device, per IP, and a global budget. When the quota runs out,
   or any time you want unlimited direct access, use menu → `Set API Key…` to
   store your own Anthropic key. It goes into macOS Keychain (service
   `com.jinkun.screen-coach`), not a file, so you only enter it once.
2. Trigger an analysis once; macOS will prompt for Screen Recording. Grant it,
   then quit and reopen the app.
3. For the ⇧⌘E hotkey, grant Accessibility when prompted. Skip this if you only
   use the ball and the menu.
4. Optionally check `Launch at Login` from the 📖 menu.

To rebuild after changing the code, re-run `./build_app.sh`. Permissions
survive rebuilds — see the note below for why that isn't automatic.

## Tests

    .venv/bin/python -m pytest tests/ -q

106 tests, no GUI or API key required: the geometry, clamping, coordinate
conversion, capture ordering, Keychain timeouts and mode dispatch are all
covered as pure logic. Window rendering and real mouse dragging are verified by
hand.

## Permissions (macOS)

- **Screen Recording** — required by `screencapture`. Grant when first
  prompted (System Settings → Privacy & Security → Screen Recording).
- **Accessibility** — required only for the ⇧⌘E hotkey. The ball, its
  right-click menu and the menu bar all work without it. If the hotkey stays
  dead after granting it, remove Screen Coach from the Accessibility list
  entirely and let the app re-add itself on next launch — a stale entry displays
  as enabled while `CGEventTapCreate` still returns NULL.
- **Note on rebuilds** — `build_app.sh` signs with a stable self-signed
  certificate (whichever code-signing identity your Keychain holds first;
  override with `SIGN_IDENTITY=<name>`) and installs with `rsync` rather than
  delete-and-copy. Both matter: an ad-hoc signature gets a new hash every build
  and a deleted-then-copied bundle gets new inodes, either of which makes macOS
  treat the app as a different one — the Accessibility toggle then reads as
  enabled while `AXIsProcessTrusted()` returns False, and the Keychain item's
  ACL stops matching (which used to hang the app on launch).
- **Automation (System Events)** — required for the "Launch at Login"
  toggle. If toggling it shows an error, grant it under System Settings →
  Privacy & Security → Automation → Screen Coach → System Events.

## Layout

| File | Responsibility |
|---|---|
| `app.py` | menu, triggers, the shared analysis pipeline |
| `region.py` | the persistent frame: geometry, window, its own screenshot |
| `floatball.py` | the draggable ball and its right-click menu |
| `capture.py` | `screencapture` wrappers (interactive and fixed-rect) |
| `analyzer.py` | the prompt and the structured-output schema |
| `render.py` | the breakdown HTML |
| `viewer.py` | the floating window (own process; `say`-based TTS) |
| `keychain.py` / `config.py` | API key storage and resolution |

`region.py` deliberately knows nothing about `analyzer`/`render`/the API — it
deals only in geometry and pixels, which is what makes it testable without a
GUI, a permission, or a key. `app.py` decides what to do with the image.

## Things that will bite you

Hard-won, all of them observed rather than theorised:

- **AppKit and `screencapture` disagree about the y axis.** AppKit measures
  upward from the bottom-left of the built-in display; `screencapture -R`
  measures downward from its top. `region.to_capture_rect()` converts, and a
  test pins the case that was verified against real pixels.
- **`NSScreen.screens()[0]` is not the built-in display** — it's whichever
  screen owns the menu bar. Anything that means "put this somewhere the user can
  see" must look for the screen whose frame origin is `(0, 0)`.
- **`orderOut_` doesn't mean the screen has redrawn.** Capturing straight after
  hiding the frame catches its own border. `region.capture()` waits a frame.
- **Blocking I/O on the main thread kills this app silently.** An unbounded
  Keychain read once froze it before the menu bar existed, so it looked simply
  dead. Keychain reads and writes are now bounded, `screencapture` has a
  timeout, and the API-key prompt happens after the menu is up rather than
  before.
- **A passive `NSEvent` global monitor never sees Command-modified keys.** Three
  modifier combinations were tried before the mechanism turned out to be wrong;
  the hotkey uses a `CGEventTap` on the main run loop.
- **In a py2app bundle `Path(__file__).parent` can be inside a zip.** User data
  belongs in `~/Library/Application Support/`, not next to the code.
- **pyobjc subclasses need `objc.super(...)`**, and `monkeypatch.setattr` on an
  AppKit class method is silently ignored — patch the module attribute instead.

## Notes

- The API key lives in macOS Keychain (service `com.jinkun.screen-coach`), never
  in a file or an environment variable. `_get_client()` pins
  `base_url="https://api.anthropic.com"` so a shell pointing at an internal
  gateway can't silently redirect it.
- Model is `config.MODEL` (`claude-sonnet-5`). Measured on a real sentence:
  sonnet-5 ≈ 3s, haiku-4.5 ≈ 4s but noisier, and the `effort` parameter made it
  *slower* while being rejected outright by opus-4-1 and haiku-4-5 — hence its
  absence.
- Runtime state (`history.jsonl`, `region.json`, `ball.json`, `prefs.json`) is
  under `~/Library/Application Support/Screen Coach/`. A debug log is at
  `~/Library/Logs/screen-coach-debug.log`.

## Trial proxy (for forks)

`trial-worker/` is a Cloudflare Worker that lets keyless installs work out of
the box using the deployer's API key, within limits (20/device/day,
40/IP/day, $1/day global — all constants in `src/index.js`). To run your own:

    cd trial-worker
    wrangler kv namespace create TRIAL_KV     # put the id into wrangler.jsonc
    wrangler deploy
    wrangler secret put ANTHROPIC_API_KEY     # paste your key

Then point `TRIAL_BASE_URL` in `config.py` at your worker URL. `GET /` on the
worker shows the day's aggregate spend.
