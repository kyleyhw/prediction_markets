# Security Policy

## Reporting a vulnerability

Please report it privately, not in a public issue: use **Report a
vulnerability** on the repository's Security tab (GitHub's private
reporting). Say what you found, how to reproduce it, and what it could
reach. We acknowledge a report within a week and say what we will do about
it. Please give us time to fix it before you publish. We credit reporters
who want credit. There is no bounty.

## What matters most

In order:

1. **Tenancy.** One workspace reading or changing another's data, past
   row-level security (`docs/platform.md`, "Tenancy").
2. **Secrets.** Model keys, webhook and bot secrets, session tokens, API
   tokens: anything that reveals or misuses one.
3. **Ledgers and the audit chain.** Changing a record without the chain
   check noticing.
4. **Sign-in.** Magic links, sessions, the cross-site checks.
5. **The read-only surfaces.** The MCP server or the API doing anything
   but read.

Live execution does not exist yet. When it does, its design
(`docs/security.md`) makes the execution service and its keys the first
item on this list.

## Nobody from this project will ever

- ask for a wallet's private key or seed phrase;
- ask you to sign a transaction or message outside the app's own pages;
- send you a link to "verify", "claim" or "unlock" anything;
- contact you first about an account in a chat server, a forum or a
  direct message.

Anyone who does is not us, whatever name or logo they use. The only
channels are this repository and the ones its README names.

## Supported versions

The `master` branch. There are no releases yet.
