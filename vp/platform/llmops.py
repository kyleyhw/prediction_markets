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
* **Routes** (docs/models.md). A workspace's own model, from any
  provider, answers its calls; without one, the platform's demo model
  does, for people in a country it may serve and within today's allowance
  of demo calls, counted before each call.
"""

from __future__ import annotations

import base64
import contextlib
import os
import random
import time
import zlib
from collections.abc import Callable, Iterator
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from psycopg_pool import ConnectionPool

from vp.llm import FREE_TIER_COUNTRIES, PROVIDERS
from vp.llm.openai_compat import check_address
from vp.llm.providers import PAID_ONLY_COUNTRIES
from vp.platform.config import Settings
from vp.platform.db import tenant_session
from vp.platform.jobs import JobRefused
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


class DemoUnavailable(KeysUnavailable, JobRefused):
    """The free demo model cannot answer this person now; ``code`` says why:
    ``country_needed``, ``region_blocked``, ``used_up`` or ``none``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


MESSAGES = {
    "none": "No model is set up here yet: connect your own model in Settings.",
    "country_needed": (
        "Before using the free demo model, say which country you are in "
        "(Settings, Where you are)."
    ),
    "region_blocked": (
        "The free demo model cannot be offered where you are: Google does "
        "not offer its free AI service in your country. You can still use "
        "everything with an AI model of your own (Settings, Your AI model), "
        "or run your own copy of the app on your computer."
    ),
    "region_paid_only": (
        "The free demo model cannot be offered where you are: Google's terms "
        "do not allow its free AI service to be used for people in the "
        "European Economic Area, Switzerland or the United Kingdom. You can "
        "still use everything with an AI model of your own (Settings, Your "
        "AI model), or run your own copy of the app on your computer."
    ),
    "used_up": (
        "The free demo model's allowance for today is used up; it starts "
        "again at midnight UTC. Your own model has no such limit."
    ),
}


def _unavailable(code: str) -> DemoUnavailable:
    return DemoUnavailable(code, MESSAGES[code])


def store_connection(
    pool: ConnectionPool,
    principal: Principal,
    *,
    provider: str,
    model: str | None,
    key: str | None,
    base_url: str | None,
    master_key: str | None,
    allow_private: bool = False,
) -> str:
    """Connect the workspace's own model (replacing any other); returns the
    key's hint. Raises ValueError for a connection that cannot work."""
    p = PROVIDERS.get(provider)
    if p is None:
        raise ValueError(f"unknown provider {provider!r}")
    if p.own_copy_only and not allow_private:
        raise ValueError(f"{p.label} works only on your own copy")
    model = (model or "").strip() or None
    if model is None and p.kind != "anthropic":
        raise ValueError(f"name the {p.label} model to use")
    key = (key or "").strip() or None
    if p.needs_key and (key is None or len(key) < 20):
        raise ValueError("that does not look like a provider key")
    if p.kind == "command":
        raise ValueError("a program is set by whoever runs the copy, not here")
    # Only an OpenAI-compatible provider without a preset address takes one
    # from the person.
    typed = p.kind == "openai" and p.base_url is None
    base_url = ((base_url or "").strip() or None) if typed else None
    if typed:
        if base_url is None:
            raise ValueError("give the model's address")
        check_address(base_url, allow_private)
    ciphertext, wrapped = seal(key or "", master_key)
    hint = "…" + key[-4:] if key else ""
    with pool.connection() as conn, tenant_session(conn, principal):
        conn.execute("delete from provider_keys where provider <> %s", (provider,))
        conn.execute(
            "insert into provider_keys (workspace_id, provider, ciphertext, "
            "wrapped_key, key_version, hint, created_by, model, base_url) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "on conflict (workspace_id, provider) do update set "
            "ciphertext = excluded.ciphertext, wrapped_key = excluded.wrapped_key, "
            "key_version = excluded.key_version, hint = excluded.hint, "
            "created_by = excluded.created_by, created_at = now(), "
            "model = excluded.model, base_url = excluded.base_url",
            (
                principal.workspace,
                provider,
                ciphertext,
                wrapped,
                KEY_VERSION,
                hint,
                principal.user_id,
                model,
                base_url,
            ),
        )
    return hint


