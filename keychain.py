"""Keychain-backed storage for the Anthropic API key, via Security.framework
(pyobjc). A .app launched from Finder / Login Items does not inherit the
shell's env vars, so Keychain — not a plaintext config file — is the
persistent store for a Finder-launched Screen Coach."""
from __future__ import annotations

import threading

from Security import (
    SecItemAdd,
    SecItemCopyMatching,
    SecItemDelete,
    SecItemUpdate,
    errSecDuplicateItem,
    kSecAttrAccount,
    kSecAttrService,
    kSecClass,
    kSecClassGenericPassword,
    kSecMatchLimit,
    kSecMatchLimitOne,
    kSecReturnData,
    kSecValueData,
)

SERVICE = "com.jinkun.screen-coach"
ACCOUNT = "ANTHROPIC_API_KEY"


def _query() -> dict:
    return {
        kSecClass: kSecClassGenericPassword,
        kSecAttrService: SERVICE,
        kSecAttrAccount: ACCOUNT,
    }


def get_key() -> str | None:
    query = {**_query(), kSecReturnData: True, kSecMatchLimit: kSecMatchLimitOne}
    status, result = SecItemCopyMatching(query, None)
    if status != 0 or result is None:
        return None
    return bytes(result).decode("utf-8")


WRITE_TIMEOUT = 5.0  # seconds; see set_key()


def _write(value: str) -> None:
    # Try add first, fall back to update on duplicate — don't gate on
    # get_key() first. get_key() collapses any non-success OSStatus
    # (including a denied Keychain-access prompt) to "not found", so a
    # check-then-act here can believe there's no existing item when there
    # actually is one; SecItemAdd would then fail with the unrecoverable
    # errSecDuplicateItem (-25299) and no UI path out.
    data = value.encode("utf-8")
    status, _item = SecItemAdd({**_query(), kSecValueData: data}, None)
    if status == errSecDuplicateItem:  # already there — overwrite
        status = SecItemUpdate(_query(), {kSecValueData: data})
    if status != 0:
        raise RuntimeError(f"Keychain write failed (OSStatus {status})")


def set_key(value: str) -> None:
    """Store the key, bounded by WRITE_TIMEOUT.

    SecItemAdd/SecItemUpdate go through the same securityd authorization
    machinery as the read path and can block forever for the same reason: when
    the stored item's ACL no longer matches the running binary's signature,
    securityd waits on an authorization dialog that an LSUIElement app never
    gets to show. This is called from _prompt_for_api_key() *before* the menu
    bar and hotkey exist, so an unbounded hang there is a total silent freeze
    with no fallback UI. Timing out raises instead, which the caller already
    surfaces in the floating window.
    """
    error: list[BaseException] = []

    def _run() -> None:
        try:
            _write(value)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread
            error.append(exc)

    # daemon: if securityd never answers, this thread stays blocked in mach_msg
    # for the life of the process — it must not keep the app alive.
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
    SecItemDelete(_query())  # errSecItemNotFound (-25300) is fine — nothing to clean up
