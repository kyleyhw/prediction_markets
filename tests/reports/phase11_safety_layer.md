# Phase 11 Test Report: Live Safety Layer

Date: 2026-09-13. Environment: Python 3.14.7 via `uv 0.12.13`, Linux
container. Runtime of the checks below: about 8 s wall.

## Purpose and Scope

Phase 11 is gated: no order-signing or placement code until the security
design in `docs/security.md` is agreed with the user. What this phase adds
is the safety layer that design specifies and that any agreed variant
will need, built so the design can be reviewed with code and tests in
hand. Nothing in `vp/live/` can sign or send an order; it has no venue
write path and no dependency on a signing library.

## Static Checks

| Check | Result |
| :--- | :--- |
| `ruff check .` and `ruff format --check .` | passed |
| `ty check` (`error-on-warning`) | passed, 0 diagnostics |
| `pre-commit run --all-files` | all hooks passed |

## Unit Tests

`uv run pytest -q`: 68 passed. New file `tests/test_live_guard.py`:

**What.** Every refusal path of the mandate guard; that it fails closed on
a missing, malformed, wrong-version or non-positive mandate and on a
broken ledger chain; the kill switch; that a ledger labelled paper is
refused as live and an unlabelled one is refused outright; the
proposal-and-approval protocol (no approval, an unnamed approver, an
expired approval, an approval consumed by the order that used it); and
credential access by environment through an injected backend, with the
real keyring raising rather than returning nothing.

**Why.** The guard is the part of live execution that must be right before
the part that moves money exists. A refusal path that does not refuse is
the failure that costs the bankroll.

**Test data.** A mandate with caps of 10 per order, 15 per market, 25
total, 3 orders per day and a daily loss of 8. Two orders of 8 on one
market make a third of 8 exceed the market cap while 5 on another market
is allowed; that brings total exposure to 21, so 5 more is refused; the
third order of the day is refused by the count; a settlement at a loss of
9 frees the market's exposure but halts trading; two days later both
windows have cleared and an order is allowed again. Because ledger
entries are stamped by the real clock, the test clock is the real one
plus a minute.

## Not Done, By Design

Task 23 (the CLOB execution adapter) and task 24 (the canary) are not
written. They wait on agreement of the design; the caps, approval expiry
and file format in the safety layer are parameters and can change with
that agreement.
