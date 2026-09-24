"""Optional proof that a person controls an address (docs/shadow.md).

The person signs a one-time message with their wallet (EIP-191
``personal_sign``); the platform recovers the signer from the signature.
Nothing is signed here, nothing is sent to the chain, and no key reaches
the platform. The venue trades through a proxy wallet, so the signer
counts as the owner of an address when it is that address or the venue's
public profile names the address as the signer's proxy.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from eth_hash.auto import keccak
from eth_keys import keys


def message(address: str, nonce: str) -> str:
    return (
        f"vibe-predict: I control {address.lower()} and link its public record "
        f"to my account. Nonce: {nonce}. This signature authorises no transaction."
    )


def recover(text: str, signature: str) -> str:
    """The address that signed ``text`` (EIP-191), lower case."""
    raw = bytes.fromhex(signature.removeprefix("0x"))
    if len(raw) != 65:
        raise ValueError("a signature is 65 bytes")
    v = raw[64]
    v = v - 27 if v >= 27 else v
    if v not in (0, 1):
        raise ValueError("bad recovery id")
    body = text.encode()
    digest = keccak(b"\x19Ethereum Signed Message:\n" + str(len(body)).encode() + body)
    sig = keys.Signature(raw[:64] + bytes([v]))
    return sig.recover_public_key_from_msg_hash(digest).to_checksum_address().lower()


def owns(
    address: str,
    text: str,
    signature: str,
    profile: Callable[[str], dict[str, Any] | None],
) -> bool:
    """Whether the signature proves control of ``address``."""
    try:
        signer = recover(text, signature)
    except ValueError:
        return False
    if signer == address.lower():
        return True
    found = profile(signer)
    return (
        bool(found) and str(found.get("proxyWallet") or "").lower() == address.lower()
    )
