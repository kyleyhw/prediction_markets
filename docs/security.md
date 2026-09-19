# Live Execution: Security Design (Phase 11, task 22)

**Status: base for version 2.** Proposed on 2026-09-13 for live execution
from an operator's machine. On 2026-09-19 the owner decided that live
execution is hosted only, so that a strategy trades while the user's
computer is closed, and is built last (Phase 22 of the plan). This page is
therefore the base that version 2 revises: sections 2 to 7 carry over; the
keyring of section 1 is replaced by the venue's session keys held under
envelope encryption, and approvals move to the browser and chat channels
(plan, task 112 and flag F12). The invariant is unchanged until version 2
is agreed: no order-signing code.

Original text follows. The safety layer described in
sections 2 to 6 is implemented and tested in `vp/live/` (mandate guard,
kill switch, environment separation, proposal-and-approval protocol,
keyring credential access); none of it can sign or send an order. Order
signing and placement (task 23) and the canary (task 24) are not written
until this design is agreed; the invariant is recorded in `CLAUDE.md`.
Agreeing may mean changing the caps, the approval expiry (15 minutes) or
the file format (JSON, `docs/security.md` § 3), all of which are
parameters of the code as written.

Live execution means signing orders with a key that controls real funds on
Polymarket's CLOB. Everything in this design exists to bound what a bug, a
compromised dependency, a bad forecast, or a mistaken operator can lose,
and to make every action attributable after the fact. The principles: keys
never touch the repository; paper and live are structurally different
credentials, not a flag; every order passes a fail-closed guard against a
written mandate; a human can stop the process from outside it; and every
decision is in the hash-chained ledger before it is acted on.

## 1. Keys

- The signing key (the Polymarket wallet's private key) and the CLOB API
  credentials derived from it live in the operating system keyring
  (`keyring` library: macOS Keychain, Secret Service on Linux, Windows
  Credential Locker), under a service name that includes the environment
  (`vibe-predict/live`). They are read at process start into memory only.
- Nothing key-shaped is ever in the repository, `.env`, a config file, a
  log, a ledger entry or an error message. `detect-secrets` already runs in
  pre-commit; the live module adds a redaction filter on its logger.
- The development container used for this project has no keyring and no
  network path to a signing wallet; live execution runs only on an operator
  machine.

## 2. Paper and Live Cannot Cross

- Two keyring entries, `vibe-predict/paper` (may be empty: paper trading
  needs no key) and `vibe-predict/live`. The execution adapter is
  constructed with an `Environment` enum; the live constructor reads only
  the live entry and refuses to start if the entry is missing or if the
  process was started with the paper ledger path.
- The ledgers are separate files with the environment name in the genesis
  entry; a live adapter refuses a ledger whose genesis says paper.
- The paper loop imports nothing from the live module, so a paper run
  cannot sign by accident.

## 3. The Mandate

A versioned JSON file (`vp.live.mandate.Mandate`, version 1), read at
start and again before every order, with hard caps that the guard
enforces and the operator cannot override at runtime:

| Cap | Meaning |
| :--- | :--- |
| `max_order_notional` | Stake of any one order, in USD |
| `max_market_exposure` | Total stake across open positions in one market |
| `max_total_exposure` | Total stake across all open positions |
| `max_orders_per_day` | Orders in any rolling 24 h window |
| `max_daily_loss` | Realised plus unrealised loss in 24 h that halts trading |
| `allowed_domains` | Domains the adapter may trade |
| `expires_at` | Instant after which every order is refused |

A cap the guard cannot evaluate (a missing price, a ledger that will not
replay or verify, an unparsable mandate, a missing or non-positive cap, a
wrong version) is a refusal: the guard fails closed. `Guard.check` returns
a `Decision` with the reason, and the tests exercise every refusal path.
Exposure, the daily order count and the daily realised loss are replayed
from the ledger, so the guard reads the same record the audit does.

## 4. The Kill Switch

A file path outside the repository (`~/.vibe-predict/STOP`, or
`VP_STOP_FILE`). The adapter checks for it before every order and every
cycle, and exits if present. It
is independent of the process: the operator, a cron job, or a monitoring
script can create it without talking to the running process, and removing
it is a deliberate act. The guard also stops if the ledger chain fails to
verify.

## 5. Human Approval

Every write (order placement, cancellation) is proposed as a ledger entry
of kind `proposal`, and the adapter waits for an `approval` entry naming
that proposal's hash and a named approver before signing. An approval
expires after 15 minutes and is consumed by the order that references
it, so one approval cannot cover two orders (`vp.live.controls`). In the first phase the approval is typed by
the operator at a prompt; an auto-approval policy, if ever adopted, is a
later mandate version with its own caps and is not part of this design.

## 6. Audit

The live ledger is the paper ledger's format: every proposal, approval,
signed order (its hash, never the signature), venue response, fill, and
settlement is an entry. The chain is verified at start and after every
append. A daily job copies the ledger to write-once storage.

## 7. Rollout (task 24)

Canary at the minimum stake the venue allows, one domain, one forecaster,
for a fixed number of settled positions, with `max_total_exposure` at a
few dollars; the mandate is widened only by a new version after the canary
ledger has been read.

## Out of Scope Until Agreed

Order signing and placement (task 23), automatic approval, more than one
venue, and any credential handling beyond the keyring.
