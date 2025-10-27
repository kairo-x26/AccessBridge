from __future__ import annotations

import pytest

from app.domain.rbac import MATRIX, Perm, Role, has_permission
from tests.factories import make_org, make_user


def test_matrix_covers_every_role():
    assert set(MATRIX) == set(Role)


@pytest.mark.parametrize(
    ("role", "perm", "allowed"),
    [
        ("clinician", Perm.REFERRAL_READ, True),
        ("clinician", Perm.ACTION_APPROVE, False),
        ("navigator", Perm.REFERRAL_IMPORT, False),
        ("navigator", Perm.MESSAGE_SEND, True),
        ("security", Perm.REFERRAL_READ, False),
        ("security", Perm.AUDIT_READ, True),
        ("coordinator", Perm.USER_MANAGE, False),
        ("admin", Perm.INTEGRATION_MANAGE, False),
        ("unknown-role", Perm.REFERRAL_READ, False),
    ],
)
def test_permission_matrix(role, perm, allowed):
    assert has_permission(role, perm) is allowed


def test_coordinator_cannot_manage_users(client):
    org = make_org()
    coord = make_user(org, "coordinator")
    assert client.get("/v1/users", headers=coord.headers()).status_code == 403


def test_cross_tenant_user_access_is_not_found(client):
    a = make_org("a-clinic", "A Clinic")
    b = make_org("b-clinic", "B Clinic")
    admin_a = make_user(a, "admin")
    target_b = make_user(b, "coordinator")
    r = client.patch(
        f"/v1/users/{target_b.user_id}", headers=admin_a.headers(), json={"status": "disabled"}
    )
    assert r.status_code == 404
    listed = client.get("/v1/users", headers=admin_a.headers()).json()
    assert target_b.user_id not in {u["id"] for u in listed}


def test_token_with_forged_org_rejected(client):
    a = make_org("a-clinic", "A Clinic")
    b = make_org("b-clinic", "B Clinic")
    admin_a = make_user(a, "admin")
    from app.core.security import create_access_token

    forged = create_access_token(user_id=admin_a.user_id, organization_id=b, role="admin", mfa=True)
    r = client.get("/v1/users", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


def test_audit_log_is_tenant_scoped(client):
    a = make_org("a-clinic", "A Clinic")
    b = make_org("b-clinic", "B Clinic")
    admin_a, sec_a = make_user(a, "admin"), make_user(a, "security")
    admin_b, sec_b = make_user(b, "admin"), make_user(b, "security")
    client.post(
        "/v1/users/invitations",
        headers=admin_a.headers(),
        json={"email": "x@a.org", "role": "navigator"},
    )
    client.post(
        "/v1/users/invitations",
        headers=admin_b.headers(),
        json={"email": "y@b.org", "role": "navigator"},
    )
    items_a = client.get("/v1/audit-events", headers=sec_a.headers()).json()["items"]
    assert items_a and all(i["actor"] != f"user:{admin_b.user_id}" for i in items_a)
    assert client.get("/v1/audit-events", headers=admin_a.headers()).status_code == 200
    assert (
        client.get("/v1/audit-events", headers=make_user(a, "navigator").headers()).status_code
        == 403
    )
    _ = sec_b
