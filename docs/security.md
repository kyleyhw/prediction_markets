# Live Execution: Security Design, Version 2 (Phase 22, task 112)

**Status: proposed on 2026-09-24, waiting for the owner's agreement.**
Until it is agreed, no code signs or sends an order (`CLAUDE.md`,
invariants). Agreeing may mean changing any recommendation in section 16.
Each is a parameter of the design, not a consequence of it.

Version 1 (2026-09-13, Phase 11) designed live execution from an
operator's own machine, with the wallet key in the operating system's
keyring. On 2026-09-19 the owner decided that live execution is hosted
only, so a strategy trades while its owner's computer is closed, and that
it is built last. Version 2 therefore changes four things:

- the key model, which replaces the keyring (section 3);
- where signing runs (section 4);
- consent and approvals, which move to the browser and the chat channels
  (sections 6 and 9);
- jurisdiction, now part of the design (section 11).

It keeps version 1's principles and its safety layer in `vp/live/`: the
mandate guard, the kill switch, environment separation, and proposal and
approval. The layer is tested and cannot sign.

Live execution means orders on Polymarket's order book paid for with a
person's own money. Everything here exists to bound what a bug, a
compromised dependency, a bad forecast, a manipulated model, an insider or
a stolen session can lose, and to make every action attributable
afterwards. The principles:

1. **The platform never holds a key that can move money.** It holds only a
   trading key the person authorised, can see on the venue, and can revoke
   without us.
2. **Paper and live are different credentials in different processes,**
   not a flag.
3. **Every order passes a fail-closed gate against a mandate the person
   signed.** The model can propose a mandate; it can never write one.
4. **Three halts, each independent of the others,** and one of them
   independent of us.
5. **Every decision is in the hash-chained ledger before it is acted on.**
6. **Lawful, not merely unblocked.** Live execution is offered only where
   using the venue is lawful for the person and for the host. Whether the
   venue's API happens to answer from a place does not decide it.

## 1. What the Venue Provides (read 2026-09-24)

The design rests on these facts, from the venue's documentation. Each is
checked again when the execution adapter is built (task 113), because the
features are new in 2026 and have changed during their rollout.

