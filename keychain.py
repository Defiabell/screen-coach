"""Keychain-backed storage for the Anthropic API key, via /usr/bin/security.

A .app launched from Finder / Login Items does not inherit the shell's env
vars, so Keychain — not a plaintext config file — is the persistent store for
a Finder-launched Screen Coach.

Why the security CLI and not the SecItem API (which this module used first):
items created through SecItemAdd get a keychain partition list pinned to the
creating binary's *cdhash* when the signing cert has no team ID — true for
both the self-signed dev cert and ad-hoc release signing. Every rebuild
changes the cdhash, securityd then blocks the silent read waiting on a
confirmation dialog an LSUIElement app can never show, and the app concluded
"no key" and asked again. Re-entering only re-stamped the partition until the
next rebuild. Measured 2026-08-16 with two differently-signed binaries:
reads and even metadata-only updates from the second binary hang; only
kSecValueData updates pass (the encrypt ACL admits any app), which is why
re-typing the key always "worked".

Items created by /usr/bin/security instead carry partition "apple-tool:" and
an ACL trusting the security tool itself — both stable across app rebuilds,
because the reader/writer is always the same Apple-signed binary. The trade-
off (any process able to run `security` can read the item after the user's
one-time grant semantics) matches the original design intent of an
unprompted read.
"""
from __future__ import annotations

import re
import subprocess
import threading

SERVICE = "com.jinkun.screen-coach"
ACCOUNT = "ANTHROPIC_API_KEY"

_SECURITY = "/usr/bin/security"

# Bounds every securityd round-trip: a read/write against an item whose ACL
# doesn't admit the security tool (e.g. one created by the old SecItem code)
# blocks on a dialog instead of failing — the timeout turns that into a normal
# "no key" / error path.
READ_TIMEOUT = 5.0
WRITE_TIMEOUT = 5.0

# The value is embedded in a `security -i` command line, so restrict it to
# printable ASCII without quotes/backslashes/whitespace. Real Anthropic keys
# (sk-ant-…) are alphanumerics plus - and _, far inside this set.
_SAFE_VALUE = re.compile(r'^[\x21-\x7e]+$')


def get_key() -> str | None:
    try:
        out = subprocess.run(
            [_SECURITY, "find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"],
            capture_output=True,
            text=True,
            timeout=READ_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.rstrip("\n") or None


def _write(value: str) -> None:
    if not _SAFE_VALUE.match(value) or '"' in value or "\\" in value:
        raise RuntimeError("API key 含空白或引号等非法字符，无法保存")
    # Delete-then-add, not add -U: updating keeps the existing item's ACL and
    # partition list, which is exactly the state this module exists to escape
    # (and the migration path for items the old SecItem code created — the
    # security tool CAN silently delete an item it cannot read).
    subprocess.run(
        [_SECURITY, "delete-generic-password", "-s", SERVICE, "-a", ACCOUNT],
        capture_output=True,
        timeout=WRITE_TIMEOUT,
    )  # item-not-found is fine — nothing to replace
    # -i reads commands from stdin, keeping the secret out of argv (visible in
    # `ps` for the process's lifetime otherwise).
    proc = subprocess.run(
        [_SECURITY, "-i"],
        input=f'add-generic-password -s {SERVICE} -a {ACCOUNT} -w "{value}"\n',
        capture_output=True,
        text=True,
        timeout=WRITE_TIMEOUT,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Keychain write failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )


def set_key(value: str) -> None:
    """Store the key, bounded by WRITE_TIMEOUT.

    The write is wrapped in a joined thread rather than relying on subprocess
    timeouts alone: it runs from _prompt_for_api_key() before the menu bar and
    hotkey exist, so any unbounded hang there is a total silent freeze with no
    fallback UI. Timing out raises instead, which the caller already surfaces
    in the floating window.
    """
    error: list[BaseException] = []

    def _run() -> None:
        try:
            _write(value)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread
            error.append(exc)

    # daemon: if securityd never answers, this thread must not keep the app alive.
    writer = threading.Thread(target=_run, daemon=True)
    writer.start()
    writer.join(WRITE_TIMEOUT)
    if writer.is_alive():
        raise RuntimeError(
            f"Keychain 写入超时（{WRITE_TIMEOUT:g}s）——"
            "钥匙串授权对话框可能没弹出来"
        )
    if error:
        raise error[0]


def delete_key() -> None:
    try:
        subprocess.run(
            [_SECURITY, "delete-generic-password", "-s", SERVICE, "-a", ACCOUNT],
            capture_output=True,
            timeout=WRITE_TIMEOUT,
        )  # item-not-found is fine — nothing to clean up
    except (subprocess.TimeoutExpired, OSError):
        pass
