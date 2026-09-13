"""Fee, edge and Kelly arithmetic on hand-checkable prices."""

from __future__ import annotations

import pytest

from vp.backtest.sizing import FeeModel, kelly_fraction, size


def test_fee_is_symmetric_and_zero_at_extremes() -> None:
    fees = FeeModel(rate=0.02)
    assert fees.per_share(0.5) == pytest.approx(0.005)
    assert fees.per_share(0.3) == pytest.approx(fees.per_share(0.7))
    assert fees.per_share(0.0) == 0.0 and fees.per_share(1.0) == 0.0
    assert FeeModel().per_share(0.5) == 0.0


def test_kelly_fraction() -> None:
    # Belief 0.6 at price 0.5: odds 1:1, f* = 0.6 - 0.4 = 0.2.
    assert kelly_fraction(0.6, 0.5) == pytest.approx(0.2)
    assert kelly_fraction(0.5, 0.5) == 0.0
    assert kelly_fraction(0.4, 0.5) == 0.0  # no negative stakes
    assert kelly_fraction(0.9, 1.0) == 0.0 and kelly_fraction(0.9, 0.0) == 0.0


def test_size_picks_the_side_with_edge() -> None:
    # Market 0.50/0.52, belief 0.6: buy yes at 0.52, f* = (0.6-0.52)/0.48.
    pos = size(0.6, ask=0.52, bid=0.50)
    assert pos is not None and pos.side == "yes" and pos.price == 0.52
    assert pos.fraction == pytest.approx(0.25 * (0.6 - 0.52) / 0.48)
    assert pos.edge == pytest.approx((0.6 - 0.52) / 0.52)
    # Belief 0.3: buy no at 1 - bid = 0.50 with p = 0.7.
    pos = size(0.3, ask=0.52, bid=0.50, max_fraction=1.0)
    assert pos is not None and pos.side == "no" and pos.price == 0.50
    assert pos.fraction == pytest.approx(0.25 * (0.7 - 0.5) / 0.5)
    # Belief inside the spread: no edge either way.
    assert size(0.51, ask=0.52, bid=0.50) is None
    # The cap binds on a large edge; a fee can remove a thin one.
    capped = size(0.99, ask=0.10, bid=0.09)
    assert capped is not None and capped.fraction == 0.05
    assert size(0.53, ask=0.52, bid=0.50, fees=FeeModel(rate=0.1)) is None
    # A minimum edge filters a thin one.
    assert size(0.55, ask=0.52, bid=0.50, min_edge=0.05) is None
    assert size(0.58, ask=0.52, bid=0.50, min_edge=0.05) is not None
