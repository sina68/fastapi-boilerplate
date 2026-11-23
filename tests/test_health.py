from __future__ import annotations

from sqlalchemy.exc import OperationalError

from app.api.deps import SessionDep
from app.db.session import get_session


async def test_liveness_returns_ok(client):
    response = await client.get("/health/liveness")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_returns_ok(client):
    response = await client.get("/health/readiness")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_reports_503_when_db_is_down(client, test_app):
    class BrokenSession:
        async def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    async def broken_session() -> SessionDep:
        yield BrokenSession()  # type: ignore[misc]

    test_app.dependency_overrides[get_session] = broken_session
    response = await client.get("/health/readiness")
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "database_unavailable"


async def test_root_reports_service_name(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
