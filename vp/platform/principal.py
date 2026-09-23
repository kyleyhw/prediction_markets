"""Who is calling, and how much that claim is worth.

Every request, job and command carries a `Principal`. It exists so that an
action can be traced to an actor, and its one hard rule is that it must
never manufacture an identity the authentication layer could not establish:
`attributable` is derived from the authentication method at construction
and cannot be passed in, because a caller-settable flag is a
caller-settable lie.

`workspace` is the tenancy boundary. Everything a user owns belongs to a
workspace, `vp.platform.db.tenant_session` sets it on the database
connection, and the row-level security policies of migration 0001 answer
every query against it. A principal with no workspace can therefore read
nothing, which is the fail-closed default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID


class AuthMethod(StrEnum):
    """How a request proved who it was.

    The distinction that matters is not the mechanism but whether it can
    name a person. Both mechanisms below can: a session follows a verified
    email, and a token is minted by a signed-in user and belongs to them.
    Anonymous cannot, and is what an unauthenticated request gets.
    """

    SESSION = "session"
    API_TOKEN = "api_token"
    ANONYMOUS = "anonymous"
    # A background job acting for the person who asked for it, whose id the
    # job row recorded when a session or token enqueued it.
    JOB = "job"
    # The platform's own work (ingest, maintenance), acting for nobody.
    SYSTEM = "system"


#: Methods that name an actual person. Anything else proves only that
#: somebody reached the service.
ATTRIBUTABLE: frozenset[AuthMethod] = frozenset(
    {AuthMethod.SESSION, AuthMethod.API_TOKEN, AuthMethod.JOB}
)


class Role(StrEnum):
    """What a principal may do.

    The first three are held within a workspace. `OPERATOR` is held on the
    platform, not in a workspace: it is the role that reads costs, sets
    budgets and trips the platform halt, and it grants no access to any
    workspace's data.
    """

    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"
    OPERATOR = "operator"


_WRITERS = frozenset({Role.OWNER, Role.EDITOR})
_READERS = frozenset({Role.OWNER, Role.EDITOR, Role.VIEWER})


@dataclass(frozen=True)
class Principal:
    """The actor behind one request, job or command.

    Attributes:
        subject: the actor's identifier. The user's id for an authenticated
            principal; `"anonymous"` otherwise. It is never a display name.
        auth_method: how the claim was established.
        workspace: the workspace this principal is acting in, or None.
        roles: the roles held, within that workspace or on the platform.
        attributable: whether `subject` names a person. Derived from
            `auth_method`; passing it is a `TypeError`.
    """

    subject: str
    auth_method: AuthMethod
    workspace: UUID | None = None
    roles: frozenset[Role] = frozenset()
    attributable: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise ValueError("a principal must have a non-empty subject")
        object.__setattr__(self, "attributable", self.auth_method in ATTRIBUTABLE)

    @classmethod
    def anonymous(cls) -> Principal:
        """The principal of an unauthenticated request: no workspace, no roles."""
        return cls(subject="anonymous", auth_method=AuthMethod.ANONYMOUS)

    @property
    def user_id(self) -> UUID:
        """The subject as a UUID.

        Raises:
            PermissionError: the principal is not attributable, so its
                subject is a label rather than a user.
            ValueError: the subject is not a UUID.
        """
        if not self.attributable:
            raise PermissionError(f"{self.auth_method} names no user")
        return UUID(self.subject)

    @property
    def may_read(self) -> bool:
        """Whether this principal may read its workspace."""
        return self.workspace is not None and bool(self.roles & _READERS)

    @property
    def may_write(self) -> bool:
        """Whether this principal may change its workspace's data."""
        return self.workspace is not None and bool(self.roles & _WRITERS)

    @property
    def may_administer(self) -> bool:
        """Whether this principal may change its workspace's membership."""
        return self.workspace is not None and Role.OWNER in self.roles

    @property
    def is_operator(self) -> bool:
        """Whether this principal holds the platform operator role."""
        return Role.OPERATOR in self.roles