def check_connection(
    provider: str,
    model: str | None,
    key: str | None,
    base_url: str | None,
    allow_private: bool = False,
) -> None:
    """Send one short message to the model before it is saved, so a wrong
    key, name or address is found now rather than in the middle of a
    backtest (a simulated user's made-up key was accepted as connected,
    2026-10-13). Raises ValueError with the provider's answer."""
    from vp.llm import connect

    p = PROVIDERS.get(provider)
    if p is None:
        raise ValueError(f"unknown provider {provider!r}")
    if p.kind != "openai" or p.base_url is not None:
        base_url = None  # a preset keeps its own address
    try:
        client = connect(
            provider,
            model or "claude-haiku-4-5",
            key,
            base_url,
            allow_private=allow_private,
            max_retries=1,
        )
        client.messages.create(
            model=model or "claude-haiku-4-5",
            max_tokens=16,
            messages=[{"role": "user", "content": "Reply with the word OK."}],
        )
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 - every provider fails in its own way
        raise ValueError(_plain_failure(p.label, model, str(exc))) from None


def _plain_failure(provider: str, model: str | None, error: str) -> str:
    """One sentence a person can act on, from a provider's error (a
    simulated user was shown "Error code: 401 - {'type': 'error', ...}",
    2026-10-13)."""
    low = error.lower()
    if any(w in low for w in ("401", "403", "authentication", "api key", "api-key")):
        return f"{provider} did not accept that key. Check that you copied all of it."
    if any(w in low for w in ("404", "not_found", "not found", "no model")):
        return (
            f"{provider} has no model named {model!r}. Check the name on the "
            "provider's website."
        )
    if any(w in low for w in ("429", "quota", "rate limit", "credit", "billing")):
        return (
            f"{provider} accepted the key but would not answer now: the account "
            "may be out of credit or over its limit."
        )
    if any(w in low for w in ("could not reach", "connect", "timed out", "timeout")):
        return "The model's address could not be reached. Check the address."
    return f"The model did not answer. {provider} said: {error[:160]}"


def connection(pool: ConnectionPool, principal: Principal) -> dict[str, Any] | None:
    """The workspace's own model, without its key: provider, model, address
    and the key's hint; or None."""
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "select provider, model, base_url, hint from provider_keys"
        ).fetchone()
    if row is None:
        return None
    return dict(zip(("provider", "model", "base_url", "hint"), row, strict=True))


def has_own(pool: ConnectionPool, principal: Principal) -> bool:
    return connection(pool, principal) is not None


def delete_connection(pool: ConnectionPool, principal: Principal) -> bool:
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute("delete from provider_keys returning 1").fetchone()
    return row is not None


def own_connection(
    pool: ConnectionPool, principal: Principal, master_key: str | None
) -> dict[str, Any] | None:
    """The workspace's own model with its key in plaintext, for the length
    of a job; or None."""
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "select provider, model, base_url, ciphertext, wrapped_key "
            "from provider_keys"
        ).fetchone()
    if row is None:
        return None
    key = unseal(bytes(row[3]), bytes(row[4]), master_key) or None
    return {"provider": row[0], "model": row[1], "base_url": row[2], "key": key}


# --------------------------------------------------------------- the demo


def country(pool: ConnectionPool, principal: Principal) -> str | None:
    """The country the person said they are in (Settings), or None."""
    if not principal.attributable:
        return None
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "select settings->>'country' from user_settings "
            "where user_id = vp_current_user_id()"
        ).fetchone()
    return row[0] if row and row[0] else None


