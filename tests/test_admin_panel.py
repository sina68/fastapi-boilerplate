from __future__ import annotations

from helpers import EMAIL, PASSWORD, promote_to_admin


async def test_admin_panel_redirects_anonymous_users(client):
    response = await client.get("/admin/", follow_redirects=False)
    assert response.status_code == 302
    assert "/admin/login" in response.headers["location"]


async def test_admin_login_page_renders(client):
    response = await client.get("/admin/login")
    assert response.status_code == 200
    assert 'name="password"' in response.text


async def test_admin_login_rejects_regular_user(client, headers):
    response = await client.post(
        "/admin/login",
        data={"username": EMAIL, "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 400
    # Still anonymous afterwards.
    assert (await client.get("/admin/", follow_redirects=False)).status_code == 302


async def test_admin_login_rejects_wrong_password(client, headers, session_maker):
    await promote_to_admin(session_maker)
    response = await client.post(
        "/admin/login",
        data={"username": EMAIL, "password": "wrong-password-value"},
        follow_redirects=False,
    )
    assert response.status_code == 400


async def test_admin_logs_in_and_out(client, headers, session_maker):
    await promote_to_admin(session_maker)

    logged_in = await client.post(
        "/admin/login",
        data={"username": EMAIL, "password": PASSWORD},
        follow_redirects=False,
    )
    assert logged_in.status_code == 302

    index = await client.get("/admin/")
    assert index.status_code == 200
    # Dashboard renders the registered model views, not the login form.
    assert "Users" in index.text
    assert 'name="password"' not in index.text

    logged_out = await client.get("/admin/logout", follow_redirects=False)
    assert logged_out.status_code == 302
    assert (await client.get("/admin/", follow_redirects=False)).status_code == 302


async def test_admin_session_cookie_has_a_bounded_lifetime(client, headers, session_maker):
    from app.core.config import settings as app_settings

    await promote_to_admin(session_maker)
    response = await client.post(
        "/admin/login",
        data={"username": EMAIL, "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 302
    cookie = response.headers["set-cookie"].lower()
    assert f"max-age={app_settings.ADMIN_SESSION_MAX_AGE_SECONDS}" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


async def test_admin_login_form_is_rate_limited(client, headers, session_maker):
    """The form checks passwords too, so it gets its own per-IP budget."""
    from app.core.config import settings as app_settings

    await promote_to_admin(session_maker)
    limit = app_settings.ADMIN_LOGIN_RATE_LIMIT_PER_MINUTE
    codes = []
    for _ in range(limit + 1):
        response = await client.post(
            "/admin/login",
            data={"username": EMAIL, "password": "wrong-password-value"},
            follow_redirects=False,
        )
        codes.append(response.status_code)
    assert codes[:limit] == [400] * limit
    assert codes[limit] == 429
    blocked = await client.post(
        "/admin/login",
        data={"username": EMAIL, "password": PASSWORD},
        follow_redirects=False,
    )
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "rate_limited"
    assert "Retry-After" in blocked.headers


async def test_admin_session_dies_when_role_is_removed(client, headers, session_maker):
    from app.core.roles import Role
    from app.repositories import user as user_repo

    await promote_to_admin(session_maker)
    await client.post(
        "/admin/login",
        data={"username": EMAIL, "password": PASSWORD},
        follow_redirects=False,
    )
    assert (await client.get("/admin/")).status_code == 200

    async with session_maker() as session:
        user = await user_repo.get_by_email(session, EMAIL)
        user.role = Role.USER.value
        await session.commit()

    assert (await client.get("/admin/", follow_redirects=False)).status_code == 302
