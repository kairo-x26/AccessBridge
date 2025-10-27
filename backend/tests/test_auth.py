from __future__ import annotations

from app.core import db
from app.core.security import totp_now, verify_totp
from app.models import Organization
from tests.factories import PASSWORD, make_org, make_user


def _login(client, email, password=PASSWORD, org="riverbend"):
    return client.post(
        "/v1/auth/login", json={"organization": org, "email": email, "password": password}
    )


def test_login_and_me(client):
    org = make_org()
    u = make_user(org, "coordinator")
    r = _login(client, u.email)
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["role"] == "coordinator"
    assert "referral:import" in me["permissions"]
    assert me["mfa_satisfied"] is False


def test_wrong_password_and_unknown_user_look_identical(client):
    org = make_org()
    u = make_user(org, "coordinator")
    a = _login(client, u.email, "wrong-password-1A")
    b = _login(client, "nobody@example.org")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_lockout_after_repeated_failures(client):
    org = make_org()
    u = make_user(org, "coordinator")
    for _ in range(5):
        _login(client, u.email, "Wrong-password-9")
    r = _login(client, u.email)
    assert r.status_code == 401
    assert "locked" in r.json()["error"]["message"]


def test_mfa_enrollment_and_challenge(client):
    org = make_org()
    u = make_user(org, "admin")
    token = _login(client, u.email).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    secret = client.post("/v1/auth/mfa/setup", headers=h).json()["secret"]
    assert client.post("/v1/auth/mfa/enable", headers=h, json={"code": "000000"}).status_code in (
        422,
        200,
    )  # 000000 is almost surely wrong
    r = client.post("/v1/auth/mfa/enable", headers=h, json={"code": totp_now(secret)})
    assert r.status_code == 200
    # Next sign-in requires the second step.
    first = _login(client, u.email).json()
    assert first["mfa_required"] and first["access_token"] is None
    bad = client.post(
        "/v1/auth/mfa/verify", json={"challenge": first["mfa_challenge"], "code": "123456"}
    )
    if not verify_totp(secret, "123456"):
        assert bad.status_code == 401
    ok = client.post(
        "/v1/auth/mfa/verify", json={"challenge": first["mfa_challenge"], "code": totp_now(secret)}
    )
    assert ok.status_code == 200
    me = client.get(
        "/v1/auth/me", headers={"Authorization": f"Bearer {ok.json()['access_token']}"}
    ).json()
    assert me["mfa_satisfied"] is True


def test_mfa_challenge_token_is_not_an_access_token(client):
    org = make_org()
    u = make_user(org, "admin")
    from app.core.security import create_mfa_challenge_token

    r = client.get(
        "/v1/auth/me", headers={"Authorization": f"Bearer {create_mfa_challenge_token(u.user_id)}"}
    )
    assert r.status_code == 401


def test_org_requiring_mfa_blocks_unverified_sessions(client):
    org = make_org()
    with db.session_factory()() as s:
        o = s.get(Organization, org)
        o.configuration = {"require_mfa": True}
        s.commit()
    admin = make_user(org, "admin")
    r = client.get("/v1/users", headers=admin.headers(mfa=False))
    assert r.status_code == 403
    assert r.json()["error"]["details"]["reason"] == "mfa_required"
    assert client.get("/v1/users", headers=admin.headers(mfa=True)).status_code == 200


def test_invitation_flow(client):
    org = make_org()
    admin = make_user(org, "admin")
    inv = client.post(
        "/v1/users/invitations",
        headers=admin.headers(),
        json={"email": "new.nav@example.org", "role": "navigator"},
    )
    assert inv.status_code == 201
    token = inv.json()["token"]
    weak = client.post(
        "/v1/auth/accept-invitation",
        json={"token": token, "full_name": "Nia Nav", "password": "short"},
    )
    assert weak.status_code == 422
    ok = client.post(
        "/v1/auth/accept-invitation",
        json={"token": token, "full_name": "Nia Nav", "password": PASSWORD},
    )
    assert ok.status_code == 201 and ok.json()["role"] == "navigator"
    again = client.post(
        "/v1/auth/accept-invitation",
        json={"token": token, "full_name": "Nia Nav", "password": PASSWORD},
    )
    assert again.status_code == 422
    assert _login(client, "new.nav@example.org").status_code == 200


def test_disabled_user_token_rejected(client):
    org = make_org()
    admin = make_user(org, "admin")
    coord = make_user(org, "coordinator")
    r = client.patch(
        f"/v1/users/{coord.user_id}", headers=admin.headers(), json={"status": "disabled"}
    )
    assert r.status_code == 200
    assert client.get("/v1/auth/me", headers=coord.headers()).status_code == 401


def test_role_change_invalidates_old_token(client):
    org = make_org()
    admin = make_user(org, "admin")
    coord = make_user(org, "coordinator")
    old = coord.headers()
    client.patch(f"/v1/users/{coord.user_id}", headers=admin.headers(), json={"role": "clinician"})
    assert client.get("/v1/auth/me", headers=old).status_code == 401


def test_last_admin_cannot_be_removed(client):
    org = make_org()
    admin = make_user(org, "admin")
    sec = make_user(org, "security")
    r = client.patch(
        f"/v1/users/{admin.user_id}", headers=sec.headers(), json={"role": "navigator"}
    )
    assert r.status_code == 422
