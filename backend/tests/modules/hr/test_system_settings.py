"""系统设置 KV（GET/PUT /system-settings）：读取、保存、值字符串化。

data-management 系列已有 test_data_management.py 覆盖，此处不重复。
"""

from httpx import AsyncClient

from tests.modules.hr.conftest import _rand


async def test_save_and_read_back(client: AsyncClient):
    """保存后可读回；覆盖保存更新旧值。"""
    key = _rand("设置键")

    initial = await client.get("/api/v1/hr/system-settings")
    assert initial.status_code == 200, initial.text
    assert key not in initial.json()["data"]

    saved = await client.put("/api/v1/hr/system-settings", json={key: "第一版"})
    assert saved.status_code == 200

    read1 = await client.get("/api/v1/hr/system-settings")
    assert read1.json()["data"][key] == "第一版"

    updated = await client.put("/api/v1/hr/system-settings", json={key: "第二版"})
    assert updated.status_code == 200
    read2 = await client.get("/api/v1/hr/system-settings")
    assert read2.json()["data"][key] == "第二版"


async def test_values_are_stringified(client: AsyncClient):
    """非字符串值统一转成字符串存储。"""
    key = _rand("数值键")
    res = await client.put("/api/v1/hr/system-settings", json={key: 12345})
    assert res.status_code == 200
    read = await client.get("/api/v1/hr/system-settings")
    assert read.json()["data"][key] == "12345"


async def test_multiple_keys_batch_save(client: AsyncClient):
    """一次保存多个键值。"""
    k1, k2 = _rand("批量1"), _rand("批量2")
    res = await client.put("/api/v1/hr/system-settings", json={k1: "a", k2: "b"})
    assert res.status_code == 200
    data = (await client.get("/api/v1/hr/system-settings")).json()["data"]
    assert data[k1] == "a"
    assert data[k2] == "b"
