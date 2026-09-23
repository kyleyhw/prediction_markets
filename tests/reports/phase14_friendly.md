# Phase 14 Test Report: Friendly for Everyone

Date: 2026-09-23. Environment: Python 3.14.7 via `uv 0.12.18`, Node 22 for
the module check, Chromium through Playwright, Postgres 16 in the
development container; `vp serve` on a scratch data root and `vp ui` over
the demo data root built from the live venue for the interface work.

## Purpose

Phase 14 makes the app usable by someone who has never seen a prediction
market and by someone who wants the bootstrap interval: two reading levels,
a guided start, a brokerage-style home, market cards, charts with a
baseline, fees in both levels, Learn, settings, internationalisation and
accessibility (tasks 39 to 47, landed earlier the same day and recorded in
`docs/interface.md`); the legal ground a public service needs (task 48);
and the usability sessions (task 49). Added to it on 2026-09-23 by the
Phase 13 measurements: one sample account for everyone (flag F17).

## Static Checks

| Check | Result | Runtime |
| :--- | :--- | ---: |
| `ruff check .` and `ruff format --check .` | passed | < 1 s |
| `ty check` | passed, 0 diagnostics | 1 s |
| `pre-commit run --all-files` | all hooks passed | 3 s |

## Unit Tests

`uv run pytest -q`: 240 passed in about 11 s. What this part of the phase
added:

| Test | What | Why |
| :--- | :--- | :--- |
| `test_platform_work.py::test_everyone_reads_the_one_sample_account…` | two people read the same sample ledger, may not run or write it, and each export verifies offline; the platform's reserved address cannot sign in | F17 must not widen tenancy |
| `test_platform_handlers.py::test_the_platform_trades_the_sample_account…` | the platform's hourly job opens the account on first run and trades every domain into it; the read-only ledger refuses writes | the sample is the platform's alone to write |
| `test_platform_web.py::test_signing_in_needs_the_age_and_the_terms…` | the confirm page asks for 18+ and the terms, an unticked form spends nothing, the version is recorded, an old version is refused, `/terms` and `/privacy` carry it | task 48 |
| `test_platform_work.py::test_deleting_an_account_removes_everything…` | deletion needs the exact words; afterwards the session is dead, no row of the workspace is left in any table, the user is gone, the files are gone, the audit chain records it, and another person's work is untouched | the privacy notice's promise |
| `test_platform_ledger.py` (archive test, extended) | a deleted workspace's rows are rewritten out of the archived months | erasure reaches the archive |
| `test_platform_work.py::test_a_job_is_cancelled_by_its_workspace_only` | a job is cancelled by its own workspace, not another's | kept from the old paper-start test |
| `test_ui_catalogue.py::test_every_module_parses` | every page module parses as an ES module | a syntax error the other tests missed reached the browser this session |

## The Sample Account (F17)

One account, run by the platform in a workspace of its own as a system user
at a reserved `.invalid` address, traded hourly by a platform job and read
by every workspace through two `SECURITY DEFINER` functions. No tenancy
policy was widened, so no existing query can see a row it did not see
before. Measured before the change (`tests/reports/phase13_platform.md`):
every person's own sample account held the same orders, about 40,000
ledger rows a person a day. After: none per person.

## Terms, Age and Deletion (task 48)

Walked through in Chromium against `vp serve`:

| Step | Result |
| :--- | :--- |
| Sign-in page | the statement (a tool for building and testing, play money, not advice) and the jurisdiction notice; links to the terms and the privacy notice |
| Confirm page, box unticked | the browser will not submit; a forced submit is refused with nothing spent |
| Box ticked | signed in; `/auth/me` reports the current version accepted |
| Acceptance cleared by the owner | the app shows only the consent screen; an unticked "carry on" asks for the box; ticked, Home |
| `/terms`, `/privacy` | the versioned drafts, marked for legal review |
| Settings, "delete it" typed | refused: "Type the words exactly as shown." |
| Settings, "delete my account" typed | back at sign-in; the user's row count is 0 |

axe-core (WCAG 2.0 to 2.2, A and AA) on the seven pages of this walk: at
first, colour contrast failed on the four server-rendered pages (sign-in,
confirm, terms, privacy), whose blue accent predated the app's palette and
had never been audited; they now use the app's measured "paper" palette,
and all seven pass. The confirm page's checkbox label also broke into
columns (a flex label around loose text); fixed.

## Accessibility (task 47)

The pass with a real screen reader needs a person and is part of the
usability sessions (`docs/usability.md`). What an automated pass can do
instead was done on the demo data root: the accessibility tree of nine
views and a market page in both reading levels (what a screen reader is
given), and the keyboard focus order of each, 40 stops deep, checked for
unnamed or invisible stops (none) and a single `h1` per page (all). Read
through, they found two things:

- Home's main figure, the play-money balance, was plain text, so a person
  moving by headings went from "Home" straight to "In the last day"; its
  label is now a heading.
- Detailed Strategies gave a screen reader 20,838 lines, most of them a
  table of every open position (1,236 rows on the demo root) without a
  caption. The table now shows the 50 largest stakes, says how many there
  are and that the ledger download has them all, and has a caption: 720
  lines.

axe-core then ran on the eight main views in both levels and both themes:
32 renders, no violations (78 earlier the same day, `docs/interface.md`).

## A Fault the Browser Found

A syntax error in `views/strategies.js` (an unbalanced parenthesis left by
an edit) passed every Python test and blanked the page in the browser. A
plain `node --check` also passed it, because it reads the files as scripts;
the new test parses each module as a module and fails on it.

## Not Done

- **Task 49, the usability sessions**, and the screen-reader half of task
  47: they need the deployed host and people who have never used a
  prediction market. The protocol is written and fixed in advance
  (`docs/usability.md`): who, how, ten tasks with success conditions, the
  measures (completion, time to first strategy watched, words that
  confused) and what happens after.
- **Flag F18**: the terms and the privacy notice are drafts until a lawyer
  has read them; public sign-up waits on it.