| Fact | Source |
| :--- | :--- |
| Wallets deployed on or after 4 May 2026 are **Deposit Wallets**. Proxy and Safe wallets are legacy types. | [Wallets and authentication](https://docs.polymarket.com/trading/wallets-auth) |
| A Deposit Wallet's owner can authorise a **Session Key**: a separate key (an externally owned account) with "scoped, time-limited trading access". It can place orders and fetch its own orders and trades. It "cannot withdraw funds" and cannot make approvals or modify the account. Its scope can be the order book, combos, or all. | [Session keys](https://docs.polymarket.com/trading/session-keys) |
| The authorisation is typed data (EIP-712) signed by the **owner**. It lasts **180 days**, with no shorter choice at present. The owner revokes it with `revokeSessionKey()`, which also cancels the key's open orders. | same |
| **Authorising a session key requires a Builder API key.** During the rollout, the venue enables it on request (builder@polymarket.com). | same |
| No per-key cap on notional or markets is documented. | same |
| Trading needs four approvals (pUSD and the conditional-token operator, on the standard and the negative-risk exchanges). A session key cannot make them. The relayer submits them gaslessly for smart wallets. | [Wallets and authentication](https://docs.polymarket.com/trading/wallets-auth) |
| Private requests use **L2 credentials** (key, secret, passphrase) derived after an L1 signature over `ClobAuth`. | same |
| Orders are GTC or GTD limit orders (FOK and FAK also exist). There is `/cancel-all`, and cancellation by order, token or market. Orders carry `feeRateBps` and a `builder` field for attribution. | [Orders](https://docs.polymarket.com/trading/orders/overview) |
| **Heartbeats:** "if a valid heartbeat is not received within 10 seconds, all open orders owned by those CLOB API credentials are canceled." | same |
| The builder programme attributes matched volume to a builder code and gives gasless wallet deployment, approvals and execution through the relayer. | [Builders](https://docs.polymarket.com/programs/builders/overview) |
| **Geographic restrictions:** OFAC countries are blocked outright. Some are close-only on both the front end and the API, among them the United States, the United Kingdom, France, Germany, Italy, Belgium, Poland, Australia, Singapore and four Canadian provinces. Ireland, Japan, Malta (sports), **the Netherlands** and South Korea are close-only "on the Polymarket frontend; the API itself is not restricted". `GET https://polymarket.com/api/geoblock` reports on a caller's address. | [Geographic restrictions](https://docs.polymarket.com/api-reference/geoblock) |

## 2. What Is at Stake, and What a Session Key Does Not Protect

A session key cannot move money out of the wallet. A breach of the
platform therefore cannot steal funds; it can only trade them. The venue
does not cap how much a session key may trade, so trading can lose the
whole balance (flag F12):

- a bug that keeps buying;
- a compromised execution host;
- a strategy that is simply wrong.

The mandate (section 6) is the only limit that is ours. That is why the
design also:

- asks the person to hold in the trading wallet only what they are
  willing to lose, and says so at every step (section 10);
- starts every person at a canary mandate (section 15);
- keeps a halt the person controls without us: revoking the key on the
  venue.

## 3. The Key Model

The options (plan, task 112):

| Option | What it is | Runs a scheduled strategy? | What the platform holds |
| :--- | :--- | :--- | :--- |
| **A. Session keys** | A trading-only key the person authorises on the venue, held by the platform encrypted | yes | a key that can trade, not withdraw |
| **B. Browser signing** | The person's own wallet signs each order in the browser | no: someone must be at the screen | nothing |
| **C. A local signer** | A program the person runs polls for approved proposals and signs them | only while their machine is on | nothing |

**Recommended: A for execution, B for consent.**

- **A** is the only option that meets the owner's reason for hosting:
  trading while the person's computer is closed.
- **B** is used for what must not rest on a stolen session cookie: signing
  the mandate (section 6), widening it, and approving orders above the
  mandate's wallet threshold (section 9).
- **C** is dropped. It gives up the reason for hosting and asks for the
  terminal that users do not have (`docs/product.md`).

How a session key is made and held:

1. **The execution service generates the key** (an Ethereum key pair)
   inside itself. The private key never leaves that service unencrypted;
   outside it, it exists only as ciphertext in the database. The browser
   sees only its address.
2. **The person authorises it with their own wallet in the browser.**
   They sign the venue's EIP-712 authorisation for that address,
   scoped to the order book and not to combos. The execution service
   submits it through the platform's builder account (section 12). The
   page shows the address, the scope and the 180-day expiry before the
   wallet is asked to sign.
3. **Storage:** envelope encryption. A fresh data key encrypts the
   private key, and the key-management service wraps the data key. The
   stand-in's `VP_MASTER_KEY` is today's stand-in for that service, and a
   managed one replaces it at the deploy. **Only the execution service's
   identity may unwrap.** The web service, the other workers, the operator
   commands and the database owner hold ciphertext they cannot open.
4. **In use:** unwrapped in memory for a signing, then dropped. It is
   never logged, never in a ledger entry, never in an error, never in a
   job payload. Only its address appears anywhere.
5. **Expiry** is tracked from the authorisation. The person is told at 30,
   7 and 1 days, and at expiry the strategy stops with a notice, never
   silently.
6. **Wallet type:** only Deposit Wallets can have session keys. A person
   with a legacy wallet is told they need a new account on the venue;
   nothing else is attempted.

## 4. Where Signing Runs

A separate **execution service**, not one of the existing worker pools:

- It runs from the same image with its own entry point, as its own
  database role (`vp_exec`), on a host of its own, in a region chosen by
  section 11.
- It holds the only permission to unwrap session keys, the builder API
  key and the L2 credentials.
- It runs no model, reads no evidence, fetches nothing a strategy names,
  and imports nothing from `vp/forecast`, `vp/strategy` or the research
  assistant. A boundary test will enforce this, as one keeps
  `vp/platform` out of the engine today.
- It takes **orders as data**: a proposal row written by the paper-shaped
  decision path. It re-checks every one against the mandate itself
  (section 7). It never trusts the proposal's own arithmetic.
- It sends the venue a heartbeat every few seconds while it has orders
  open. If it hangs or dies, the venue cancels its open orders within
  10 seconds. This is the dead man's switch for the wedged worker.

## 5. Threat Model

| Threat | What it could do | Controls |
| :--- | :--- | :--- |
| Compromise of the web service or an ordinary worker | Write proposals; read ciphertext | It cannot unwrap keys. The execution service re-checks every proposal against the signed mandate. It cannot write a mandate without the person's wallet signature (section 6). |
| Compromise of the execution service | Trade within the venue's rules until noticed | Keys are unwrapped per signing, so it holds little in memory. A mandate check in the service is only as good as the service, so the venue-side controls matter: each person can revoke on the venue at any time; alerts on orders that reconcile to no proposal; the external review (task 117). Stated plainly: this is the residual risk (F12). |
| An insider or the operator | Change rows, trade | The operator's credentials cannot unwrap keys. Mandates are signed by the person, and changing a row breaks the signature check. Every operator action is in the audit chain. A second operator is due before live execution (F2). |
| Prompt injection through evidence or a shared strategy | Talk the model into a bigger bet or a new mandate | The model's output is a forecast and at most a proposal. Mandates are written by one function reachable only from the web with a wallet signature. The gate's caps are numbers the model never sees as instructions. |
| A compromised dependency | Code in any process | Pinned and hashed dependencies (the `uv` lock). The execution service has the smallest dependency set, and its image is built separately and reviewed. Egress from it only to the venue's hosts. |
| Key exfiltration | Trading from elsewhere | Keys cannot withdraw. Ciphertext is useless without the key service. A leaked key is revoked by the person or, on detection, by the operator asking the person (we cannot revoke it ourselves); orders that reconcile to no proposal raise an alert. |
| A wedged or crashed worker | Orders left resting, or an order sent twice | The venue cancels on a missed heartbeat. A pending-action marker is written before each send. Reconciliation against the venue on restart (section 7). |
| Venue outage or API change | Unknown order state | Fail closed: no new orders while positions, balance or order state cannot be read. Reconcile when it returns. The adapter checks response shapes and refuses unknown ones. |
| A stolen browser session (magic-link account takeover) | Widen the mandate; approve orders | Mandate changes and large approvals need the person's wallet signature, which a session cookie cannot give. Small approvals are bounded by the mandate. |
| Replay of an approval or a mandate | A second order on one approval | Approvals are single-use, expire (15 minutes) and name the proposal's hash (as `vp/live/controls.py` does). Mandates carry a version and a nonce, and only the latest signed version counts. |
| Database tampering | Change a mandate or a ledger | Mandates are checked against the person's signature before every order. Ledgers are hash-chained and verified daily from the first entry (Phase 21), with a daily copy to write-once storage. |

## 6. The Mandate, Version 2

A mandate is what a person allows one promoted strategy version to do
with one wallet. It extends version 1 (`vp/live/mandate.py`) with:

- **Caps:** per order, per market, **per event** (F6, Phase 20), in total,
  orders a day, and loss in 24 hours. All are in dollars of pUSD. A missing
  or non-positive cap is a refusal.
- **Universe:** domains, market kinds (the strategy spec's), a liquidity
  floor (resting size at our price), a minimum time before the event,
  and a maximum spread.
- **Bindings:** the strategy version and the promotion approval that
  allowed it (Phase 20), the wallet address, and the session key's
  address.
- **Consent provenance:**
  - the person's EIP-712 signature over the mandate's canonical hash,
    made with the wallet's owner key in the browser;
  - the time;
  - the jurisdiction the person declared then (section 11).
- **Expiry:** no later than the session key's.
- **Wallet threshold:** the order size above which approval needs a wallet
  signature (section 9).

Who writes it: **one function, reachable only from one web route.** The
route needs a browser session, the consent token that the page's own
signing flow produces, and a valid signature from the wallet's owner. No
API token, MCP tool, channel command, job or model reaches it. The
research assistant and the preview may produce a **draft**, shown as "a
proposal is not a mandate". A draft does nothing until a person signs it.

Widening a mandate means a new version, signed again. Narrowing one
(lower caps, fewer domains) takes effect at once from a session, because
narrowing cannot hurt the person.

## 7. The Order Gate

The execution service runs these checks for every order, in this fixed
order. It fails closed, and the first failure stops the order.

1. **Halts:** platform, workspace, the person's own. Any one set means
   deny.
2. **Mandate:** present, the latest version, its signature verifies
   against the wallet owner, not expired.
3. **Session key:** authorised and not expired, per our record and the
   venue's.
4. **Account binding:** the proposal's workspace, strategy version, wallet
   and key are the mandate's.
5. **Jurisdiction:** the person's status is current (section 11).
6. **Intent parse:** the proposal is well formed. It names a market in
   the universe, a side, and a limit price on the market's tick. The size
   is at or above the venue's minimum. The fee comes from the market's
   `feeSchedule` now.
7. **Venue state, read now:** open orders, positions and pUSD balance
   from the venue, not from our ledger. The two must reconcile. If they
   cannot be read, deny.
8. **Caps:** order, market, event, total, count, and daily loss, computed
   from the venue's state plus this order.

A **structural breach** denies the order and is logged: a wrong binding,
a market outside the universe, a bad signature. A **quantitative breach**
of a cap pauses the strategy and asks the person to re-authorise: the
strategy wanted more than was allowed, which is theirs to decide.

Orders are **limit orders at our price, never market orders.** The
default is GTD, expiring at the strategy's horizon. FAK at our limit is
allowed where the strategy takes liquidity. Post-only is used where the
venue supports it, which is checked at build time. Every order carries
the builder code.

**Crash safety.** Before sending, the service writes a pending-action
marker to the ledger: the proposal, the order's hash and a client
identifier. After the venue answers, it writes the result. On start it
reads every marker without a result and asks the venue what happened:
open orders and trades by identifier. It records the answer and then
resumes. An order is never re-sent because we cannot tell whether the
first one landed.

## 8. The Three Halts

| Halt | Who | What happens |
| :--- | :--- | :--- |
| The person's | the person: **revoke the session key on the venue** (independent of us), or the halt button on the page | revocation cancels the key's orders at the venue; the button makes the service cancel all and stop |
| The workspace's | the operator (`vp admin pause`) | cancel all for that workspace's keys, stop |
| The platform's | the operator (`vp admin halt`) | cancel all for every key, stop; no job, model call or order runs |

Each halt is a ledger entry. **Positions are not flattened** on a halt
unless the mandate says `flatten_on_halt`. Selling into a thin book to
stop is itself a loss, so it is the person's choice, off by default. A
missed heartbeat is a fourth, automatic stop: the venue cancels.

## 9. Approvals

- **Within the mandate and below its approval threshold:** no approval.
  The strategy trades.
- **Above the approval threshold:** an approval request goes to the
  person's channel (Phase 18) or the page. It names the proposal's hash,
  the market, the side, the price and the size. It expires after 15
  minutes and is single-use. It is attributable to the person: a paired
  and approved channel sender, or a browser session.
- **Above the wallet threshold:** the approval is a wallet signature in
  the browser. A chat reply is not enough.

## 10. Paper and Live Cannot Cross

This carries over from version 1, adapted:

- Live ledgers are separate accounts whose genesis entry says `live`. A
  live path refuses a paper ledger and a paper path refuses a live one.
- Nothing outside `vp/live` imports it, so no paper, backtest or
  platform path can reach it (`tests/test_platform_boundary.py`). The
  execution service will be the one named exception.
- Only the execution service's role can read live credentials.
- The page shows paper and live in different colours and words. Every
  live screen repeats the canary's limits and "hold in this wallet only
  what you are willing to lose".

## 11. Jurisdiction

- **The person:** declares their country (and region where the venue
  distinguishes one) before a mandate. The declaration is checked against
  their address at the mandate's signing and at each sign-in. A mismatch
  pauses live execution until it is resolved.
- **The list:** live execution is refused wherever the venue blocks
  trading or makes it close-only, **including the places that are
  close-only only on its front end** (Ireland, Japan, Malta for sports,
  the Netherlands, South Korea). The API answering from there makes it
  unblocked, not lawful. The list is kept as data, reviewed monthly and
  whenever the venue changes its page, and a change pauses the people it
  affects. Legal advice may lengthen it; nothing short of legal advice
  shortens it.
- **United States:** refused on this venue (F13). Polymarket US is a
  separate question (`docs/venues.md`).
- **The host:** orders go out from the execution service's address, so
  its region must itself be somewhere trading on the venue is lawful.
  **This revisits flag F1.** Amsterdam, the first candidate for the
  platform, is in the Netherlands, which the venue makes close-only on its
  front end. The rest of the platform (paper trading, no orders) may stay
  there if lawful. The execution service's region is chosen with legal
  advice and probed with the geoblock endpoint before anything is
  deployed.

## 12. The Venue's Builder Programme (flag F4)

Session keys need a builder API key, so **the platform becomes a
builder:**

- its own account;
- its builder code attached to every live order, for attribution;
- the builder key held only by the execution service.

People bring their own Deposit Wallet. The platform does not create
wallets for them, which the builder key could do: wallet creation is the
venue's relationship with the person, and keeping out of it keeps the
platform from ever touching their funds. **Recommended: no builder fee.**
Charging one makes the platform a party with an interest in volume, which
is at odds with a mandate meant to limit it.

## 13. Fees, pUSD and Approvals

- **Fees:** from the market's `feeSchedule` at the moment of the order,
  the same function paper and backtests use. The venue's `feeRateBps` and
  the fill are recorded, and the live views show live against paper
  (fills, slippage, fees; task 116).
- **pUSD and the four approvals** are the owner's to make, since a session
  key cannot. The page links the person to make them on the venue, or
  prepares a relayer transaction for their wallet to sign in the browser.
  The execution service checks the allowances before the first order and
  refuses while any is missing.

## 14. Audit

Every step is a ledger entry through the redaction filter: proposal,
approval, pending-action marker, the signed order's hash (never the
signature), the venue's response, fill, settlement, halt, mandate
version, key authorisation and revocation. Addresses appear; keys,
signatures and credentials never do. The ledgers are verified daily from
the first entry (Phase 21) and copied daily to write-once storage (object
lock at the deploy).

## 15. Rollout

1. The deploy (F16), with the execution service in a region settled by
   section 11.
2. The canary (task 115): the owner's own wallet, one domain, one promoted
   strategy, the venue's minimum order, a fixed number of settlements, a
   total mandate of a few dollars. It is widened only by a new signed
   version after its ledger has been read.
3. The external security review (task 117) before anyone but the canary
   workspace can trade.
4. People, one mandate at a time, each starting at the canary's caps.

## 16. To Agree

| # | Decision | Recommended |
| :--- | :--- | :--- |
| S1 | Key model | A (session keys) for execution; B (wallet signature in the browser) for mandates, widening and large approvals; no C |
| S2 | Where signing runs | A separate execution service with its own role, host and key permissions, no model, a heartbeat |
| S3 | Jurisdiction list | The venue's blocked and close-only places, **including front-end-only ones**, plus whatever legal advice adds |
| S4 | Host region for the execution service | Chosen with legal advice; **not the Netherlands** on the venue's own list; F1 revisited |
| S5 | Builder programme | Become a builder (required for session keys); code on every order; no builder fee; no wallet creation for people |
| S6 | Order types | Limit only (GTD default, FAK at our limit when taking, post-only where supported); never market orders |
| S7 | Flatten on halt | Off by default; a mandate may turn it on |
| S8 | Approval thresholds | Canary: every order approved in a channel. Later: set per mandate, with a wallet signature above it |
| S9 | Session-key expiry | Notices at 30, 7 and 1 days; stop with a notice at expiry |

## Out of Scope Until Agreed

Everything that signs or sends: the execution adapter (task 113), the
channel approvals for orders (task 114), the canary (task 115) and the
live views (task 116). Also out of scope: more than one venue, automatic
widening of any mandate, and any key that can withdraw.
