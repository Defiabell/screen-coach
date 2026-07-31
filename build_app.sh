#!/usr/bin/env bash
# Build Screen Coach.app, codesign it with a STABLE identity, and install to
# /Applications.
#
# The signing identity matters more than it looks. macOS keys both the Keychain
# item's ACL and the Accessibility (TCC) grant to the app's code signature, and
# an ad-hoc signature (`--sign -`) gets a fresh hash on every build. Each
# rebuild therefore looked like a *different* app: the stored API key became
# unreadable (SecItemCopyMatching hung in securityd waiting on an authorization
# dialog an LSUIElement app can't show) and the Accessibility toggle stayed
# visibly ON while AXIsProcessTrusted() returned False. Signing with a stable
# self-signed certificate keeps one identity across builds, so both grants are
# given once.
set -euo pipefail
cd "$(dirname "$0")"

# Stable self-signed code-signing certificate. Create one if you have none:
#   Keychain Access -> Certificate Assistant -> Create a Certificate…
#   type "Code Signing", self-signed, any name.
# Override with SIGN_IDENTITY=<name>. With neither set, the first code-signing
# identity in the Keychain is used — any stable one will do, the point is only
# that it doesn't change between builds.
SIGN_IDENTITY="${SIGN_IDENTITY:-}"

echo "==> Step 1: Clean previous build"
rm -rf build dist

echo "==> Step 2: py2app build"
.venv/bin/python setup.py py2app

if [ -z "$SIGN_IDENTITY" ]; then
    SIGN_IDENTITY=$(security find-identity -v -p codesigning \
        | sed -n 's/^ *1) [0-9A-F]* "\(.*\)"$/\1/p')
    [ -n "$SIGN_IDENTITY" ] || {
        echo "ERROR: no code-signing identity found in the Keychain."
        echo "       Create one: Keychain Access -> Certificate Assistant ->"
        echo "       Create a Certificate…, type 'Code Signing', self-signed."
        echo "       Then re-run, or set SIGN_IDENTITY=<name>."
        exit 1
    }
fi

echo "==> Step 3: Codesign with stable identity ($SIGN_IDENTITY)"
security find-identity -v -p codesigning | grep -qF "$SIGN_IDENTITY" || {
    echo "ERROR: code-signing identity '$SIGN_IDENTITY' not found in the Keychain."
    exit 1
}
codesign --force --deep --sign "$SIGN_IDENTITY" --identifier com.jinkun.screen-coach \
    "dist/Screen Coach.app"
codesign --verify --deep --strict "dist/Screen Coach.app"

echo "==> Step 4: Install to /Applications"
osascript -e 'tell application "Screen Coach" to quit' 2>/dev/null || true
pkill -f "Screen Coach.app/Contents/MacOS/Screen Coach" 2>/dev/null || true
sleep 1
# rsync --delete rather than `rm -rf` + `cp -R`: deleting the bundle and copying
# a fresh one gives every file a new inode, and macOS then treats the installed
# app as a new object — the Accessibility grant keeps showing as enabled while
# CGEventTapCreate returns NULL, and the Keychain item's ACL stops matching.
# Syncing in place keeps the bundle's identity stable across rebuilds, so the
# grants given once stay valid.
rsync -a --delete "dist/Screen Coach.app/" "/Applications/Screen Coach.app/"
xattr -cr "/Applications/Screen Coach.app"

echo "==> Step 5: Launch"
open "/Applications/Screen Coach.app"

# `open` returning 0 only means launch was accepted, not that the process
# didn't immediately crash (e.g. a missing bundled dependency) — confirm it's
# actually still running before declaring victory.
sleep 2
pgrep -f "Screen Coach.app/Contents/MacOS/Screen Coach" >/dev/null \
    || { echo "ERROR: app did not stay running"; exit 1; }

echo "Done. Screen Coach installed and running."
