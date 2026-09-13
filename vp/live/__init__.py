"""Live-execution safety layer: mandate guard, kill switch, approvals, credentials.

Nothing in this package can sign or send an order. It is the gate the
security design (``docs/security.md``) puts in front of execution, built
so the design can be reviewed with code and tests in hand. The execution
adapter itself (order signing and placement, plan task 23) is not written
until that design is agreed with the user; the invariant is recorded in
``CLAUDE.md``.
"""
