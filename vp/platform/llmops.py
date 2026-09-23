"""Running paid model calls for many workspaces: keys, concurrency, charges.

* **Keys.** The platform's key comes from the settings. A workspace may
  store its own, under envelope encryption: a fresh 256-bit data key
  encrypts the secret with AES-GCM, and the master key (`VP_MASTER_KEY`,
  the key-management service's stand-in until the deploy) encrypts the
  data key. The table holds only the two ciphertexts and a hint (the last
  four characters); neither plaintext is stored, and rotating the master
  key re-wraps data keys without touching secrets. Calls on a workspace's
  own key are recorded but not charged to the platform budget.
* **Concurrency.** Every worker's calls on one key share a limit, held as
  Postgres advisory locks, one per slot: a call takes a free slot or waits
  for one, so ten workers cannot open ten times the provider's allowance.
* **Retries.** The client retries rate-limit and overload answers itself
  with backoff (six attempts), which is the provider SDK's own mechanism.
"""

from __future__ import annotations

import base64
import contextlib
import os
import random
import time
import zlib
from collections.abc import Iterator
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg_pool import ConnectionPool

from vp.platform.db import tenant_session
from vp.platform.principal import Principal

KEY_VERSION = 1
MAX_RETRIES = 6


class KeysUnavailable(RuntimeError):
    """No master key is configured, so own keys cannot be stored or read."""


def _master(master_key: str | None) -> AESGCM:
    if not master_key:
        raise KeysUnavailable("VP_MASTER_KEY is not set; own keys are off")
    raw = base64.b64decode(master_key)
    if len(raw) != 32:
        raise KeysUnavailable("VP_MASTER_KEY must be 32 bytes, base64-encoded")
    return AESGCM(raw)


def seal(secret: str, master_key: str | None) -> tuple[bytes, bytes]:
    """(ciphertext, wrapped data key) for a secret."""
    data_key = AESGCM.generate_key(bit_length=256)
    nonce, wrap_nonce = os.urandom(12), os.urandom(12)
    ciphertext = nonce + AESGCM(data_key).encrypt(nonce, secret.encode(), b"vp-key")
    wrapped = wrap_nonce + _master(master_key).encrypt(wrap_nonce, data_key, b"vp-dek")
    return ciphertext, wrapped


def unseal(ciphertext: bytes, wrapped: bytes, master_key: str | None) -> str:
    data_key = _master(master_key).decrypt(wrapped[:12], wrapped[12:], b"vp-dek")
    return (
        AESGCM(data_key).decrypt(ciphertext[:12], ciphertext[12:], b"vp-key").decode()
    )


def store_key(
    pool: ConnectionPool, principal: Principal, secret: str, master_key: str | None
) -> str:
    """Store (or replace) the workspace's own model key; returns its hint."""
    secret = secret.strip()
    if len(secret) < 20:
        raise ValueError("that does not look like a provider key")
    ciphertext, wrapped = seal(secret, master_key)
    hint = "…" + secret[-4:]
    with pool.connection() as conn, tenant_session(conn, principal):
        conn.execute(
            "insert into provider_keys (workspace_id, provider, ciphertext, "
            "wrapped_key, key_version, hint, created_by) "
            "values (%s, 'anthropic', %s, %s, %s, %s, %s) "
            "on conflict (workspace_id, provider) do update set "
            "ciphertext = excluded.ciphertext, wrapped_key = excluded.wrapped_key, "
            "key_version = excluded.key_version, hint = excluded.hint, "
            "created_by = excluded.created_by, created_at = now()",
            (
                principal.workspace,
                ciphertext,
                wrapped,
                KEY_VERSION,
                hint,
                principal.user_id,
            ),
        )
    return hint


def key_hint(pool: ConnectionPool, principal: Principal) -> str | None:
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "select hint from provider_keys where provider = 'anthropic'"
        ).fetchone()
    return row[0] if row else None


def delete_key(pool: ConnectionPool, principal: Principal) -> bool:
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "delete from provider_keys where provider = 'anthropic' returning 1"
        ).fetchone()
    return row is not None


def own_key(
    pool: ConnectionPool, principal: Principal, master_key: str | None
) -> str | None:
    """The workspace's own key in plaintext, for the length of a job; or None."""
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "select ciphertext, wrapped_key from provider_keys "
            "where provider = 'anthropic'"
        ).fetchone()
    if row is None:
        return None
    return unseal(bytes(row[0]), bytes(row[1]), master_key)


# --------------------------------------------------------------- concurrency


class Slots:
    """At most `slots` concurrent holders of `name`, across every process."""

    def __init__(self, pool: ConnectionPool, name: str, slots: int) -> None:
        self.pool = pool
        self.key = zlib.crc32(name.encode()) & 0x7FFFFFFF
        self.slots = slots

    @contextlib.contextmanager
    def hold(self, timeout: float = 600.0) -> Iterator[int]:
        deadline = time.monotonic() + timeout
        with self.pool.connection() as conn:
            while True:
                for slot in range(self.slots):
                    got = conn.execute(
                        "select pg_try_advisory_lock(%s, %s)", (self.key, slot)
                    ).fetchone()
                    if got and got[0]:
                        try:
                            yield slot
                        finally:
                            conn.execute(
                                "select pg_advisory_unlock(%s, %s)", (self.key, slot)
                            )
                        return
                if time.monotonic() > deadline:
                    raise TimeoutError("no model-call slot came free")
                time.sleep(0.1 + random.random() * 0.2)


class LimitedMessages:
    """`client.messages` with every `create` holding a slot; batches pass through
    (the provider queues them, so they do not occupy a connection here)."""

    def __init__(self, messages: Any, slots: Slots) -> None:
        self._messages = messages
        self._slots = slots
        self.batches = getattr(messages, "batches", None)

    def create(self, **kwargs: Any) -> Any:
        with self._slots.hold():
            return self._messages.create(**kwargs)


class LimitedBeta:
    """`client.beta`, for the compiler's refusal fallback, under the same slots."""

    def __init__(self, beta: Any, slots: Slots) -> None:
        self.messages = LimitedMessages(beta.messages, slots)


class LimitedClient:
    def __init__(self, client: Any, slots: Slots) -> None:
        self.messages = LimitedMessages(client.messages, slots)
        self.beta = LimitedBeta(client.beta, slots)


def client_for(
    pool: ConnectionPool,
    principal: Principal,
    platform_key: str | None,
    master_key: str | None,
    slots: int = 4,
) -> tuple[Any, str]:
    """A limited client for this workspace, and who pays: 'own_key' or 'platform'.

    Raises:
        KeysUnavailable: neither the workspace nor the platform has a key.
    """
    import anthropic

    mine = own_key(pool, principal, master_key) if master_key else None
    key, paid_by = (mine, "own_key") if mine else (platform_key, "platform")
    if not key:
        raise KeysUnavailable("no model key: the platform has none configured")
    client = anthropic.Anthropic(api_key=key, max_retries=MAX_RETRIES)
    name = f"anthropic:{principal.workspace}" if mine else "anthropic:platform"
    return LimitedClient(client, Slots(pool, name, slots)), paid_by
