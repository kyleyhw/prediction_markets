# Phase 23 Test Report: The Documentation Site

Date: 2026-09-24. Environment: Python 3.14.7 via `uv 0.12.18`, Chromium
with axe-core through Playwright, and the site served by a static file
server on the development container.

## Purpose

The goal is one text for everyone. The site is built from the files a
developer already reads (`docs/`, the reports, the README) and from the
manifests the code already keeps, so it has no content of its own that
could drift. Every page names its source and the date that source last
changed. Agents read the same pages as markdown. The design was
`docs/site.md`, and its "As built" section records what was done.

## Static Checks and Tests

| Check | Result | Runtime |
| :--- | :--- | ---: |
| `ruff check .`, `ruff format --check .` | passed | < 1 s |
| `ty check` | passed, 0 diagnostics | 1 s |
| `pre-commit run --all-files` | all hooks passed | 3 s |
| `pytest -q` | 357 passed (354 before the phase) | 32 s |
| `vp site` | 74 pages and a search page, 2.4 MB, no problems | 2 s |

`tests/test_docsite.py`:

- the whole site builds with no problem;
- every `docs/` page is published with its markdown twin;
- the references, roadmap and signals exist;
- the sizing page has MathML;
- `llms.txt` lists the twins;
- no page loads anything from another host;
- a stale command is caught (a misspelt flag in a code block, an unknown
  command and an unknown flag named in the text);
- a broken link and a missing anchor are caught.

The name gate now skips `data/`, where the built site lives, because the
site publishes the provenance pages that are allowed to name the reference
project.

## What the Site Holds

| Section | Pages | From |
| :--- | ---: | :--- |
| Home | 1 | the README's opening, the boundary statement, where to go |
| Docs | 29 | every `docs/*.md` in four groups, the README as the overview, `CONTRIBUTING.md`, `SECURITY.md` |
| Learn | 7 | the app's Learn topics, both reading levels, from `en.json` |
| Signals | 14 | one page per registered signal from the registry's manifest, and the list |
| Reference | 5 | the CLI from the parser `vp` runs; 77 web routes from the OpenAPI document; the seven MCP tools from the server's source; the app's glossary (43 terms) |
| Reports | 17 | every phase report including this one, in phase order |
| Roadmap | 1 | every task of the plan with its status tag |

Also generated: `llms.txt`, a markdown twin of every page, and
`search.json`.

## Measured

| What | Result | Budget |
| :--- | :--- | :--- |
| Accessibility, axe-core at WCAG 2.2 AA | **0 violations** on 26 page states: 13 pages in each theme (home, docs index, sizing with math, security, a Learn topic, signals and one signal, CLI, API, glossary, a report, the roadmap, search results) | 0 |
| Horizontal scroll at 375 px | none on any of the 13 pages | none |
| Page weight | median 11.8 KB of HTML, largest 48 KB (the platform page), plus 12 KB of CSS and script | 200 KB before fonts |
| Fonts | 60 KB, the app's two vendored faces | |
| Search index | 570 KB, loaded on first search only | |
| Math | 40 formulas on the sizing page as MathML, no script | |

**Search quality.** Fifteen questions, each with the page a reader would
want. The questions were fixed before the first run.

- **First run:** 12 of 15 had the page in the first three.
- **Fixed:** the index kept only each page's first 6,000 characters, so
  the runbook's restore entry and the later sections of long pages were
  never searched. It is now one entry a section, and a result opens at
  that section. A light stem was added: "strategy" did not find
  "Strategies from Conversation".
- **Now:** 13 of 15; 10 at the top.

The two misses:

| Question | Wanted | First result | Why |
| :--- | :--- | :--- | :--- |
| cutoff evidence | Forecasters (5th) | Signals, then the Evidence Archive | the evidence page is about exactly this, so the expectation was arguable |
| magic link sign-in | The Platform (absent) | Product Design | `docs/platform.md` never says "magic"; the product page, which does, came first. The expectation was wrong. |

## Found and Fixed

| Fault | Fix |
| :--- | :--- |
| README links resolved from the wrong place on the Overview page, 38 broken links | Pages register by their source file; Home quotes the README, and the README's own page is the Overview |
| Relative links from nested pages lost their trailing slash (`../..site.css`) | Every page is a directory, so a link climbs one step a segment |
| Two wide formulas scrolled but could not be reached by keyboard (axe: scrollable-region-focusable) | Formulas and tables that scroll are focusable groups |
| Wide tables were squeezed into the 68-character text column | The measure applies to text only |
| On a phone the whole sub-navigation came before the text | Phones show the sections only; each section's first page lists its pages |
| Search missed everything after a page's first 6,000 characters | One index entry a section |
| `vp --version` was reported as a broken command (it exits 0) | Exit code 0 is success |
| Commands named in the text without their arguments were all "broken" | The text is checked for command names and flags; code blocks must parse whole |

## Not Done

- **The Research Lab studies (task 123).** They need the datasets rebuilt
  (`data/` is empty in a fresh session) and, for committees, the API key.
  No study is published without its command.
- **Tutorials:** the day-by-day route is to be written with the
  usability sessions (Phase 14, task 49). The Learn pages stand in.
- **Versions** wait on a first release, and so does a changelog. The
  reports serve until then.
- **Community channels (task 126)** are a proposal: GitHub Discussions,
  with the impostor warning already in `SECURITY.md`.
- **Publishing** is decided with the deploy (F16). CI keeps each build as
  an artifact.
- **No visitor counts:** nothing is counted.
