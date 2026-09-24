# The Documentation Site

Design page for Phase 23 of the plan: a public site as detailed and as
useful as the reference implementation's wiki, built from this repository's
`docs/` and the app's own manifests, in a visual style of our own. This page
fixes the structure, the build rules and the default visual style. The style
is a placeholder chosen so the site can be built now; alternatives are
trialled later behind the same design tokens.

## 1. What the Site Is For

One text serves everyone. The developer reads `docs/architecture.md` in the
repository; the user reads the same page rendered on the site; the research
session agent quotes the same glossary; another agent reads the same page as
markdown through `llms.txt`. The site therefore never has content of its
own: every page has a source file in the repository, a last-verified date,
and, where it shows a number, the command that reproduces it.

## 2. Structure

| Section | Contents | Source |
| :--- | :--- | :--- |
| Home | What it is in one paragraph, one honest example with its run card, "open the app" for everyone and "install" for developers, the boundary statement (a tool, not advice; paper first; live gated) | `README.md`, a fixed example run |
| Docs | Versioned by release, searchable client-side, an "on this page" outline. Getting started; core concepts (a contract, a price as a forecast, the cutoff, proper scores, skill, Kelly, fees); the strategy spec; forecasters, signals and committees; the evidence archive; paper trading; security; reference (CLI, API from the OpenAPI document, MCP tools, glossary, run card fields, the ledger format) | `docs/*.md`, OpenAPI, registry manifests |
| Tutorials | Hands-on, for someone with no finance or programming background; a day-by-day learning route from "watch one market" to "describe a strategy in a sentence" to "read your own record" | `docs/tutorials/*.md` |
| Signals | The library: formula, references, gates passed, live bench per signal, one page per signal generated from the registry | the signal registry manifest and bench results |
| Research Lab | Long-form studies whose every number is one command away; a caveats section as long as the findings | `docs/lab/*.md` with their commands |
| Learn | The in-app plain-language pages, published here too | `vp/ui/static` learn content |
| Changelog and reports | Release notes and the phase reports | `CHANGELOG.md`, `tests/reports/*.md` |

## 3. Build Rules

- A small generator, run in CI, turns markdown and manifests into static
  HTML: no framework, no bundler, the same "no toolchain to install" rule as
  the app. Content authors write markdown and nothing else.
- Math is rendered; code blocks keep the mono font; tables get sticky
  headers; every heading is linkable; every page shows its source path and
  last-verified date.
- Search is client-side over a generated index; versions are directories
  (`/docs/0.2/...`) with `latest` as an alias.
- `llms.txt` at the root and a `.md` twin of every page, so agents read
  the site as markdown.
- A CI check runs every fenced command a page marks as reproducible and
  fails on a page whose commands no longer run or whose numbers changed.
- Analytics, if any, is an anonymous first-party counter: no cookies, no
  per-visitor identifier, no IP retention.
- Nothing from the reference implementation's wiki is reused: no asset,
  layout, copy or colour (`vibe_trading.md` § 9).

## 4. The Default Visual Style: "Paper"

The app already has a visual language (`ui.md`): Instrument Sans for text,
JetBrains Mono for numbers and identifiers, an 8 px spacing scale, a fixed
colour slot per forecaster, both themes, charts drawn inline. The site
extends it rather than inventing a second one. The character is a printed
working paper: quiet, dense where the content is dense, with the numbers
always in the mono face.

**Tokens** (one file, `site/tokens.css`, shared with the app where the names
coincide):

| Token | Light | Dark | Use |
| :--- | :--- | :--- | :--- |
| `--bg` | `#FAF8F3` warm off-white | `#121316` near-black | page |
| `--panel` | `#F2EFE7` | `#1A1B1F` | code blocks, tables' header row, asides |
| `--ink` | `#1B1B1F` | `#E8E6DF` | text |
| `--muted` | `#5C5B57` | `#A3A198` | captions, metadata, secondary labels |
| `--rule` | `#E4E0D6` | `#2A2B30` | hairlines |
| `--accent` | `#0F6E63` teal | `#4FB3A6` | links, focus rings, the active nav item, one accent only |
| `--positive`, `--negative` | the app's status colours | same | positive and negative skill and returns, nothing else |
| forecaster slots | as in the app | same | series in charts |

