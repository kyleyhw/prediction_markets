# Venues: the Polymarket US Assessment (Phase 22, task 118)

**Status: a proposed decision, 2026-09-24, waiting for the owner's
agreement.** The plan asks for a decision, not code. Polymarket is the only
venue. Kalshi is deferred (`PROJECT_PLAN.md`, "Deferred").

## What Polymarket US Is

It is a separate venue from the international Polymarket the platform
reads today, not a region of it.

- **Regulation:** a designated contract market and clearing organisation
  under the United States Commodity Futures Trading Commission (CFTC)
  ([regulatory information](https://www.polymarketexchange.com/regulatory.html)).
- **Its own API:** a different base URL and a different authentication
  (Ed25519 API keys, not the international venue's wallet signatures and
  L2 credentials).
- **API access by application:** "API access requires an application
  process and integration testing to ensure compliance and security"
  ([developers](https://www.polymarketexchange.com/developers.html)).
- **Traders:** individuals who have passed the venue's identity checks.
- **Fees:** a taker fee of $\Theta \cdot C \cdot p(1-p)$ with $\Theta = 0.0695$,
  and a maker *rebate* with $\Theta = -0.0125$, from 17 September 2026. There
  are volume rebates, and per-sport coefficients are changing
  ([fee schedule](https://docs.polymarket.us/fees)).

## What It Would Take

| Surface | International venue today | Polymarket US |
| :--- | :--- | :--- |
| Market data for datasets, snapshots, paper | public, unauthenticated | access and redistribution terms to be read; the developer page describes an application for API access |
| Fee model | $C \cdot r \cdot p(1-p)$ per market | the same shape, so the one fee function serves if a maker rebate (a negative rate for resting orders) is added |
| Resolution evidence | the venue's `winner` flag and oracle status | the exchange's own settlement, to be mapped to "closed is not resolved" |
| Live execution | a person's session key under a signed mandate (`docs/security.md`) | **no documented delegation**: each trader's own API key after identity checks. A platform placing orders for people on a CFTC-regulated exchange raises the question of acting as an intermediary (an introducing broker or similar), which is registration territory. |

## The Proposed Decision

1. **No live execution on Polymarket US.** The platform does not trade for
   people there. There is no delegated-key mechanism to build on, and doing
   it would likely need registration as an intermediary. That is a legal
   and business decision far beyond this project's scope, and "the API
   allows it" would not settle it (principle 6 of `docs/security.md`).
2. **No data from it now.** The platform's domains are covered by the
   international venue's public data. Adding a second venue's markets
   doubles the dataset, fee, resolution and snapshot paths (`vp/venues/`
   is written for one).
3. **Revisit** when both are true: people in the United States ask for it,
   and the exchange publishes terms that allow a third party to show its
   market data. The first step would then be read-only data and paper
   trading, as a second implementation of the venue interface: records,
   fees with the maker rebate, resolution. It would still not be live
   execution.
4. **United States residents stay unable to trade live on this platform**
   (F13). Paper trading is not money and remains open to them.
