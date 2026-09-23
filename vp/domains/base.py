"""The domain adapter contract.

A domain decides membership from three signals available on every market
without extra requests: the event's tag labels, the event title, and the
question. Tags are the most reliable signal because they are assigned by the
venue; keywords catch markets the tags miss; exclusion terms reject markets a
keyword pulls in by accident (the archived project found "Major" matching a
military question, and "Miami" a hockey one). A domain also carries the Gamma
tag ids it can be *listed* by, which is how the catalogue is paged without a
keyword search, and a parser that reads a question into structured fields for
the forecasters. Parsing is best-effort: an unrecognised question is still a
member of the domain, it just has no structured fields.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from vp.domains import props

Parser = Callable[[str, str | None], dict[str, str] | None]


@dataclass(frozen=True)
class Domain:
    """Membership rules and parser for one forecasting domain."""

    name: str
    tag_ids: tuple[str, ...]
    tag_labels: tuple[str, ...]
    keywords: tuple[str, ...]
    exclude: tuple[str, ...]
    parse: Parser
    title: str = ""  # what a person calls it, for the interface
    summary: str = ""  # one plain sentence on what its markets are about
    # The parsed kinds of its main contracts and the fields each carries; a
    # strategy's selector is checked against these (docs/strategies.md).
    kinds: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # The kinds of `vp.domains.props` its match events carry.
    props: tuple[str, ...] = ()
    # Whether a match's first-listed team plays at home (football fixtures),
    # which the rating signals give a home advantage.
    home_first: bool = False
    # Its league's file in openfootball (``en.1``) and the league's time
    # zone, when results come from there (docs/evidence.md).
    openfootball: str = ""
    zone: str = "UTC"

    @property
    def observes(self) -> bool:
        """Whether its markets settle on an observed daily temperature."""
        return "daily_temperature" in self.kinds

    @property
    def all_kinds(self) -> dict[str, tuple[str, ...]]:
        """Every kind a market of this domain can parse to, props included."""
        return {**self.kinds, **{k: props.PROP_KINDS[k] for k in self.props}}

    def read(self, question: str, event_title: str | None) -> dict[str, str] | None:
        """The parsed fields of a member market: a prop form, else the domain's."""
        found = props.parse(question, event_title) if self.props else None
        if found is not None and found["kind"] in self.props:
            return found
        return self.parse(question, event_title)

    def matches(
        self, question: str, event_title: str | None, tags: tuple[str, ...]
    ) -> bool:
        """Whether a market belongs to this domain.

        Exclusion terms are checked first and veto everything; then a tag label
        match or a keyword match in the question or event title admits it.
        All comparisons are case-insensitive substring tests.
        """
        text = f"{question} {event_title or ''}".lower()
        if any(term.lower() in text for term in self.exclude):
            return False
        labels = {t.lower() for t in tags}
        if any(label.lower() in labels for label in self.tag_labels):
            return True
        return any(keyword.lower() in text for keyword in self.keywords)
