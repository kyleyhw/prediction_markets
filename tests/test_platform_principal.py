"""The principal: derived attribution, and what each role may do."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from vp.platform.principal import AuthMethod, Principal, Role

WORKSPACE = uuid4()
USER = uuid4()


def _principal(role: Role, method: AuthMethod = AuthMethod.SESSION) -> Principal:
    return Principal(
        subject=str(USER),
        auth_method=method,
        workspace=WORKSPACE,
        roles=frozenset({role}),
    )


def test_attribution_is_derived_and_cannot_be_passed() -> None:
    """A caller-settable flag would be a caller-settable lie."""
    with pytest.raises(TypeError):
        Principal(
            subject=str(USER),
            auth_method=AuthMethod.ANONYMOUS,
            attributable=True,  # ty: ignore[unknown-argument]
        )
    assert _principal(Role.VIEWER).attributable is True
    assert Principal.anonymous().attributable is False


def test_both_authenticated_methods_name_a_person() -> None:
    for method in (AuthMethod.SESSION, AuthMethod.API_TOKEN):
        assert _principal(Role.VIEWER, method).attributable is True


def test_anonymous_has_no_workspace_no_roles_and_no_user() -> None:
    anon = Principal.anonymous()
    assert anon.workspace is None
    assert anon.roles == frozenset()
    assert anon.may_read is False
    assert anon.may_write is False
    with pytest.raises(PermissionError):
        _ = anon.user_id


def test_user_id_is_the_subject_as_a_uuid() -> None:
    assert _principal(Role.OWNER).user_id == UUID(str(USER))


def test_what_each_role_may_do() -> None:
    owner, editor, viewer = (
        _principal(r) for r in (Role.OWNER, Role.EDITOR, Role.VIEWER)
    )
    assert [p.may_read for p in (owner, editor, viewer)] == [True, True, True]
    assert [p.may_write for p in (owner, editor, viewer)] == [True, True, False]
    assert [p.may_administer for p in (owner, editor, viewer)] == [
        True,
        False,
        False,
    ]


def test_a_role_without_a_workspace_grants_nothing() -> None:
    """Roles are held within a workspace; there is no ambient authority."""
    stray = Principal(
        subject=str(USER),
        auth_method=AuthMethod.SESSION,
        roles=frozenset({Role.OWNER}),
    )
    assert stray.workspace is None
    assert stray.may_read is False
    assert stray.may_write is False
    assert stray.may_administer is False


def test_the_operator_role_reaches_no_workspace_data() -> None:
    operator = Principal(
        subject=str(USER),
        auth_method=AuthMethod.SESSION,
        roles=frozenset({Role.OPERATOR}),
    )
    assert operator.is_operator is True
    assert operator.may_read is False
    assert operator.may_write is False


def test_a_subject_must_say_something() -> None:
    with pytest.raises(ValueError):
        Principal(subject="  ", auth_method=AuthMethod.SESSION)
