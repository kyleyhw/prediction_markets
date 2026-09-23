"""Sending sign-in emails.

One interface, `Mailer`, and one implementation today: `OutboxMailer`,
which writes each message to a file under the data root instead of sending
it. It exists so that sign-in works end to end on a development machine
with no mail provider, and it never logs a message body, because the body
of a sign-in email is a credential. Production refuses it (see
`vp.platform.config`); the provider is chosen with the deploy (flag F3).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Message:
    """One email."""

    to: str
    subject: str
    body: str


class Mailer(Protocol):
    """Anything that can deliver a message."""

    def send(self, message: Message) -> None:
        """Deliver the message, or raise."""
        ...


class OutboxMailer:
    """Writes messages to files, and keeps them in memory for tests.

    Args:
        directory: where to write each message as a `.txt` file, or None to
            keep messages in memory only.
    """

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory
        self.sent: list[Message] = []

    def send(self, message: Message) -> None:
        """Record the message, and write it out if a directory is set."""
        self.sent.append(message)
        if self.directory is None:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        safe = re.sub(r"[^a-z0-9@._-]", "_", message.to.lower())
        path = self.directory / f"{stamp}-{safe}.txt"
        path.write_text(
            f"To: {message.to}\nSubject: {message.subject}\n\n{message.body}\n"
        )
        # The path, never the body: the body carries a sign-in link.
        logger.info("mail written to the outbox: %s", path)
