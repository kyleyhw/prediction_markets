# Contributing

Contributions are welcome under the repository's MIT licence. Three things
are asked of every one.

## Sign off your commits

This project uses the [Developer Certificate of Origin](https://developercertificate.org/):
by adding a `Signed-off-by: Your Name <you@example.com>` line to each
commit (`git commit -s`), you certify that you wrote the change or have the
right to submit it under the project's licence. The pull-request check
refuses a commit without one.

## Keep the gates green

CI runs, and a pull request passes, the same commands a contributor runs
locally: `uv run ruff check .`, `uv run ruff format --check .`,
`uv run ty check` and `uv run pytest -q`, plus the pre-commit hooks
(stage new files first: `pre-commit run --all-files` skips untracked
files). The tests include these contribution gates:

- **No secrets.** The detect-secrets hook runs over every file.
- **No market-data dumps in the docs.** No data files under `docs/`, and no
  table or code block longer than 60 lines; results belong in
  `tests/reports/` as summaries, and data in the git-ignored `data/`.
- **The name gate.** The reference project this one learnt from is named
  only where attribution or a design note needs it, and never on a page
  people use (`docs/vibe_trading.md` § 9).

## What to contribute

- **A signal.** Follow the checklist in `docs/signals.md`: a module under
  `vp/signals/`, one line in the registry, and `vp signals check` passing
  (purity, metadata with a reference and a licence note, the cutoff
  sentinel, and a bench on at least one domain, whose file the pull
  request carries).
- **A domain pack.** `vp/domains/packs/<domain>.md` in the pack format of
  `docs/strategies.md`: how questions are phrased, fields, evidence and its
  cutoff, base rates, pitfalls, with sources. `tests/test_strategy.py`
  checks every pack parses.
- **A domain.** Follow `docs/domains.md`; opening one is the maintainers'
  decision, so open an issue first.

Nothing in a contribution may sign or send an order: live execution is
built last, by the maintainers, behind an agreed security design.

## Contributions written with an AI assistant

They are welcome on the same terms. The sign-off is yours: you certify the
change as if you had typed it, so read all of it. What the assistant must
be told, and what reviewers check first:

- **Run the gates, don't describe them.** The four commands above, and
  pre-commit after staging new files. A test that fails is a finding, never
  something to skip, loosen or mark as expected.
- **High-risk surfaces need a human reason for every line:**
  - row-level security and the migrations (`vp/platform/migrations/`,
    `vp/platform/db.py`);
  - sign-in, sessions and tokens (`vp/platform/auth.py`, `vp/platform/web.py`);
  - secrets and keys (`vp/platform/llmops.py`, `vp/platform/channels.py`,
    `vp/platform/webhooks.py`, `vp/platform/delivery.py`);
  - the ledgers and the audit chain (`vp/paper/ledger.py`,
    `vp/platform/ledger.py`, `vp/platform/audit.py`);
  - the MCP server's allow-list (`vp/platform/mcp_server.py`);
  - anything under `vp/live/`.
- **Invariants an assistant tends to break:**
  - a label comes only from settlement evidence, never a price;
  - every forecaster reads nothing after its cutoff;
  - the engine never imports `vp/platform`;
  - no code outside `vp/domains/` names a domain.
  Tests hold each of these, so a change that needs a test changed is
  suspect.
- **Nothing signs or sends an order** (above).
- **Say so in the pull request** when an assistant wrote a substantial
  part, and what you checked yourself.

## Reporting a vulnerability

Privately, as `SECURITY.md` says; not in an issue or a pull request.