**Type.** Instrument Sans at 16 px with a 1.55 line height for text;
headings in the same face at 600 weight with slightly tightened tracking;
JetBrains Mono at 0.92 em for numbers, identifiers, commands and axis ticks,
with tabular figures in columns; no other faces; both fonts vendored as the
app already does.

**Layout.** A left sidebar of section navigation on wide screens that
collapses to a top bar on narrow ones; a content column with a measure of
68 characters and a wider grid for tables and charts; an "on this page"
outline on the right above 1,280 px; 16 px side gutters on phones and no
horizontal scroll.

**Elements.** Hairline rules instead of boxes; asides as a left rule in the
accent colour, not a coloured box; tables with sticky header rows and hover
rows; code blocks on the panel colour with a copy button; callouts of three
kinds only (note, caution, reproduce); no hero images, no illustrations, no
gradients; charts as inline SVG in the theme's colours with a legend and a
table beside each, as in the app.

**Motion and state.** No animation except a 120 ms colour transition on
hover and focus; a visible focus ring in the accent; theme follows the
system with a remembered override; every interactive element keyboard
reachable; contrast at WCAG 2.2 AA in both themes.

**Why this default.** It is the style the app already has, so a user moving
between the app and the site sees one product; it needs no imagery and no
brand work to start; its tokens are few enough to swap wholesale when an
alternative is trialled.

## 5. Alternatives to Trial Later

Each is a different `tokens.css` and, at most, a different sidebar
treatment; the generator and the content do not change.

| Name | Character | What changes |
| :--- | :--- | :--- |
| Terminal | dark-first, mono-forward, dense | mono for headings too, a cooler dark palette, a green accent, boxed panels |
| Journal | editorial, serif headings, generous | a serif display face for headings, wider margins, drop rules, a warm red accent |
| Product | brighter, card-based, marketing-friendly | cards with soft shadows, a blue accent, a hero band on Home only |

A trial is a branch of the tokens file shown to at least three people from
the Phase 14 usability sessions; the decision is recorded here.

## 6. What Is Measured

Search quality on a fixed query set; the reproduction check passing on
every Research Lab page; page weight under 200 KB before fonts; contrast and
keyboard audits in both themes; visitor counts if counted. Reported in
`tests/reports/phase23_site.md`.

## 7. As Built (2026-09-24)

`vp site [--out data/site]` builds the site; CI builds it on every push and
keeps it as an artifact (`site` job). The generator is `vp/docsite/`: about
1,000 lines of Python and 220 of CSS and script, with markdown-it for the
markdown and latex2mathml for the math.
Both are development dependencies.

- **Sources:**
  - every `docs/*.md` (grouped by `DOC_GROUPS` in `vp/docsite/pages.py`,
    with any page missing from it under "More");
  - the README (as Home's opening and as the Overview);
  - `CONTRIBUTING.md`, `SECURITY.md`, the phase reports;
  - generated pages: the CLI reference from the parser `vp` runs
    (`build_parser`), the web API from the service's OpenAPI document,
    the MCP tools from the server's source, one page per signal from the
    registry's manifest, the app's glossary and Learn topics from
    `en.json`, and the roadmap from the plan's status tags.
- **Links:** a link to another source becomes a relative link to its page.
  A link to code becomes a link to the file on GitHub.
- **Pages:** every page is a directory with `index.html` and `index.md`
  (the markdown twin); `llms.txt` lists the twins. Every page names its
  source and the date of the source's last commit.
- **Math** is MathML, which browsers draw natively: no script, no font.
  A dollar sign followed by a digit is money, not math.
- **Search** runs in the page over `search.json`, one entry per section.
  The title counts most, then the section's heading, then word frequency,
  with a light stem. A result opens at the section that matched. The index
  loads on first use, so it does not count against page weight.
- **The build fails** on:
  - a broken link or anchor;
  - a `docs/` page not published;
  - a `vp` command in a code block that no longer parses;
  - a command named in the text whose command names or flags no longer
    exist.
- **No visitor counter.** Counting is left out rather than made anonymous
  later; the site sets no cookie and stores nothing but the theme choice
  in the browser.

Not yet:

- **Versions,** which wait on a first release. Until then there is one
  version, `master`.
- **The tutorials route** (task 120), to be written with the usability
  sessions (Phase 14, task 49). The Learn pages stand in for now.
- **The Research Lab studies** (task 123), which need rebuilt datasets
  and, for committees, the API key.
- **Publishing,** which is decided with the deploy (F16). The artifact is
  a folder any static host serves.
