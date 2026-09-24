"""The outbox's delivery job (plan, tasks 85 to 87 and 89;
docs/collaboration.md).

`deliver` runs every minute as a platform job. It claims due messages
through `vp_outbox_claim` (a five-minute lease, so a worker that dies
leaves nothing lost), sends each through its channel's adapter, and
records the outcome through `vp_outbox_finish`: sent with the provider's
receipt, queued again after 1, 5, 30 and 120 minutes, or dead after the
fifth attempt, which tells the workspace's owners.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from vp.platform.channels import Adapter, Target, adapters
from vp.platform.llmops import unseal
from vp.platform.mail import OutboxMailer

logger = logging.getLogger(__name__)

BACKOFF = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(minutes=120),
)
BATCH = 100


def target_of(row: dict[str, Any], master_key: str | None) -> Target:
    """Where a claimed message goes: an address, a channel or a webhook."""
    secret = (
        unseal(bytes(row["ciphertext"]), bytes(row["wrapped_key"]), master_key)
        if row["ciphertext"]
        else None
    )
    if row["address"]:
        return Target("email", row["address"])
    if row["url"]:
        return Target("webhook", row["url"], secret)
    return Target(row["channel_kind"], row["target"], secret)


def deliver(
    ctx: Any,
    send_with: dict[str, Adapter] | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    """Send what is due; returns counts of sent, retried and dead messages."""
    svc = ctx.services
    table = send_with or adapters(
        getattr(svc, "mailer", None) or OutboxMailer(svc.settings.outbox_dir)
    )
    counts = {"sent": 0, "retried": 0, "dead": 0}
    with ctx.pool.connection() as conn:
        cur = conn.execute("select * from vp_outbox_claim(%s)", (BATCH,))
        names = [d.name for d in cur.description or []]
        claimed = [dict(zip(names, r, strict=True)) for r in cur.fetchall()]
    for row in claimed:
        payload = row["payload"] or {}
        try:
            target = target_of(row, svc.settings.master_key)
            receipt = table[target.kind].send(
                target,
                str(payload.get("text", "")),
                {k: v for k, v in payload.items() if k != "text"},
            )
            outcome: tuple[str, Any, str | None, datetime | None] = (
                "sent",
                receipt,
                None,
                None,
            )
            counts["sent"] += 1
        except Exception as exc:  # noqa: BLE001 - every failure is recorded
            error = f"{type(exc).__name__}: {exc}"[:500]
            attempts = row["attempts"]
            if attempts <= len(BACKOFF):
                outcome = (
                    "queued",
                    None,
                    error,
                    (now or datetime.now(tz=UTC)) + BACKOFF[attempts - 1],
                )
                counts["retried"] += 1
            else:
                outcome = ("dead", None, error, None)
                counts["dead"] += 1
            logger.warning(
                "delivery %s failed (attempt %s): %s", row["id"], attempts, error
            )
        state, receipt, error, retry_at = outcome
        with ctx.pool.connection() as conn:
            conn.execute(
                "select vp_outbox_finish(%s, %s, %s, %s, %s)",
                (
                    row["id"],
                    state,
                    Jsonb(receipt) if receipt else None,
                    error,
                    retry_at,
                ),
            )
            if state == "dead":
                conn.execute(
                    "select vp_notify_owners(%s, 'delivery', %s, %s)",
                    (
                        row["workspace_id"],
                        "A message could not be delivered",
                        f"After {row['attempts']} attempts: {error}. "
                        "Check the channel on the Delivery page, which counts "
                        "every failure; you are told at most once an hour.",
                    ),
                )
    return counts
