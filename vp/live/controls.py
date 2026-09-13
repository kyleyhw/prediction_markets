"""Kill switch, environment separation, approvals and credential access.

* **Kill switch.** A file outside the repository (``~/.vibe-predict/STOP``
  by default). Its presence stops everything; it is created and removed by
  a human or a monitoring job, never by this code.
* **Environment.** ``paper`` and ``live`` are different ledgers whose first
  entry names the environment, and different keyring entries. A live
  process refuses a ledger that does not say live, so the two cannot cross
  by a flag or a path mistake.
* **Approval.** Every write is first a ``proposal`` entry; execution needs
  an ``approval`` entry whose ``proposal`` field is that entry's hash and
  whose approver is a person. Approvals expire.
* **Credentials.** Read from the operating-system keyring under
  ``vibe-predict/<environment>`` through an injectable backend; the value
  is returned to the caller and never logged, stored or echoed.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from vp.forecast.evidence import parse_time
from vp.paper.ledger import Ledger

STOP_FILE = Path(
    os.environ.get("VP_STOP_FILE", str(Path.home() / ".vibe-predict" / "STOP"))
)
KEYRING_SERVICE = "vibe-predict"
APPROVAL_TTL = timedelta(minutes=15)


class Environment(str, Enum):
    PAPER = "paper"
    LIVE = "live"


def stopped(path: Path = STOP_FILE) -> bool:
    """Whether the kill switch is set."""
    return path.exists()


def ensure_environment(ledger: Ledger, environment: Environment) -> None:
    """Make the ledger's first entry name the environment, or refuse a mismatch.

    Raises:
        RuntimeError: The ledger belongs to another environment.
    """
    first = next(iter(ledger.entries()), None)
    if first is None:
        ledger.append("genesis", {"environment": environment.value})
        return
    found = first.get("kind") == "genesis" and first["data"].get("environment")
    if found != environment.value:
        label = found or "unlabelled"
        raise RuntimeError(
            f"ledger is {label!r}, refusing to use it as {environment.value}"
        )


def propose(ledger: Ledger, order: dict[str, Any]) -> str:
    """Record a proposed write; returns the proposal's hash to be approved."""
    return ledger.append("proposal", order)["hash"]


def approve(ledger: Ledger, proposal_hash: str, approver: str) -> None:
    """Record a person's approval of a proposal."""
    if not approver.strip():
        raise ValueError("approver must be named")
    ledger.append("approval", {"proposal": proposal_hash, "approver": approver})


def approved(
    ledger: Ledger, proposal_hash: str, *, now: datetime | None = None
) -> bool:
    """Whether an unexpired approval for the proposal exists and nothing has used it."""
    now = now or datetime.now(tz=timezone.utc)
    seen_proposal = valid = False
    for entry in ledger.entries():
        kind, data = entry["kind"], entry["data"]
        if kind == "proposal" and entry["hash"] == proposal_hash:
            seen_proposal = True
        elif kind == "approval" and data.get("proposal") == proposal_hash:
            at = parse_time(entry.get("at"))
            if seen_proposal and at is not None and now - at <= APPROVAL_TTL:
                valid = True
        elif kind == "order" and data.get("proposal") == proposal_hash:
            return False
    return valid


def load_credential(
    environment: Environment,
    *,
    backend: Callable[[str, str], str | None] | None = None,
) -> str:
    """Fetch the environment's credential from the keyring.

    Args:
        environment: Which entry to read; a live process must pass ``LIVE``.
        backend: ``(service, username) -> secret``; defaults to the
            ``keyring`` library, imported lazily so paper trading needs no
            keyring at all.

    Raises:
        RuntimeError: No credential is stored, or no keyring is available.
    """
    if backend is None:
        try:
            import keyring
        except ImportError as exc:
            raise RuntimeError("keyring library not installed") from exc
        backend = keyring.get_password
    secret = backend(KEYRING_SERVICE, environment.value)
    if not secret:
        raise RuntimeError(
            f"no credential stored for {KEYRING_SERVICE}/{environment.value}"
        )
    return secret
