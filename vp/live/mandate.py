"""The mandate: hard caps a live process cannot exceed, enforced fail-closed.

A mandate is a versioned JSON file the operator writes and the guard reads
at start and before every order. Every cap in it is a ceiling; the guard
refuses an order that would cross any of them, refuses when a cap cannot
be evaluated (a missing price, a ledger that will not replay, an
unparsable file), and refuses everything after ``expires_at``. Refusal is
the default: the only path to "allowed" runs through every check.

Exposure and daily counts come from replaying the ledger, so the guard's
view of open positions is the same record the audit reads.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from vp.forecast.evidence import parse_time
from vp.paper.ledger import Ledger

MANDATE_VERSION = 1
_REQUIRED = (
    "max_order_notional",
    "max_market_exposure",
    "max_total_exposure",
    "max_orders_per_day",
    "max_daily_loss",
    "allowed_domains",
    "expires_at",
)


@dataclass(frozen=True)
class Mandate:
    version: int
    max_order_notional: float
    max_market_exposure: float
    max_total_exposure: float
    max_orders_per_day: int
    max_daily_loss: float
    allowed_domains: tuple[str, ...]
    expires_at: datetime

    @classmethod
    def load(cls, path: Path) -> Mandate:
        """Parse the file; any defect raises, which the guard treats as refusal."""
        raw = json.loads(path.read_text())
        missing = [k for k in _REQUIRED if k not in raw]
        if missing:
            raise ValueError(f"mandate missing {missing}")
        if raw.get("version") != MANDATE_VERSION:
            raise ValueError(
                f"mandate version {raw.get('version')!r} != {MANDATE_VERSION}"
            )
        expires = parse_time(str(raw["expires_at"]))
        if expires is None:
            raise ValueError("mandate expires_at is not a timestamp")
        caps = {k: float(raw[k]) for k in _REQUIRED[:3] + ("max_daily_loss",)}
        if any(v <= 0 for v in caps.values()) or int(raw["max_orders_per_day"]) <= 0:
            raise ValueError("mandate caps must be positive")
        return cls(
            version=MANDATE_VERSION,
            max_order_notional=caps["max_order_notional"],
            max_market_exposure=caps["max_market_exposure"],
            max_total_exposure=caps["max_total_exposure"],
            max_orders_per_day=int(raw["max_orders_per_day"]),
            max_daily_loss=caps["max_daily_loss"],
            allowed_domains=tuple(str(d) for d in raw["allowed_domains"]),
            expires_at=expires,
        )


@dataclass(frozen=True)
class OrderRequest:
    """What the guard is asked about: a stake on one market in one domain."""

    domain: str
    market_id: str
    side: str
    price: float
    stake: float


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class LedgerState:
    """Open exposure, recent order count and recent realised loss from the ledger."""

    open_by_market: dict[str, float]
    orders_last_day: int
    loss_last_day: float

    @property
    def total_exposure(self) -> float:
        return sum(self.open_by_market.values())


def replay_state(ledger: Ledger, now: datetime) -> LedgerState:
    """Replay ``order`` and ``settlement`` entries into the guard's state."""
    open_by_market: dict[str, float] = {}
    orders = 0
    loss = 0.0
    since = now - timedelta(days=1)
    for entry in ledger.entries():
        at = parse_time(entry.get("at"))
        if at is None:
            raise ValueError(f"ledger entry {entry.get('seq')} has no valid time")
        data = entry["data"]
        if entry["kind"] == "order":
            open_by_market[data["market_id"]] = open_by_market.get(
                data["market_id"], 0.0
            ) + float(data["stake"])
            if at >= since:
                orders += 1
        elif entry["kind"] == "settlement":
            open_by_market.pop(data["market_id"], None)
            if at >= since and float(data["pnl"]) < 0:
                loss += -float(data["pnl"])
    return LedgerState(open_by_market, orders, loss)


class Guard:
    """Fail-closed check of an order against the mandate, the ledger and the clock."""

    def __init__(self, mandate_path: Path, ledger: Ledger) -> None:
        self.mandate_path = mandate_path
        self.ledger = ledger

    def check(self, order: OrderRequest, *, now: datetime | None = None) -> Decision:
        now = now or datetime.now(tz=timezone.utc)
        try:
            mandate = Mandate.load(self.mandate_path)
        except Exception as exc:  # noqa: BLE001 - any defect is a refusal
            return Decision(False, f"mandate unreadable: {exc}")
        if self.ledger.verify() is not None:
            return Decision(False, "ledger chain broken")
        try:
            state = replay_state(self.ledger, now)
        except Exception as exc:  # noqa: BLE001
            return Decision(False, f"ledger unreadable: {exc}")
        if now >= mandate.expires_at:
            return Decision(
                False, f"mandate expired at {mandate.expires_at.isoformat()}"
            )
        if order.domain not in mandate.allowed_domains:
            return Decision(False, f"domain {order.domain!r} not in mandate")
        if not (0.0 < order.price < 1.0) or order.stake <= 0.0:
            return Decision(False, "order price or stake not evaluable")
        if order.stake > mandate.max_order_notional:
            return Decision(False, "stake exceeds max_order_notional")
        market_after = state.open_by_market.get(order.market_id, 0.0) + order.stake
        if market_after > mandate.max_market_exposure:
            return Decision(False, "market exposure would exceed max_market_exposure")
        if state.total_exposure + order.stake > mandate.max_total_exposure:
            return Decision(False, "total exposure would exceed max_total_exposure")
        if state.loss_last_day >= mandate.max_daily_loss:
            return Decision(False, "max_daily_loss reached; trading halted")
        if state.orders_last_day + 1 > mandate.max_orders_per_day:
            return Decision(False, "max_orders_per_day reached")
        return Decision(True, "within mandate")
