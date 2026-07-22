import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_list_modules(client: AsyncClient) -> None:
    response = await client.get("/api/v1/system/modules")

    assert response.status_code == 200
    data = response.json()
    codes = {module["code"] for module in data}
    assert "production" in codes
    assert "quality" in codes
    assert "registration" in codes
