# Vibe-Trading: What It Is, What It Has, What vibe-predict Takes

Reviewed on 2026-09-18. The snapshot is [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading)
at commit `e5f7195` (version 0.1.15, released 2026-09-09, plus nine days of
unreleased changes) and the public site [vibetrading.wiki](https://vibetrading.wiki/home/),
whose source is the repository's `wiki/` directory. The first review, on
2026-09-13 at commit `afe7d7d`, looked for code to port and is recorded in
[provenance.md](provenance.md). This review read the product whole: the wiki
(home, the docs content, the Chinese beginner tutorial, the Alpha Library page,
the Research Lab study), the README (2,129 lines), the changelog, the
contributor and agent-contributor guides, the security policy, the desktop
threat model, the module docstrings and data models of every package under
`agent/src` (1,764 Python files, about 423,000 lines), the frontend page list,
and the CI gates.

Its purpose is threefold: to take inspiration for an analogue built for
prediction markets, without infringing on anything; to record Vibe-Trading's
collaborative tools and capabilities specifically; and to judge how it is
built for scale, since vibe-predict is to serve many users. The conclusions
feed [PROJECT_PLAN.md](../PROJECT_PLAN.md) Phases 13 to 23 and
[scaling.md](scaling.md).

## 1. Vibe-Trading in One Paragraph

Vibe-Trading is an open-source (MIT) finance research workspace from the
University of Hong Kong's data-intelligence group. A natural-language prompt
is routed to skills, data loaders, tools and, when useful, a team of worker
agents; the agent grounds itself in fetched market data, writes strategy code,
runs it through one of ten market-specific backtest engines, validates the
result with benchmark comparison, bootstrap, Monte Carlo and walk-forward
checks, and delivers a report, a run card and an artifact trail that a later
session can pick up. Around that loop it has grown persistent memory, an
editable skill library, a 460-alpha factor zoo with a one-line bench, a
"Shadow Account" that turns a broker journal into a rule-based counterfactual,
eighteen broker connectors behind a bounded-autonomy mandate and kill switch,
sixteen chat-channel adapters, a scheduler with delivery to those channels, an
MCP server and client, a React web UI in eight languages, and an Electron
desktop shell. Its stated boundary is research first: live trading is opt-in,
read-only by default, bounded by user-set limits, instantly haltable, and it
holds no funds.

## 2. Size, as of the Snapshot

| Measure | Count | Source |
| :--- | ---: | :--- |
| GitHub stars / forks | 33.6k / 5.5k | repository page |
| Finance skills (markdown, frontmatter) | about 90 in 9 categories | README, `agent/src/skills` |
| Swarm presets (YAML teams) | 30 | `agent/src/swarm/presets` |
| Alpha Zoo factors | about 460 in 5 zoos | README, `agent/src/factors` |
| Backtest engines | 10 plus an options portfolio engine | README |
| Market-data loaders | 27 with per-market fallback chains | README |
| Broker connectors | 18 (read, paper, bounded live where supported) | README |
| MCP tools exposed | 74 | README |
| Chat-channel adapters | 16 | `agent/src/channels` |
| Quant library | about 300 tested functions in 23 modules | README |
| Scheduled-research playbooks | 5 | `agent/src/scheduled_research/playbooks` |
| Web UI locales | 8 | `frontend/src/i18n/locales` |
| Contributors in the 0.1.15 cycle | 35, 551 commits, 162 merged PRs | CHANGELOG |

## 3. The Research Loop and the Artifact Trail

The wiki states the loop as four steps and the docs as five; they are the
same thing.

1. **Route** (Plan): choose skills, tools, data sources and, when useful, a
   swarm preset from the request.
2. **Ground**: fetch market bars, documents, URLs, broker journals or local
   files at runtime. Swarm workers are additionally pre-fed the last weeks of
   prices for any symbol named in the request, because "without explicit
   grounding they cheerfully quote prices from their training data"
   (`swarm/grounding.py`). This is the same reasoning as vibe-predict's
   cutoff-bounded `Evidence` object.
3. **Test** (Execute): generate a run directory (`config.json` plus
   `code/signal_engine.py`), validate it, run the matching engine in a
   narrow subprocess.
4. **Validate**: metrics, benchmark comparison, Monte Carlo, bootstrap
   intervals, walk-forward, warnings, and a run card.
5. **Deliver**: the answer plus inspectable artifacts: reports, charts,
   generated code, tool traces, a run manifest, and exports (Pine Script,
   TDX, MetaTrader 5).

The artifact trail is the product's centre of gravity. Every run has a
directory; every run has a **manifest** that hashes the system prompt, each
injected skill's content, the tool registry and the key package versions into
one deterministic hash, with timestamps deliberately excluded so that two runs
under the same methodology hash identically and `diff_manifests` can name what
changed (`governance/manifest.py`). Every live-money action goes to a
hash-chained, fsynced, append-only ledger (`governance/ledger.py`). An offline
**evals harness** reads a finished run's files and emits one verdict per
assertion, with `NOT_EVALUABLE` kept distinct from `PASS` so that missing
instrumentation can never read as good behaviour (`evals/harness`).

## 4. Capabilities by Area

### 4.1 Agent harness

A ReAct loop (`agent/loop.py`, 3,300 lines) with five layers of context
compression (pruning old tool results, folding long text without an LLM call,
LLM summaries with tail protection, an explicit `compact` tool, and iterative
summary updates), parallel execution of consecutive read-only tools, and two
guards that matter for any agent that spends money: after eight consecutive
tool calls without a new successful observation the run stops with a visible
recovery request, and an identical call is refused from its second failure
onward. A final-answer **grounding gate** classifies every number in the
answer by shape (measurement, date, code, ordinal) and requires each
measurement to be observed in a tool result, derived by an evaluable formula
from observed values, or declared with a source; a failing draft gets one
correction round and is then released with the failing figures cut and a
footnote saying so (CHANGELOG, unreleased). Prompt-injection scanning adds
warning metadata to fetched content without rewriting it. Provider
abstraction covers Anthropic, OpenAI-compatible, DeepSeek, Gemini and the
GitHub Copilot SDK, with prompt caching on the Anthropic adapter.

### 4.2 Data and backtesting

Twenty-seven loaders behind a registry with per-market fallback chains and a
`source="auto"` router; a `local` loader for CSV, Parquet and DuckDB; the
0.1.15 theme of "data that says what it is" (a price frame carries its
adjustment caliber, factors propagate NaN instead of filling zero, a failed
portfolio source is an error excluded from totals rather than a carried-forward
cache). Ten engines encode market rules (T+1 settlement, price bands, lots,
tick grids, taxes, funding, margin); intraday bars down to one minute; five
portfolio optimisers; validation tools; a data window separated from the
evaluation window so warm-up bars are not graded. Generated strategy code runs
as a local subprocess with a narrow environment that never receives LLM keys,
auth tokens or broker secrets (SECURITY.md).

### 4.3 Alpha Zoo

About 460 cross-sectional alphas in five zoos (Qlib Alpha158 under Apache-2.0
with a pinned commit; Kakushadze's 101; Guotai Junan's 191; twelve academic
anomalies; four point-in-time fundamental factors). Each alpha is a pure
`compute(panel)` with an `__alpha_meta__` record (formula in LaTeX, theme,
universe, frequency, decay horizon, warm-up, columns required). Two automated
gates protect the corpus: an **AST purity gate** that rejects any import
outside an allowlist and any reference to `os`, `subprocess`, `socket`,
network libraries, `eval`, `exec`, `open` or dunder `getattr`; and a
**lookahead gate** that forbids negative shifts and runs a 300-row sentinel
test. A one-line bench (`alpha bench --zoo --universe --period`) computes the
cross-sectional information coefficient per day and classifies each alpha as
alive (mean IC above 0.02, t above 2, positive on at least 55% of days),
reversed (significantly negative) or dead. Licensing is handled per zoo with a
provenance note that reproduces formulas only, as mathematical content, and
none of the source reports' prose, tables or figures; a CI grep gate bans a
third party's trademark string from shipped artifacts.

### 4.4 Quant library and valuation

One tested implementation of each piece of finance mathematics the agent
needs, callable from every transport through a read-only `quantlib_call`
tool, on the rule that a formula living in a skill's markdown is a bug: the
model used to retype formulas into throwaway code on every run, which was
neither reproducible nor reviewable. Valuation models refuse to run on a
missing input rather than default it ("every default in a valuation model is
an opinion wearing a constant's clothes").

### 4.5 Shadow Account and Trade Journal

The flagship loop for an individual: parse a broker export (three Chinese
brokers plus generic CSV), profile behaviour (holding time, win rate, P&L
ratio, drawdown, disposition effect, over-trading, momentum chasing,
anchoring), extract three to five if-then rules that describe the profitable
round trips, backtest the rule-based "shadow" of the user across markets,
attribute the delta between actual and shadow P&L, render an HTML or PDF
report, and scan today's symbols that match the shadow's entry cadence.

### 4.6 Portfolio

A read-only aggregation of holdings across the broker connections the user
picks, with per-source provenance, immutable snapshots in SQLite, CSV export,
and a sanitised summary tool that feeds a risk x-ray. Eligibility is a single
structural rule (read-only profile that declares account and position reads),
and a connector that fails to refresh is reported as an error and excluded,
never carried forward.

### 4.7 Swarm teams

Thirty presets, each a YAML file naming agents (role, system prompt, tools,
skills, iteration and time budgets) and tasks with dependencies, run as a DAG:
parallel within a topological layer, serial between layers, in a background
thread with cancellation and streamed events. Runs persist as `run.json`,
`events.jsonl`, per-task state, inter-agent inboxes and artifacts, and can be
resumed keeping completed tasks. User presets in a home directory override
bundled ones by name. Workers may call operator-allowlisted external MCP
tools; caller variables are template data only and cannot inject servers.
The presets are committee-style: bull/bear debate then risk review then a
final call; screening then factor research then backtest then risk audit.

### 4.8 Memory, skills, sessions and goals

Cross-session **memory** is a directory of markdown entries with frontmatter
(type, keywords, importance, quality score, access count, compression level),
auto-recalled into the system prompt, with optional lifecycle features behind
flags: quality updates, Ebbinghaus-style decay, garbage collection, a
three-level compression pipeline and an FTS5 index. **Skills** are markdown
guides with progressive disclosure (one-line summaries in the prompt, full
text on demand, section-by-section paging for the long ones), editable and
creatable by the agent through a CRUD tool, with a user directory that
overrides the bundle. **Sessions** are multi-turn with attempts, SSE streams,
checkpoints of streaming text, cancellation, auto-titles and a cross-session
FTS5 search. **Research goals** are a ledger of claims, protocol criteria and
evidence rows (each with provider, URI, method, assumptions, artifact hash,
freshness and verification status, and the claims it contradicts), with
token, turn and time budgets, a risk tier from general research up to live
execution, and a completion audit per criterion. A **hypothesis registry**
tracks thesis, signal definition, data sources, linked run cards and
invalidation notes. The **Strategy Development Manager** stores research
artifacts with a decay state machine (active, monitoring, decayed, disabled)
driven by IC ratio, information ratio and Sharpe thresholds with consecutive
warning counts, and the **Strategy Discovery** facade answers per-regime
questions only from harness-computed evidence, saying so when the table is
empty.

### 4.9 Governance and trust

The run manifest and hash-chained ledger described in section 3; sink-aware
redaction (tool-call arguments and the live ledger keep `content` redacted,
the tool-result sink releases it after pattern scrubbing, `env` is never
released); a no-hidden-clock rule (governance modules take timestamps from the
caller and a CI gate rejects `datetime.now()` in named files); an env-var gate
that confines environment reads to one config layer; a trust invariant for the
live mandate that the agent loop has no code path to write it.

### 4.10 Live trading

The most carefully built part. A **mandate** is an immutable record of hard
caps (funding, order notional, total exposure, leverage, instruments, trades
per day), a universe constraint, and consent provenance (a consent token hash,
broker, account reference, expiry). It is written by exactly one function
that the tool registry cannot discover, called only by the web surface with a
consent acknowledgement the model never produces: a proposal is not a mandate.
Every order-placing tool is wrapped in a fail-closed **gate** that in fixed
order loads the mandate, checks expiry, checks the **kill switch** (a
filesystem sentinel, global or per broker, whose existence is the halt and
whose JSON is only attribution), binds the account, parses the intent, reads
positions and balance through the broker's own read path, and evaluates the
caps; a structural breach denies, a quantitative breach pauses for
re-authorisation. Remote broker tools are classified read or write by a
three-tier ladder (server annotations, a curated map that wins, default-deny),
so an unrecognised tool is never exposed ungated. A crash-safe **pending
action** marker owns each unresolved broker side effect; a persistent runtime
has a durable job store, heartbeats, reconciliation and a preemptive
cancel-then-flatten on halt (flattening off by default). Every action fans
out to a compliance ledger, the run trace and the UI event stream, redacted.
An observational **advisory** layer can attach a risk opinion and can never
block. A credential-proxy mode (TAP) lets the process hold no broker key at
all, with writes gated on human approval in a chat channel. Paper and live
are separated by a structural per-broker discriminator, never a flag; a broker
without one is capped at paper.

### 4.11 Delivery: scheduled research and chat channels

**Scheduled research**: jobs with an interval or a five-field cron expression
on an IANA timezone, persisted and DST-proof; five playbook templates whose
bodies state the data capability they need in plain language rather than a
tool name, resolve "today" at run time, declare their variables and reject
undeclared ones; the agent may only propose a schedule, and a deterministic
confirmation card, a CLI `y/N` or an exact "confirm" in chat commits it; each
run's briefing ends in a machine-readable verdict block that a watch list
renders without re-reading prose; delivery goes to an opaque target
reference, through a persisted outbox with retries and provider receipts.
**Channels**: a plugin architecture with a message bus, a manager and sixteen
adapters (WebSocket, Telegram, Slack, Discord, Matrix, WhatsApp, Signal, QQ,
NapCat, WeChat, WeCom, Feishu, DingTalk, Teams, email, Mochat); unknown direct
senders receive a pairing code that an operator approves; pairing control in
chat is refused unless the sender is a configured operator; a per-channel
session map keeps one conversation per chat; in-chat slash commands reset a
session; a reply-wait budget bounds long runs.

### 4.12 Interfaces

A terminal TUI with slash commands (model, memory, history, goal, search,
swarm, skill, journal, shadow, export, valuation workflows, playbook,
connector, halt, resume); a FastAPI server with REST and SSE, loopback
dev-trust or one shared bearer key, single-use tickets for browser event
streams, CORS and DNS-rebinding guards, security headers, and shell tools off
on every non-local surface; a React 19 web app (home, agent chat, alpha zoo,
run detail, compare runs, correlation regime, options lab, portfolio,
reports, runtime, scheduled, settings) with charts, KaTeX and eight locales;
an MCP server exposing 74 read and research tools (order tools deliberately
never on MCP) over stdio, SSE and streamable HTTP; an MCP client that loads
operator-allowlisted external servers; an OpenBB Workspace bridge; a
ClawHub one-command install; an Electron desktop with a written
process-boundary threat model, per-launch random API secret, sandboxed
renderer, credential encryption and a dormant, fail-closed updater.

### 4.13 Evaluation

Beyond the offline evals harness, the project runs an internal "harness v2"
end-to-end suite and publishes a Research Lab study (which of the 191 GTJA
alphas still work in 2026, on CSI 300 over 2018 to 2025) whose every number
is reproducible with one CLI command and whose caveats section is longer than
its findings: one-day IC is not profitability, one universe, a short window,
survivorship in the constituent list, no regime conditioning.

### 4.14 Community process

Developer Certificate of Origin sign-off on every community commit and no
AI-assistant attribution trailers; a reviewer checklist for alpha PRs
(purity gate, lookahead gate, metadata, LaTeX matches code, licence note,
attribution); a contributor guide addressed to AI-assisted contributors that
lists safe local checks and high-risk surfaces needing explicit approval; a
security policy with private advisories and a note on impostor communities;
an issue-driven roadmap; Discord, WeChat and Feishu groups; a static wiki on
Cloudflare Pages with versioned docs, tutorials, the alpha library and the
research lab, and an anonymous first-party visit counter that distinguishes
AI agents from humans.

## 5. Collaborative Tools and Capabilities

Vibe-Trading is built for one operator, but several of its features are
about working together, and they are the ones a hosted, many-user product
must reproduce or improve on.

- **Agents collaborating: swarm teams.** The committee presets are
  explicitly modelled on how research desks work: specialists in parallel,
  a reviewer, a decision maker. Progress streams to the UI; the run persists;
  a failed run resumes with its completed tasks. Presets are files a user can
  write and share.
- **Humans and the agent in one conversation: chat channels.** The same
  session runtime serves the web UI, the CLI and sixteen chat platforms, so
  a team can put the agent in a group chat. Sender pairing and operator roles
  decide who may talk to it and who may administer it; the session map keeps
  one thread per chat.
- **Research delivered to a team on a schedule.** A scheduled job's briefing
  goes to a named delivery target such as `research-team` on Feishu or
  Slack, with an outbox that retries and records provider receipts, and a
  verdict block a watch list can render.
- **Shareable, overridable artifacts.** Skills, swarm presets, playbooks and
  read-only broker connectors all follow one pattern: a bundled set, a user
  directory that adds to or overrides it by name, and survival across
  upgrades. Skills are published to OpenSpace for self-improvement and
  community sharing; the whole tool is installable from ClawHub.
- **Agent-to-agent.** The MCP server makes Vibe-Trading a tool for other
  agents (Claude Desktop, Cursor, OpenClaw); the MCP client lets its own agent
  use other servers; the OpenBB bridge puts it inside another workspace.
- **Human approval in the loop.** Mandate commits, scheduled-job proposals
  and (in TAP mode) every broker write require an action on a human surface
  that the model cannot perform. Approval can happen in a chat channel.
- **Community contribution as collaboration.** The alpha checklist, the DCO
  process, the agent-contributor guide and the reproducible Research Lab
  posts are how strangers collaborate on the corpus.

What it does **not** have, and what vibe-predict will need: user accounts,
teams or workspaces, per-object permissions, shared strategies with roles,
comments or annotations on runs, leaderboards, or attribution of an action to
a named person. Its own `Principal` model says so plainly: under a shared
bearer key "every request from every person looks identical", the
`attributable` flag "stays False until an identity provider is wired in", and
`tenant` exists "for a future multi-tenant runtime root".

## 6. Scaling Posture

Vibe-Trading is a single-operator local application and does not pretend
otherwise. State lives in files under a home directory (sessions, runs, swarm
runs, memory, mandates, ledgers) with SQLite for full-text indexes and the
portfolio snapshots; the pairing store is "designed for private-assistant
scale: small JSON file, simple locking, no external DB". The API authenticates
with one process-wide static key or loopback trust. Concurrency control is an
in-process semaphore of two for alpha benches and a thirty-per-minute sliding
window on one endpoint; budgets are per session (tokens, turns, seconds) and
per session for a paid data marketplace. The scheduler is off by default.
Deployment is a Docker Compose file or `pip install`. The one thing designed
for scale is the wiki, which is static on a CDN with a serverless counter.

None of this is a criticism: it matches the product. It does mean that
almost nothing in Vibe-Trading's runtime is a model for a service with many
users, and that vibe-predict's platform has to be designed for that from its
first hosted release rather than retrofitted. [scaling.md](scaling.md) is
that design.

## 7. What vibe-predict Takes: The Mapping

Everything in the right-hand columns is re-derived for binary contracts
scored with proper scoring rules under an explicit information cutoff; the
left-hand column is the inspiration, not the specification. Phase numbers
refer to [PROJECT_PLAN.md](../PROJECT_PLAN.md).

| Vibe-Trading | vibe-predict analogue | Phase | What differs |
| :--- | :--- | :--- | :--- |
| Research loop: route, ground, test, deliver | Research session: ask, ground at the cutoff, test by backtest or paper, deliver a run card | 15 | Grounding is the cutoff-bounded `Evidence` object and the archive; nothing is fetched live in a backtest |
| Generated strategy code in a run directory | Strategy **spec**: data, not code; versioned, immutable, rendered to plain language deterministically | 15 | No user code is executed anywhere, which is what makes multi-tenant execution safe and results reproducible |
| Run card and run manifest | Run card and run manifest (spec hash, forecaster and pack hashes, dataset version, fee schedule version, model ids) | 15 | Same idea; timestamps excluded from the hash |
| Grounding gate on numbers in the answer | The number gate: the assistant shows only numbers the engine computed; the model's only number is the probability, which is scored | 15 | Inverts Vibe-Trading's "the model produces no numbers": here it produces exactly one, under a proper scoring rule |
| Loop guards, context compression | Same guards; sessions are short so compression is light | 15 | |
| Skills library, editable, progressive disclosure | Domain packs: how a domain's markets are phrased, what evidence exists, base rates, pitfalls; platform packs versioned and hashed, user copies editable | 15, 17 | Written from primary sources; never copied |
| Persistent memory with auto-recall | Per-user memory the user can see, edit and delete; never silently overrides a spec | 15 | |
| Session search | Workspace search across sessions, strategies and runs | 18 | |
| Alpha Zoo with purity and lookahead gates and a one-line bench | **Signal library** with purity and cutoff gates and `vp signals bench`: skill against the market with intervals, alive, at par or anti, over rolling windows | 16 | Cross-sectional IC becomes paired proper-score skill against the market price on the same markets |
| Swarm presets | **Forecast committees**: role forecasters in a DAG behind the `Forecaster` interface, YAML presets, aggregation rules, streamed progress, cost accounted | 16 | Evaluated against single elicitation on matched samples before being offered |
| Hypothesis registry, research goals with criteria and evidence rows | Strategy lifecycle and the **promotion protocol**: criteria with numbers, evidence rows linked to runs, an audit per criterion, a human approval | 15, 20 | |
| Strategy Development Manager decay states | **Strategy health**: rolling forward skill with a sequential test; healthy, watch, decayed; auto-pause | 20 | Skill against the market, not IC |
| Shadow Account from a broker export | **Shadow forecaster** from a public Polymarket address: closing-line value, calibration, biases, rule extraction, counterfactual | 19 | No export needed: positions and activity are public on the Data API |
| Portfolio aggregation and risk x-ray | Exposure by event and resolution date, correlated outcomes, simultaneous Kelly, worst case at settlement | 20 | Outcomes are discrete and correlated within events |
| Mandate, consent state machine, fail-closed gates, kill switch, pending actions, audit with redaction | Security design v2 for the hosted setting, on the existing safety layer | 11, 22 | Session keys replace broker credentials: scoped, revocable, unable to withdraw |
| TAP credential proxy with chat approval | Session keys held in a key-management service; approvals through channels | 22 | |
| Scheduled research, playbooks, propose-then-commit, verdict blocks, delivery targets, outbox | **Scheduled briefs** with the same shape | 18 | |
| Sixteen chat adapters, pairing, operators | Channels: email first, then Telegram, Discord, Slack, a generic webhook; the same bus and pairing pattern | 18 | Fewer adapters, multi-tenant from the start |
| MCP server (no order tools) | MCP server with per-user scoped tokens, read-only tools, never an order tool | 18 | |
| MCP client for external tools | Not adopted for backtests (evidence must come from the archive); considered for the forward loop only | 17 | |
| OpenBB bridge, ClawHub | Public API with tokens, webhooks out | 18 | |
| Offline evals harness | Evals harness over session and run artifacts, with `NOT_EVALUABLE` distinct from pass | 15 | |
| Governance ledger and manifest | Hash-chained ledger (built in Phase 10) per account; manifests per run | 10, 13, 15 | |
| Env-var gate, no-hidden-clock gate, trademark gate | Config layer with one env reader; injected clocks in jobs; a name gate for the review and provenance pages only | 13, 23 | |
| Alpha licence notes, DCO, reviewer checklist | Signal contribution checklist with citation and licence note; DCO to decide | 18, 23 | |
| Wiki: docs, tutorials, alpha library, research lab | Docs site: Learn, Signals, Research Lab with one-command reproduction | 23 | |
| Principal with a placeholder tenant | Real tenancy: workspaces, roles, attributable identity, row-level security | 13 | |
| Per-session budgets, in-process semaphores | Per-user budgets with reservations, a job queue with worker pools, provider concurrency limits | 13 | |
| React web app, eight locales | Build-free app (decided in product.md) with an internationalisation structure from Phase 14 | 13, 14 | |

## 8. What vibe-predict Does Not Take, and Why

- **Executing generated code.** Vibe-Trading's strategies are Python files
  the agent writes and a subprocess runs. That is right for a local research
  tool on continuous prices. For a hosted service it is the largest attack
  surface and the largest source of irreproducibility, and prediction-market
  strategies do not need it: a selector, a belief, a rule and a sizing policy
  are data. Strategies are specs; the engine interprets them.
- **Ten engines, twenty-seven loaders, eighteen brokers.** One venue keeps
  the record, the fee model and the execution path singular. Polymarket US
  and Kalshi are noted as future venues, not built.
- **Options, futures, perpetuals, portfolio optimisers for continuous
  assets.** Different instruments.
- **"The model produces no numbers."** Vibe-Trading forbids its model from
  producing figures because the model is a code writer. Our model is a
  forecaster whose one number is a probability under a strictly proper
  scoring rule; everything else it shows the user comes from the engine.
- **A terminal for users, an Electron desktop.** The product decision in
  [product.md](product.md) is a browser for users and the command line for
  developers and the operator.
- **A large bundled skill corpus.** Domain packs are written as domains are
  onboarded, from primary sources, and measured by whether they change
  scores.

## 9. Staying Clear of Infringement

Vibe-Trading is MIT-licensed, so reuse with attribution is lawful. The
project nonetheless keeps a wider margin, because it is an analogue and
should be unmistakably its own work:

1. **Name and marks.** The product is vibe-predict. The words "Vibe-Trading",
   the HKUDS name, their logo, screenshots, feature images and colour scheme
   appear nowhere in the product, its pages or its marketing. The name is
   used nominatively only in [provenance.md](provenance.md), this page, the
   `NOTICE` file, the plan's reference section and the README's one
   provenance sentence. A CI check enforces that list (Phase 23).
2. **Code.** Exactly three modules were adapted, each recorded with its
   source path, line count and changes in provenance.md and covered by the
   MIT text in `NOTICE`. Any further port goes through the same record with
   the upstream commit hash. Design patterns (run manifests, purity gates,
   committee DAGs, pairing codes, propose-then-commit) are re-implemented
   from their description, not copied.
3. **Text.** No README, wiki, tutorial, skill, preset, playbook or prompt
   text is reproduced. Domain packs, committee presets, playbooks and Learn
   pages are written for prediction markets from primary sources with
   citations.
4. **Third-party content they bundle.** Their alpha zoos and their vendors'
   data are not relevant to prediction markets and are not touched.
5. **Attribution the other way.** No assistant attribution appears in this
   repository's commits or documents, which is also Vibe-Trading's rule and
   the project owner's.

## 10. References

- HKUDS (2026). *Vibe-Trading: Your Personal Trading Agent.* Version 0.1.15,
  commit `e5f7195`. [Repository](https://github.com/HKUDS/Vibe-Trading),
  [wiki](https://vibetrading.wiki/home/). MIT License.
- Vibe-Trading Research Lab (2026-05-17). *Which of the 191 GTJA alphas
  still work in 2026?* [Post](https://vibetrading.wiki/research-lab/posts/alpha-191-in-2026.html).
- Vibe-Trading `CONTRIBUTING.md`, `AGENT_CONTRIBUTOR_GUIDE.md`,
  `SECURITY.md`, `desktop/electron/THREAT_MODEL.md`, at the same commit.