def demo_check(
    pool: ConnectionPool, principal: Principal, settings: Settings, calls: int = 0
) -> int:
    """Whether the demo can answer this person ``calls`` more times today;
    returns the calls left, or raises DemoUnavailable."""
    if not settings.has_demo:
        raise _unavailable("none")
    if settings.demo_region_rule:
        where = country(pool, principal)
        if where is None:
            raise _unavailable("country_needed")
        if where not in FREE_TIER_COUNTRIES:
            reason = "region_paid_only" if where in PAID_ONLY_COUNTRIES else None
            raise DemoUnavailable(
                "region_blocked", MESSAGES[reason or "region_blocked"]
            )
    with pool.connection() as conn, tenant_session(conn, principal):
        (left,) = conn.execute(
            "select vp_demo_left(%s, %s)",
            (settings.demo_workspace_daily_calls, settings.demo_daily_calls),
        ).fetchone() or (0,)
    if left < max(calls, 1):
        raise _unavailable("used_up")
    return left


def take_demo_call(
    pool: ConnectionPool, principal: Principal, settings: Settings
) -> None:
    """Count one demo call against today's allowances, or raise used_up."""
    with pool.connection() as conn, tenant_session(conn, principal):
        (ok,) = conn.execute(
            "select vp_demo_take(%s, %s)",
            (settings.demo_workspace_daily_calls, settings.demo_daily_calls),
        ).fetchone() or (False,)
    if not ok:
        raise _unavailable("used_up")


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
    """`client.messages` with every `create` holding a slot, after ``before``
    (the demo's allowance) agrees; batches pass through (the provider queues
    them, so they do not occupy a connection here)."""

    def __init__(
        self, messages: Any, slots: Slots, before: Callable[[], None] | None = None
    ) -> None:
        self._messages = messages
        self._slots = slots
        self._before = before
        self.batches = getattr(messages, "batches", None)

    def create(self, **kwargs: Any) -> Any:
        if self._before is not None:
            self._before()
        with self._slots.hold():
            return self._messages.create(**kwargs)


class LimitedBeta:
    """`client.beta`, for the compiler's refusal fallback, under the same slots."""

    def __init__(
        self, beta: Any, slots: Slots, before: Callable[[], None] | None = None
    ) -> None:
        self.messages = LimitedMessages(beta.messages, slots, before)


class LimitedClient:
    """A client under the slots; the wrapped client's model choice and
    price (free or not) hold."""

    def __init__(
        self, client: Any, slots: Slots, before: Callable[[], None] | None = None
    ) -> None:
        self.messages = LimitedMessages(client.messages, slots, before)
        self.beta = LimitedBeta(client.beta, slots, before)
        self.free = getattr(client, "free", False)
        self._client = client

    def model_for(self, requested: str) -> str:
        inner = getattr(self._client, "model_for", None)
        return inner(requested) if callable(inner) else requested


def client_for(
    pool: ConnectionPool, principal: Principal, settings: Settings, slots: int = 4
) -> tuple[Any, str]:
    """A limited client for this workspace, and who pays: 'own_key' (the
    workspace's own model) or 'platform' (the demo).

    Raises:
        DemoUnavailable: no own model, and the demo cannot answer this
            person (no demo, their country, today's allowance).
    """
    from vp.llm import connect

    mine = (
        own_connection(pool, principal, settings.master_key)
        if settings.master_key
        else None
    )
    if mine:
        client = connect(
            mine["provider"],
            mine["model"],
            mine["key"],
            mine["base_url"],
            allow_private=settings.allow_private_model_urls,
            max_retries=MAX_RETRIES,
        )
        slot = Slots(pool, f"own:{principal.workspace}", slots)
        return LimitedClient(client, slot), "own_key"
    demo_check(pool, principal, settings)
    client = connect(
        settings.demo_provider,
        settings.demo_model,
        settings.demo_api_key,
        settings.demo_base_url,
        allow_private=settings.allow_private_model_urls,
        free=settings.demo_free,
        max_retries=MAX_RETRIES,
    )
    return (
        LimitedClient(
            client,
            Slots(pool, "demo:platform", slots),
            lambda: take_demo_call(pool, principal, settings),
        ),
        "platform",
    )
