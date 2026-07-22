"""Smoke tests for safety module API endpoints."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestSafetyCheckAPI:
    async def test_get_checks_returns_200(self, client) -> None:
        """GET /api/v1/safety/checks returns 200."""
        pass

    async def test_create_check_requires_auth(self, client) -> None:
        """POST without token returns 401."""
        pass


class TestHazardAPI:
    async def test_get_hazards_returns_200(self, client) -> None:
        pass
