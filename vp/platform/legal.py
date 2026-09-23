"""The terms of use and the privacy notice (plan, task 48).

Both are drafts written from what the platform does, for a lawyer to review
before anyone outside the project signs in (plan, flag F18). They are kept
here, versioned, so the page shows exactly the version a person accepted
and a change of wording asks everyone again. Every claim in them is a fact
about this code; where a fact belongs to the deploy (the host's region,
backup retention), the text says so rather than guess.
"""

from __future__ import annotations

import html

#: Bump when either text changes in substance; people are asked again.
TERMS_VERSION = "2026-09-23"

#: The minimum age to use the service.
MINIMUM_AGE = 18

#: The first-screen statement, shown on sign-in and in the app.
STATEMENT = (
    "vibe-predict is a tool for building and testing forecasting strategies "
    "with play money. It is not financial advice, it places no real orders, "
    "and nothing on it is a recommendation to bet."
)

#: What the service is and is not allowed to be, wherever the person is.
JURISDICTION = (
    "Everything here uses play money against real market prices. The service "
    "is not offered where using it would break local law, and real-money "
    "trading, if it is ever added, will be offered only where the venue and "
    "the law allow it."
)

DRAFT = (
    "Draft of 23 September 2026, to be reviewed by a lawyer before the "
    "service is opened to the public."
)

Section = tuple[str, list[str]]

TERMS: list[Section] = [
    (
        "What this is",
        [
            STATEMENT,
            "Prices and markets come from Polymarket, a prediction market. "
            "vibe-predict reads them; it is not Polymarket and is not endorsed "
            "by it.",
        ],
    ),
    ("Where you may use it", [JURISDICTION]),
    (
        "Who may use it",
        [
            f"You must be {MINIMUM_AGE} or older. By signing in you confirm "
            "that you are, and that using the service is lawful where you are.",
        ],
    ),
    (
        "Play money, and no advice",
        [
            "Balances, positions and profits are simulated. They are not "
            "money and cannot be withdrawn. Backtests show what a strategy "
            "would have done on markets that have already settled; they do not "
            "predict what it will do. Nothing the service shows, including "
            "anything its AI assistant says, is advice about real bets or "
            "investments.",
        ],
    ),
    (
        "Using it fairly",
        [
            "Do not try to reach other people's data, overload the service, "
            "get around its limits or budgets, or use it to break the terms of "
            "the market data's source. We may pause or close an account that "
            "does.",
        ],
    ),
    (
        "Costs",
        [
            "Strategies that use an AI model cost money to run. The service "
            "shows the estimated cost before a run starts and stops at your "
            "monthly budget. If you add your own model key, its use is billed "
            "to you by its provider.",
        ],
    ),
    (
        "No guarantee",
        [
            "The service is provided as it is, may be wrong or unavailable, "
            "and may change. To the extent the law allows, we are not liable "
            "for any loss from relying on it.",
        ],
    ),
    (
        "Ending",
        [
            "You may delete your account at any time from Settings, which "
            "deletes your data as the privacy notice describes.",
        ],
    ),
    (
        "Changes",
        [
            "If these terms change, you will be asked to accept the new "
            "version before you carry on.",
        ],
    ),
]

PRIVACY: list[Section] = [
    (
        "What we keep",
        [
            "Your email address, to send sign-in links; your settings; your "
            "sessions and API tokens (stored only as hashes); your workspace's "
            "strategies, backtests, paper trading records and forecasts; its "
            "model spending; and, if you add one, your model key, encrypted "
            "and shown only by its last four characters.",
            "When you accepted these terms and confirmed your age.",
            "Request logs, without sign-in tokens, and metrics that name no person.",
        ],
    ),
    (
        "What we do not do",
        [
            "We do not sell or share your data, show advertising, or use your "
            "strategies or prompts to train models. A strategy's prompt is "
            "sent to the AI model provider only to run it.",
        ],
    ),
    (
        "Who else handles it",
        [
            "The hosting provider and its region, the email provider that "
            "sends sign-in links, and the AI model provider. They are named "
            "here when the service is deployed.",
        ],
    ),
    (
        "How long",
        [
            "Until you delete your account. Sessions expire after 30 days, "
            "sign-in links after 15 minutes, and completed jobs are removed "
            "after 90 days. Old months of paper-trading records move to "
            "archive storage and are deleted with your account. Copies in "
            "backups expire with the backups, whose retention is stated here "
            "when the service is deployed.",
        ],
    ),
    (
        "Your data is yours",
        [
            "Settings, in Detailed, downloads every record the service holds "
            "for you as one file, and your paper-trading ledger as a file you "
            "can check yourself. Settings also deletes your account: your "
            "workspace and everything in it (if you are its only member), "
            "your settings, sessions, tokens and email address, at once and "
            "for good. The operator's own log keeps only the random "
            "identifiers of your account and workspace, not your address.",
        ],
    ),
]


def render(title: str, sections: list[Section]) -> str:
    """A text as the body of a server page."""
    parts = [
        f"<h1>{html.escape(title)}</h1>",
        f"<p class=note>{html.escape(DRAFT)}</p>",
    ]
    for heading, paragraphs in sections:
        parts.append(f"<h2>{html.escape(heading)}</h2>")
        parts += [f"<p>{html.escape(p)}</p>" for p in paragraphs]
    parts.append(
        f"<p class=note>Version {TERMS_VERSION}. "
        '<a href="/terms">Terms of use</a> · <a href="/privacy">Privacy</a> · '
        '<a href="/">Back</a></p>'
    )
    return "".join(parts)
