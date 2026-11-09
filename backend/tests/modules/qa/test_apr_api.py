"""QA 年度产品审核（APR）API 测试：配置/录入/锁定/趋势/汇总/导出。

沿用 test_deviation_api 的模式：手工覆盖 get_db / get_current_user 并
patch 权限集合，整条用例共用一个最终回滚的会话。产品短码加随机前缀，
避免与共享开发库里的既有数据冲突。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.main import app as fastapi_app
from app.platform.identity.deps import get_current_user
from app.platform.identity.models import User
from tests.conftest import _test_session_factory

READ = {"qa:apr:read"}
WILDCARD_READ = {"qa:*:read"}
MANAGE = READ | {"qa:apr:manage"}
ENTER = READ | {"qa:apr:enter"}
LOCK = READ | {"qa:apr:lock"}
EXPORT = READ | {"qa:apr:export"}


async def _ensure_test_user(session: AsyncSession) -> User:
    stmt = select(User).where(User.is_deleted == False).limit(1)  # noqa: E712
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing
    user = User(name="qa-apr测试用户", employee_no="QA-APR-TEST-001")
    session.add(user)
    await session.flush()
    return user


@asynccontextmanager
async def _client(
    perms: set[str] | None,
) -> AsyncGenerator[tuple[AsyncClient, AsyncSession], None]:
    """perms=None 表示匿名；否则以测试用户登录并授予给定权限码。"""
    async with _test_session_factory() as session:
        user = await _ensure_test_user(session)

        async def _override_get_db() -> Any:
            yield session

        async def _override_user() -> Any:
            return user

        async def _perms(user_id: str, db: object) -> set[str]:
            return set(perms or ())

        fastapi_app.dependency_overrides[get_db] = _override_get_db
        if perms is not None:
            fastapi_app.dependency_overrides[get_current_user] = _override_user
        try:
            with patch("app.platform.permission.deps.get_user_permissions", new=_perms):
                transport = ASGITransport(app=fastapi_app)
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as ac:
                    yield ac, session
        finally:
            fastapi_app.dependency_overrides.clear()
            await session.rollback()


def _code(prefix: str = "T") -> str:
    return f"{prefix}{uuid4().hex[:8].upper()}"


async def _mk_product(ac: AsyncClient, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": _code(),
        "name": "达托霉素",
        "name_en": "Daptomycin",
    }
    payload.update(overrides)
    # 产品名称唯一：追加随机后缀，避免同一用例/共享开发库内既有产品重名。
    payload["name"] = f"{payload['name']}{uuid4().hex[:6]}"
    resp = await ac.post("/api/v1/qa/apr/products", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def _mk_section(
    ac: AsyncClient, product_id: str, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "product_id": product_id,
        "name": "成品检验-USP",
        "data_kind": "inspection",
        "market": "US",
        "stage": "finished_test",
    }
    payload.update(overrides)
    resp = await ac.post("/api/v1/qa/apr/sections", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def _mk_item(
    ac: AsyncClient, section_id: str, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "section_id": section_id,
        "category": "test",
        "name_cn": "酸碱度",
        "value_type": "number",
        "spec_text": "4.0-4.6",
        "spec_min": 4.0,
        "spec_max": 4.6,
        "oot_min": 4.2,
        "oot_max": 4.5,
    }
    payload.update(overrides)
    resp = await ac.post("/api/v1/qa/apr/items", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def _mk_batch(
    ac: AsyncClient, section_id: str, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "section_id": section_id,
        "year": 2025,
        "batch_no": _code("B"),
    }
    payload.update(overrides)
    resp = await ac.post("/api/v1/qa/apr/batches", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


# ───────────────────────── 鉴权 ─────────────────────────


async def test_read_requires_permission() -> None:
    """匿名与无权限用户访问产品列表被拒。"""
    async with _client(None) as (ac, _):
        resp = await ac.get("/api/v1/qa/apr/products")
        assert resp.status_code in (401, 403)
    async with _client({"qa:document:create"}) as (ac, _):
        resp = await ac.get("/api/v1/qa/apr/products")
        assert resp.status_code == 403


async def test_wildcard_read_grants_list() -> None:
    """模块通配读码 qa:*:read 放行 APR 读取。"""
    async with _client(WILDCARD_READ) as (ac, _):
        resp = await ac.get("/api/v1/qa/apr/products")
        assert resp.status_code == 200
        assert "data" in resp.json()


async def test_write_codes_imply_read() -> None:
    """enter/manage 写权限隐含 APR 读取（否则按码配权会菜单可见但整页 403）。"""
    async with _client({"qa:apr:enter"}) as (ac, _):
        resp = await ac.get("/api/v1/qa/apr/products")
        assert resp.status_code == 200
    async with _client({"qa:apr:manage"}) as (ac, _):
        resp = await ac.get("/api/v1/qa/apr/products")
        assert resp.status_code == 200


async def test_write_requires_dedicated_permission() -> None:
    """只有读码不能创建产品。"""
    async with _client(READ) as (ac, _):
        resp = await ac.post(
            "/api/v1/qa/apr/products", json={"code": _code(), "name": "X"}
        )
        assert resp.status_code == 403


# ───────────────────────── 产品与模板 ─────────────────────────


async def test_product_crud_and_code_conflict() -> None:
    """产品创建/更新/删除全流程；短码重复 409。"""
    async with _client(MANAGE) as (ac, _):
        created = await _mk_product(ac)
        assert created["code"]
        # 同码拒绝（名称不同，命中短码唯一）
        resp = await ac.post(
            "/api/v1/qa/apr/products",
            json={"code": created["code"], "name": f"另一个{uuid4().hex[:6]}"},
        )
        assert resp.status_code == 409
        assert "短码" in resp.json()["message"]
        # 更新
        new_name = f"新名称{uuid4().hex[:6]}"
        resp = await ac.patch(
            f"/api/v1/qa/apr/products/{created['id']}", json={"name": new_name}
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == new_name
        # 无段可删
        resp = await ac.delete(f"/api/v1/qa/apr/products/{created['id']}")
        assert resp.status_code == 200


async def test_product_name_conflict() -> None:
    """产品名称唯一：新增撞名与改名撞名均 409，名称不变则放行。"""
    async with _client(MANAGE) as (ac, _):
        first = await _mk_product(ac, name="重名产品")
        # 不同短码、同名称 → 409
        resp = await ac.post(
            "/api/v1/qa/apr/products",
            json={"code": _code(), "name": first["name"]},
        )
        assert resp.status_code == 409
        assert "名称" in resp.json()["message"]
        # 另一个产品改名撞上来 → 409
        second = await _mk_product(ac, name="另一个产品")
        resp = await ac.patch(
            f"/api/v1/qa/apr/products/{second['id']}", json={"name": first["name"]}
        )
        assert resp.status_code == 409
        assert "名称" in resp.json()["message"]
        # 表单整单提交会带上未改动的名称，不能被自己挡住
        resp = await ac.patch(
            f"/api/v1/qa/apr/products/{first['id']}",
            json={"name": first["name"], "remark": "整单提交"},
        )
        assert resp.status_code == 200
        # 短码/名称是必填列，显式传 null 按 422 拒绝
        resp = await ac.patch(
            f"/api/v1/qa/apr/products/{first['id']}", json={"name": None}
        )
        assert resp.status_code == 422


async def test_product_code_normalized_to_upper() -> None:
    """短码入库统一转大写：小写入参回显大写，大小写变体视为同一短码。"""
    async with _client(MANAGE) as (ac, _):
        raw = f"u{uuid4().hex[:8]}"
        product = await _mk_product(ac, code=raw)
        assert product["code"] == raw.upper()
        # 换成小写再建 → 归一后撞码 409
        resp = await ac.post(
            "/api/v1/qa/apr/products",
            json={"code": raw.lower(), "name": f"大写测试{uuid4().hex[:6]}"},
        )
        assert resp.status_code == 409
        assert "短码" in resp.json()["message"]
        # PATCH 传大写形态（与入库值等价）不算改码，正常放行
        resp = await ac.patch(
            f"/api/v1/qa/apr/products/{product['id']}", json={"code": raw.upper()}
        )
        assert resp.status_code == 200
        # PATCH 小写改码同样归一为大写
        resp = await ac.patch(
            f"/api/v1/qa/apr/products/{product['id']}",
            json={"code": f"z{uuid4().hex[:8]}"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["code"].startswith("Z")


async def test_product_delete_guarded_by_sections() -> None:
    """产品下已配段时删除被拒。"""
    async with _client(MANAGE) as (ac, _):
        product = await _mk_product(ac)
        await _mk_section(ac, product["id"])
        resp = await ac.delete(f"/api/v1/qa/apr/products/{product['id']}")
        assert resp.status_code == 409


async def test_item_code_autogen_and_conflict() -> None:
    """列定义 code 未传自动生成；显式传重复 code 409。"""
    async with _client(MANAGE) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        item = await _mk_item(ac, section["id"])
        assert item["code"].startswith("it_")
        resp = await ac.post(
            "/api/v1/qa/apr/items",
            json={
                "section_id": section["id"],
                "name_cn": "重复码",
                "code": item["code"],
            },
        )
        assert resp.status_code == 409


async def test_item_delete_with_values_deactivates() -> None:
    """有历史值的列删除转为停用（保历史可解释），无值时直接删。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        item = await _mk_item(ac, section["id"])
        batch = await _mk_batch(ac, section["id"])
        resp = await ac.put(
            f"/api/v1/qa/apr/batches/{batch['id']}/values",
            json={"values": [{"item_id": item["id"], "value_num": 4.3}]},
        )
        assert resp.status_code == 200
        # 有值 → 停用
        resp = await ac.delete(f"/api/v1/qa/apr/items/{item['id']}")
        assert resp.status_code == 200
        assert resp.json()["data"]["is_active"] is False
        # 无值 → 直接软删
        item2 = await _mk_item(ac, section["id"], name_cn="水分")
        resp = await ac.delete(f"/api/v1/qa/apr/items/{item2['id']}")
        assert resp.status_code == 200
        assert resp.json()["data"]["is_active"] is True


async def test_item_value_type_change_guarded() -> None:
    """已录数值的列不能改成文字型。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        item = await _mk_item(ac, section["id"])
        batch = await _mk_batch(ac, section["id"])
        await ac.put(
            f"/api/v1/qa/apr/batches/{batch['id']}/values",
            json={"values": [{"item_id": item["id"], "value_num": 4.3}]},
        )
        resp = await ac.patch(
            f"/api/v1/qa/apr/items/{item['id']}", json={"value_type": "text"}
        )
        assert resp.status_code == 422


async def test_section_delete_guarded_by_batches() -> None:
    """段下已登记批次时删除被拒。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        await _mk_batch(ac, section["id"])
        resp = await ac.delete(f"/api/v1/qa/apr/sections/{section['id']}")
        assert resp.status_code == 409


async def test_section_name_conflict() -> None:
    """段名在同一产品内唯一：重复新建/改名撞名 409；跨产品可同名。"""
    async with _client(MANAGE) as (ac, _):
        product = await _mk_product(ac)
        await _mk_section(ac, product["id"], name="成品检验-USP")
        # 同产品下新建同名段 → 409
        resp = await ac.post(
            "/api/v1/qa/apr/sections",
            json={
                "product_id": product["id"],
                "name": "成品检验-USP",
                "data_kind": "inspection",
            },
        )
        assert resp.status_code == 409
        assert "段名" in resp.json()["message"]
        # 另一个段改名撞上来 → 409
        ferment = await _mk_section(
            ac,
            product["id"],
            name="发酵",
            data_kind="production",
            market=None,
            stage=None,
        )
        resp = await ac.patch(
            f"/api/v1/qa/apr/sections/{ferment['id']}", json={"name": "成品检验-USP"}
        )
        assert resp.status_code == 409
        assert "段名" in resp.json()["message"]
        # 名称不变（前端整单提交）不能被自己挡住
        resp = await ac.patch(
            f"/api/v1/qa/apr/sections/{ferment['id']}",
            json={"name": "发酵", "remark": "整单提交"},
        )
        assert resp.status_code == 200
        # 段名唯一作用域是产品：另一个产品可同名
        other_product = await _mk_product(ac)
        resp = await ac.post(
            "/api/v1/qa/apr/sections",
            json={
                "product_id": other_product["id"],
                "name": "成品检验-USP",
                "data_kind": "inspection",
            },
        )
        assert resp.status_code == 201, resp.text


async def test_section_data_kind_change_guarded() -> None:
    """段内已有列定义或批次后不能改数据类型（会改变汇总分组口径）。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)

        # 空段可以改
        empty = await _mk_section(
            ac, product["id"], name="空段", data_kind="production", market=None
        )
        resp = await ac.patch(
            f"/api/v1/qa/apr/sections/{empty['id']}", json={"data_kind": "inspection"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["data_kind"] == "inspection"

        # 有列定义 → 409
        with_item = await _mk_section(
            ac, product["id"], name="有列段", data_kind="production", market=None
        )
        await _mk_item(ac, with_item["id"])
        resp = await ac.patch(
            f"/api/v1/qa/apr/sections/{with_item['id']}",
            json={"data_kind": "inspection"},
        )
        assert resp.status_code == 409

        # 只有批次、没有列定义也拦
        with_batch = await _mk_section(
            ac, product["id"], name="有批次段", data_kind="production", market=None
        )
        await _mk_batch(ac, with_batch["id"])
        resp = await ac.patch(
            f"/api/v1/qa/apr/sections/{with_batch['id']}",
            json={"data_kind": "inspection"},
        )
        assert resp.status_code == 409

        # 改其他字段、data_kind 原样回传不受影响（前端编辑表单就是这么提交的）
        resp = await ac.patch(
            f"/api/v1/qa/apr/sections/{with_batch['id']}",
            json={"name": "有批次段-改名", "data_kind": "production"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["name"] == "有批次段-改名"


async def test_product_list_includes_template_counts() -> None:
    """产品列表附带段数与列定义数，配置页据此提示「已配置/未配置」。"""
    async with _client(MANAGE) as (ac, _):
        empty = await _mk_product(ac, name="未配置产品")
        configured = await _mk_product(ac, name="已配置产品")
        section = await _mk_section(ac, configured["id"])
        await _mk_item(ac, section["id"])
        await _mk_item(ac, section["id"], name_cn="水分")

        resp = await ac.get("/api/v1/qa/apr/products")
        assert resp.status_code == 200
        rows = {row["id"]: row for row in resp.json()["data"]}
        assert rows[empty["id"]]["section_count"] == 0
        assert rows[empty["id"]]["item_count"] == 0
        assert rows[configured["id"]]["section_count"] == 1
        assert rows[configured["id"]]["item_count"] == 2


async def test_copy_template() -> None:
    """模板整树复制：段与列定义计数一致；目标已有段拒绝。"""
    async with _client(MANAGE) as (ac, _):
        source = await _mk_product(ac, name="源产品")
        section = await _mk_section(ac, source["id"])
        await _mk_item(ac, section["id"], quick_values=["未检出", "<0.5"])
        await _mk_item(ac, section["id"], name_cn="水分")
        target = await _mk_product(ac, name="目标产品")
        resp = await ac.post(
            f"/api/v1/qa/apr/templates/{target['id']}/copy-from/{source['id']}"
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["data"]["sections"] == 1
        assert resp.json()["data"]["items"] == 2
        # 复制后的模板可读且包含两列
        resp = await ac.get(f"/api/v1/qa/apr/sections?product_id={target['id']}")
        sections = resp.json()["data"]
        assert len(sections) == 1
        assert len(sections[0]["items"]) == 2
        copied = next(i for i in sections[0]["items"] if i["name_cn"] == "酸碱度")
        assert copied["quick_values"] == ["未检出", "<0.5"]
        # 重复复制被拒
        resp = await ac.post(
            f"/api/v1/qa/apr/templates/{target['id']}/copy-from/{source['id']}"
        )
        assert resp.status_code == 409
        # 同产品复制被拒
        resp = await ac.post(
            f"/api/v1/qa/apr/templates/{source['id']}/copy-from/{source['id']}"
        )
        assert resp.status_code == 422


# ───────────────────────── 批次与值 ─────────────────────────


async def test_batch_create_and_conflict() -> None:
    """批次登记；同段同年同批号重复 409；不同年可重号。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        batch = await _mk_batch(ac, section["id"], batch_no="DT2501001", year=2025)
        assert batch["batch_no"] == "DT2501001"
        resp = await ac.post(
            "/api/v1/qa/apr/batches",
            json={
                "section_id": section["id"],
                "year": 2025,
                "batch_no": "DT2501001",
            },
        )
        assert resp.status_code == 409
        resp = await ac.post(
            "/api/v1/qa/apr/batches",
            json={
                "section_id": section["id"],
                "year": 2026,
                "batch_no": "DT2501001",
            },
        )
        assert resp.status_code == 201


async def test_save_values_roundtrip_and_guards() -> None:
    """值保存回读、列归属校验、数值/文字匹配、(item,row) 去重。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        ph = await _mk_item(ac, section["id"])
        chars = await _mk_item(
            ac,
            section["id"],
            name_cn="性状",
            value_type="text",
            spec_text="白色粉末",
            trend_enabled=False,
        )
        batch = await _mk_batch(ac, section["id"])
        # number 项数值/文字都缺（仅备注）→ 422
        resp = await ac.put(
            f"/api/v1/qa/apr/batches/{batch['id']}/values",
            json={"values": [{"item_id": ph["id"], "remark": "仅备注"}]},
        )
        assert resp.status_code == 422
        # text 项缺文字 → 422
        resp = await ac.put(
            f"/api/v1/qa/apr/batches/{batch['id']}/values",
            json={"values": [{"item_id": chars["id"], "value_num": 1}]},
        )
        assert resp.status_code == 422
        # (item, row) 重复 → 422
        resp = await ac.put(
            f"/api/v1/qa/apr/batches/{batch['id']}/values",
            json={
                "values": [
                    {"item_id": ph["id"], "value_num": 4.3},
                    {"item_id": ph["id"], "value_num": 4.4},
                ]
            },
        )
        assert resp.status_code == 422
        # 正常保存 + 回读
        resp = await ac.put(
            f"/api/v1/qa/apr/batches/{batch['id']}/values",
            json={
                "values": [
                    {"item_id": ph["id"], "value_num": 4.31},
                    {"item_id": chars["id"], "value_text": "符合规定"},
                ]
            },
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["saved"] == 2
        resp = await ac.get(f"/api/v1/qa/apr/batches/{batch['id']}/values")
        data = resp.json()["data"]
        by_item = {v["item_id"]: v for v in data["values"]}
        assert by_item[ph["id"]]["value_num"] == 4.31
        assert by_item[chars["id"]]["value_text"] == "符合规定"
        # 全量替换：重存只留一条
        resp = await ac.put(
            f"/api/v1/qa/apr/batches/{batch['id']}/values",
            json={"values": [{"item_id": ph["id"], "value_num": 4.33}]},
        )
        assert resp.status_code == 200
        resp = await ac.get(f"/api/v1/qa/apr/batches/{batch['id']}/values")
        assert len(resp.json()["data"]["values"]) == 1
        # 其他产品的列 → 422
        other_product = await _mk_product(ac, name="别家")
        other_section = await _mk_section(ac, other_product["id"])
        foreign = await _mk_item(ac, other_section["id"])
        resp = await ac.put(
            f"/api/v1/qa/apr/batches/{batch['id']}/values",
            json={"values": [{"item_id": foreign["id"], "value_num": 1}]},
        )
        assert resp.status_code == 422


async def test_save_values_required_items_enforced() -> None:
    """必填列漏填时拒绝保存：整批替换下漏填会被静默清掉。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(
            ac, product["id"], data_kind="production", market=None
        )
        required = await _mk_item(ac, section["id"], name_cn="含量", required=True)
        optional = await _mk_item(ac, section["id"], name_cn="水分")
        batch = await _mk_batch(ac, section["id"])
        url = f"/api/v1/qa/apr/batches/{batch['id']}/values"

        # 只填非必填 → 422，并指出缺哪列
        resp = await ac.put(
            url, json={"values": [{"item_id": optional["id"], "value_num": 1.0}]}
        )
        assert resp.status_code == 422
        assert "含量" in resp.json()["message"]

        # 必填填上 → 200
        resp = await ac.put(
            url,
            json={
                "values": [
                    {"item_id": required["id"], "value_num": 99.1},
                    {"item_id": optional["id"], "value_num": 1.0},
                ]
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["saved"] == 2

        # 清空必填（空占位）→ 422，历史值不会被静默删掉
        resp = await ac.put(
            url, json={"values": [{"item_id": required["id"], "value_num": None}]}
        )
        assert resp.status_code == 422
        resp = await ac.get(url)
        assert len(resp.json()["data"]["values"]) == 2


async def test_save_values_required_items_multi_row() -> None:
    """多行段：有内容的行必须填满必填列，未提交的行不校验。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(
            ac,
            product["id"],
            name="多行段",
            data_kind="production",
            market=None,
            multi_row=True,
        )
        required = await _mk_item(ac, section["id"], name_cn="罐压", required=True)
        optional = await _mk_item(ac, section["id"], name_cn="备注数值")
        batch = await _mk_batch(ac, section["id"])
        url = f"/api/v1/qa/apr/batches/{batch['id']}/values"

        # 第 2 行只填非必填 → 422，点名第 2 行
        resp = await ac.put(
            url,
            json={
                "values": [
                    {"item_id": required["id"], "row_seq": 1, "value_num": 1.0},
                    {"item_id": optional["id"], "row_seq": 2, "value_num": 2.0},
                ]
            },
        )
        assert resp.status_code == 422
        assert "第 2 行" in resp.json()["message"]

        # 只提交第 1 行 → 200
        resp = await ac.put(
            url,
            json={"values": [{"item_id": required["id"], "row_seq": 1, "value_num": 1.0}]},
        )
        assert resp.status_code == 200, resp.text


async def test_multi_row_values() -> None:
    """multi_row 段一批多行（罐号）保存与汇总展开。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(
            ac,
            product["id"],
            name="盐脱中和",
            data_kind="production",
            multi_row=True,
        )
        ph = await _mk_item(ac, section["id"], name_cn="中和液pH", category="ipc")
        batch = await _mk_batch(ac, section["id"], batch_no="STI-ET-2501-001")
        resp = await ac.put(
            f"/api/v1/qa/apr/batches/{batch['id']}/values",
            json={
                "values": [
                    {
                        "item_id": ph["id"],
                        "row_seq": 1,
                        "row_label": "1号罐",
                        "value_num": 5.26,
                    },
                    {
                        "item_id": ph["id"],
                        "row_seq": 2,
                        "row_label": "2号罐",
                        "value_num": 5.41,
                    },
                ]
            },
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["saved"] == 2
        resp = await ac.get(
            f"/api/v1/qa/apr/summary?product_id={product['id']}&year=2025"
        )
        rows = resp.json()["data"]["sections"][0]["rows"]
        assert len(rows) == 2
        assert {r["row_label"] for r in rows} == {"1号罐", "2号罐"}


# ───────────────────────── 年度锁定 ─────────────────────────


async def test_lock_blocks_writes() -> None:
    """锁定后批次/值写操作被拒，解锁恢复；空年度锁定与重复锁定被拒。"""
    async with _client(MANAGE | ENTER | LOCK) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        item = await _mk_item(ac, section["id"])
        # 无数据锁 → 422
        resp = await ac.post(f"/api/v1/qa/apr/annual-reviews/{product['id']}/2025/lock")
        assert resp.status_code == 422
        batch = await _mk_batch(ac, section["id"], year=2025)
        await ac.put(
            f"/api/v1/qa/apr/batches/{batch['id']}/values",
            json={"values": [{"item_id": item["id"], "value_num": 4.3}]},
        )
        # 锁定
        resp = await ac.post(f"/api/v1/qa/apr/annual-reviews/{product['id']}/2025/lock")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "locked"
        # 写批次 → 422
        resp = await ac.post(
            "/api/v1/qa/apr/batches",
            json={
                "section_id": section["id"],
                "year": 2025,
                "batch_no": _code("B"),
            },
        )
        assert resp.status_code == 422
        # 写值 → 422
        resp = await ac.put(
            f"/api/v1/qa/apr/batches/{batch['id']}/values",
            json={"values": [{"item_id": item["id"], "value_num": 9.9}]},
        )
        assert resp.status_code == 422
        # 重复锁 → 422
        resp = await ac.post(f"/api/v1/qa/apr/annual-reviews/{product['id']}/2025/lock")
        assert resp.status_code == 422
        # 汇总里带锁定标记
        resp = await ac.get(
            f"/api/v1/qa/apr/summary?product_id={product['id']}&year=2025"
        )
        assert resp.json()["data"]["locked"] is True
        # 解锁后恢复
        resp = await ac.post(
            f"/api/v1/qa/apr/annual-reviews/{product['id']}/2025/unlock"
        )
        assert resp.status_code == 200
        resp = await ac.put(
            f"/api/v1/qa/apr/batches/{batch['id']}/values",
            json={"values": [{"item_id": item["id"], "value_num": 4.4}]},
        )
        assert resp.status_code == 200


# ───────────────────────── 趋势 ─────────────────────────


async def test_trend_classification_and_stats() -> None:
    """趋势逐点 OOS/OOT 分类与 ±3σ 统计。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        # spec 4.0-4.6，OOT 4.2-4.5：4.30/4.35 线内 normal，4.10/4.55 超 OOT
        # 线但在 spec 内 oot，4.70 超 spec → oos
        item = await _mk_item(ac, section["id"])
        values = [4.30, 4.35, 4.10, 4.55, 4.70]
        for i, v in enumerate(values, start=1):
            batch = await _mk_batch(ac, section["id"], batch_no=f"DT2501{i:03d}", seq=i)
            resp = await ac.put(
                f"/api/v1/qa/apr/batches/{batch['id']}/values",
                json={"values": [{"item_id": item["id"], "value_num": v}]},
            )
            assert resp.status_code == 200, resp.text
        resp = await ac.get(f"/api/v1/qa/apr/trends?item_id={item['id']}&year=2025")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        statuses = [p["status"] for p in data["points"]]
        assert statuses == ["normal", "normal", "oot", "oot", "oos"]
        stats = data["stats"]
        assert stats["count"] == 5
        assert stats["mean"] == pytest.approx(4.4)
        assert stats["max"] == 4.70
        assert "stdev" in stats and "plus3s" in stats
        # 年份过滤：没有 2026 数据则空
        resp = await ac.get(f"/api/v1/qa/apr/trends?item_id={item['id']}&year=2026")
        assert resp.json()["data"]["points"] == []


async def test_number_item_text_result_nd_policy() -> None:
    """数值列文字结果（未检出）：录入/回读、zero 口径按 0 进统计、exclude 不进。

    汇总里 ND 单元格不做 OOS/OOT 判定（status=None），趋势 ND 点恒 normal；
    两种口径都透明返回 nd_count。
    """
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        # 默认 zero 口径
        item = await _mk_item(ac, section["id"])
        assert item["nd_policy"] == "zero"
        b1 = await _mk_batch(ac, section["id"], batch_no="ND250101", seq=1)
        b2 = await _mk_batch(ac, section["id"], batch_no="ND250102", seq=2)
        b3 = await _mk_batch(ac, section["id"], batch_no="ND250103", seq=3)
        values_url = f"/api/v1/qa/apr/batches/{b2['id']}/values"
        # 数值项只填文字结果 → 200（原始记录保留文字）
        resp = await ac.put(
            values_url,
            json={"values": [{"item_id": item["id"], "value_text": "未检出"}]},
        )
        assert resp.status_code == 200, resp.text
        resp = await ac.get(values_url)
        assert resp.json()["data"]["values"][0]["value_text"] == "未检出"
        await ac.put(
            f"/api/v1/qa/apr/batches/{b1['id']}/values",
            json={"values": [{"item_id": item["id"], "value_num": 4.30}]},
        )
        await ac.put(
            f"/api/v1/qa/apr/batches/{b3['id']}/values",
            json={"values": [{"item_id": item["id"], "value_num": 4.50}]},
        )

        # zero 口径趋势：ND 按 0 进样本
        resp = await ac.get(f"/api/v1/qa/apr/trends?item_id={item['id']}&year=2025")
        data = resp.json()["data"]
        assert data["stats"]["count"] == 3
        assert data["stats"]["nd_count"] == 1
        assert data["stats"]["mean"] == pytest.approx((4.30 + 0.0 + 4.50) / 3)
        nd_point = data["points"][1]
        assert nd_point["nd"] is True
        assert nd_point["value"] == 0.0
        assert nd_point["status"] == "normal"

        # zero 口径汇总：count 含 ND，ND 单元格不判定
        resp = await ac.get(
            f"/api/v1/qa/apr/summary?product_id={product['id']}&year=2025"
        )
        payload = next(
            s for s in resp.json()["data"]["sections"] if s["id"] == section["id"]
        )
        stats = payload["column_stats"][item["id"]]
        assert stats["count"] == 3
        assert stats["nd_count"] == 1
        assert stats["mean"] == pytest.approx((4.30 + 0.0 + 4.50) / 3)
        nd_cell = next(
            r for r in payload["rows"] if r["batch_id"] == b2["id"]
        )["cells"][item["id"]]
        assert nd_cell["num"] is None
        assert nd_cell["text"] == "未检出"
        assert nd_cell["status"] is None

        # 切换 exclude 口径：ND 不进样本，nd_count 仍透明返回
        resp = await ac.patch(
            f"/api/v1/qa/apr/items/{item['id']}", json={"nd_policy": "exclude"}
        )
        assert resp.status_code == 200, resp.text
        resp = await ac.get(f"/api/v1/qa/apr/trends?item_id={item['id']}&year=2025")
        data = resp.json()["data"]
        assert data["stats"]["count"] == 2
        assert data["stats"]["nd_count"] == 1
        assert data["stats"]["mean"] == pytest.approx((4.30 + 4.50) / 2)
        assert len(data["points"]) == 2

        # 必填数值项填「未检出」也算已填
        required = await _mk_item(
            ac, section["id"], name_cn="残留溶剂", required=True, spec_min=None
        )
        b4 = await _mk_batch(ac, section["id"], batch_no="ND250104", seq=4)
        resp = await ac.put(
            f"/api/v1/qa/apr/batches/{b4['id']}/values",
            json={"values": [{"item_id": required["id"], "value_text": "未检出"}]},
        )
        assert resp.status_code == 200, resp.text


async def test_item_quick_values_whitelist_and_normalization() -> None:
    """数值列文字结果白名单：默认 未检出/<1；全角字符归一化；非白名单 422。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        item = await _mk_item(ac, section["id"])
        assert item["quick_values"] == ["未检出", "<1"]
        batch = await _mk_batch(ac, section["id"])
        url = f"/api/v1/qa/apr/batches/{batch['id']}/values"

        # 全角 ＜１ 归一化后命中默认白名单 <1
        resp = await ac.put(
            url, json={"values": [{"item_id": item["id"], "value_text": "＜１"}]}
        )
        assert resp.status_code == 200, resp.text
        resp = await ac.get(url)
        assert resp.json()["data"]["values"][0]["value_text"] == "<1"

        # 不在白名单的文字 → 422，且不覆盖已存值
        resp = await ac.put(
            url, json={"values": [{"item_id": item["id"], "value_text": "小于1"}]}
        )
        assert resp.status_code == 422
        assert "未检出" in resp.json()["message"]
        resp = await ac.get(url)
        assert resp.json()["data"]["values"][0]["value_text"] == "<1"

        # 列级配置：改成 <0.5 后生效，旧 <1 不再通过
        resp = await ac.patch(
            f"/api/v1/qa/apr/items/{item['id']}",
            json={"quick_values": ["未检出", "＜０.５"]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["quick_values"] == ["未检出", "<0.5"]
        resp = await ac.put(
            url, json={"values": [{"item_id": item["id"], "value_text": "<0.5"}]}
        )
        assert resp.status_code == 200, resp.text
        resp = await ac.put(
            url, json={"values": [{"item_id": item["id"], "value_text": "<1"}]}
        )
        assert resp.status_code == 422

        # 数值本身不受白名单影响
        resp = await ac.put(
            url, json={"values": [{"item_id": item["id"], "value_num": 0.77}]}
        )
        assert resp.status_code == 200, resp.text


async def test_trend_rejects_text_item() -> None:
    """文字型列与未启用趋势的列请求趋势被拒。"""
    async with _client(MANAGE) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        text_item = await _mk_item(
            ac, section["id"], name_cn="性状", value_type="text", trend_enabled=False
        )
        resp = await ac.get(f"/api/v1/qa/apr/trends?item_id={text_item['id']}")
        assert resp.status_code == 422
        num_item = await _mk_item(
            ac, section["id"], name_cn="水分", trend_enabled=False
        )
        resp = await ac.get(f"/api/v1/qa/apr/trends?item_id={num_item['id']}")
        assert resp.status_code == 422


# ───────────────────────── 汇总与导出 ─────────────────────────


async def test_summary_matrix_and_filters() -> None:
    """汇总矩阵结构；market/data_kind 过滤；数值列统计。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        us = await _mk_section(ac, product["id"], name="成品检验-US", market="US")
        chp = await _mk_section(ac, product["id"], name="成品检验-ChP", market="Ch.P")
        prod = await _mk_section(
            ac, product["id"], name="发酵", data_kind="production", market=None
        )
        ph_us = await _mk_item(ac, us["id"])
        # ChP 段与生产段只配列定义不录值，验证汇总不因缺值阻塞。
        await _mk_item(ac, chp["id"], name_cn="酸碱度", spec_min=4.0, spec_max=5.0)
        await _mk_item(
            ac, prod["id"], name_cn="培养温度MIN", category="cpp", code="temp#min"
        )
        b1 = await _mk_batch(ac, us["id"], batch_no="MSK2501001", seq=1)
        b2 = await _mk_batch(ac, us["id"], batch_no="MSK2501002", seq=2)
        await ac.put(
            f"/api/v1/qa/apr/batches/{b1['id']}/values",
            json={"values": [{"item_id": ph_us["id"], "value_num": 4.70}]},
        )
        await ac.put(
            f"/api/v1/qa/apr/batches/{b2['id']}/values",
            json={"values": [{"item_id": ph_us["id"], "value_num": 4.30}]},
        )
        # ChP 段与生产段各一批（值缺失不阻塞汇总）
        await _mk_batch(ac, chp["id"], batch_no="MSK2501001", seq=1)
        await _mk_batch(ac, prod["id"], batch_no="KA-205B-2501-001", seq=1)

        resp = await ac.get(
            f"/api/v1/qa/apr/summary?product_id={product['id']}&year=2025"
        )
        data = resp.json()["data"]
        assert len(data["sections"]) == 3
        us_payload = next(s for s in data["sections"] if s["market"] == "US")
        assert len(us_payload["rows"]) == 2
        row1 = us_payload["rows"][0]
        # 4.70 超 spec 4.6 → oos
        assert row1["cells"][ph_us["id"]]["status"] == "oos"
        stats = us_payload["column_stats"][ph_us["id"]]
        assert stats["count"] == 2
        assert stats["mean"] == pytest.approx(4.5)

        # market 过滤
        resp = await ac.get(
            f"/api/v1/qa/apr/summary?product_id={product['id']}&year=2025&market=Ch.P"
        )
        data = resp.json()["data"]
        assert [s["market"] for s in data["sections"]] == ["Ch.P"]
        # data_kind 过滤
        resp = await ac.get(
            f"/api/v1/qa/apr/summary?product_id={product['id']}"
            f"&year=2025&data_kind=production"
        )
        data = resp.json()["data"]
        assert [s["data_kind"] for s in data["sections"]] == ["production"]


async def test_summary_export_xlsx() -> None:
    """汇总导出返回 xlsx 流，文件名含产品与年度。"""
    async with _client(MANAGE | ENTER | EXPORT) as (ac, _):
        product = await _mk_product(ac, name="达托霉素")
        section = await _mk_section(ac, product["id"])
        item = await _mk_item(ac, section["id"])
        batch = await _mk_batch(ac, section["id"], batch_no="DT2501001")
        await ac.put(
            f"/api/v1/qa/apr/batches/{batch['id']}/values",
            json={"values": [{"item_id": item["id"], "value_num": 4.3}]},
        )
        resp = await ac.get(
            f"/api/v1/qa/apr/summary/export?product_id={product['id']}&year=2025"
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert "attachment" in resp.headers["content-disposition"]
        assert len(resp.content) > 1000


async def test_bulk_create_items_appends_sort_order() -> None:
    """批量建列：顺序按数组依次追加（10/20/30），单列新增继续往后排。"""
    async with _client(MANAGE) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        resp = await ac.post(
            f"/api/v1/qa/apr/sections/{section['id']}/items/bulk",
            json={
                "items": [
                    {"name_cn": "批号", "category": "info", "value_type": "text"},
                    {"name_cn": "保温时间", "category": "cpp", "unit": "min"},
                    {"name_cn": "培养基pH", "category": "ipc", "spec_text": "6.6±0.4"},
                ]
            },
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["count"] == 3
        assert [item["sort_order"] for item in data["items"]] == [10, 20, 30]
        assert all(item["code"].startswith("it_") for item in data["items"])

        appended = await _mk_item(ac, section["id"], name_cn="追加列")
        assert appended["sort_order"] == 40


async def test_bulk_create_items_rejects_duplicate_code() -> None:
    """批量建列：编码重复整体拒绝（批内重复与已存在都 409）。"""
    async with _client(MANAGE) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        existing = await _mk_item(ac, section["id"], code="ph_value")

        resp = await ac.post(
            f"/api/v1/qa/apr/sections/{section['id']}/items/bulk",
            json={
                "items": [
                    {"name_cn": "重复一", "code": "dup_code"},
                    {"name_cn": "重复二", "code": "dup_code"},
                ]
            },
        )
        assert resp.status_code == 409

        resp = await ac.post(
            f"/api/v1/qa/apr/sections/{section['id']}/items/bulk",
            json={"items": [{"name_cn": "撞已有", "code": existing["code"]}]},
        )
        assert resp.status_code == 409


# ───────────────────────── 锁定与守卫补充 ─────────────────────────


async def test_lock_blocks_batch_moving_into_locked_year() -> None:
    """批次改年度迁入已锁定年度被拒（旧年度开放不代表目标年度开放）。"""
    async with _client(MANAGE | ENTER | LOCK) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        # 2024 有数据并锁定；2025 开放
        old_batch = await _mk_batch(ac, section["id"], year=2024, batch_no="DT2401001")
        resp = await ac.post(f"/api/v1/qa/apr/annual-reviews/{product['id']}/2024/lock")
        assert resp.status_code == 200
        batch = await _mk_batch(ac, section["id"], year=2025, batch_no="DT2501001")
        # 2025 → 2024（已锁定）被拒
        resp = await ac.patch(
            f"/api/v1/qa/apr/batches/{batch['id']}", json={"year": 2024}
        )
        assert resp.status_code == 422
        assert "锁定" in resp.json()["message"]
        # 已锁定年度内的批次原样 PATCH 也被拒
        resp = await ac.patch(
            f"/api/v1/qa/apr/batches/{old_batch['id']}", json={"remark": "x"}
        )
        assert resp.status_code == 422
        # 开放年度之间迁移仍允许
        resp = await ac.patch(
            f"/api/v1/qa/apr/batches/{batch['id']}", json={"year": 2026}
        )
        assert resp.status_code == 200, resp.text


async def test_lock_year_out_of_range() -> None:
    """锁定端点 year 限 2000-2100，越界 422。"""
    async with _client(MANAGE | LOCK) as (ac, _):
        product = await _mk_product(ac)
        resp = await ac.post(
            f"/api/v1/qa/apr/annual-reviews/{product['id']}/1999/lock"
        )
        assert resp.status_code == 422


async def test_lock_and_export_require_dedicated_permission() -> None:
    """锁定/导出各自独立权限：持读码（或仅 enter/export 单码）一律 403。

    权限依赖在路由处理前执行，用随机产品 id 即可触发判定。
    """
    any_product = str(uuid4())
    async with _client(READ) as (ac, _):
        resp = await ac.post(
            f"/api/v1/qa/apr/annual-reviews/{any_product}/2025/lock"
        )
        assert resp.status_code == 403
        resp = await ac.get(
            f"/api/v1/qa/apr/summary/export?product_id={any_product}&year=2025"
        )
        assert resp.status_code == 403
    async with _client(READ | {"qa:apr:export"}) as (ac, _):
        # 有导出码但无锁定码：锁定仍 403
        resp = await ac.post(
            f"/api/v1/qa/apr/annual-reviews/{any_product}/2025/lock"
        )
        assert resp.status_code == 403


async def test_item_update_code_conflict() -> None:
    """编辑列定义改 code 撞段内已有编码 409。"""
    async with _client(MANAGE) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        await _mk_item(ac, section["id"], code="first_col")
        second = await _mk_item(ac, section["id"], name_cn="水分", code="second_col")
        resp = await ac.patch(
            f"/api/v1/qa/apr/items/{second['id']}", json={"code": "first_col"}
        )
        assert resp.status_code == 409
        # 改成不冲突的新码成功
        resp = await ac.patch(
            f"/api/v1/qa/apr/items/{second['id']}", json={"code": "renamed_col"}
        )
        assert resp.status_code == 200


async def test_single_row_section_rejects_row_seq_over_one() -> None:
    """单行段提交 row_seq>1 被拒（防汇总幻影行）。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])  # 默认 multi_row=False
        item = await _mk_item(ac, section["id"])
        batch = await _mk_batch(ac, section["id"])
        resp = await ac.put(
            f"/api/v1/qa/apr/batches/{batch['id']}/values",
            json={"values": [{"item_id": item["id"], "row_seq": 2, "value_num": 4.3}]},
        )
        assert resp.status_code == 422
        assert "单行段" in resp.json()["message"]
        # row_seq=1 正常
        resp = await ac.put(
            f"/api/v1/qa/apr/batches/{batch['id']}/values",
            json={"values": [{"item_id": item["id"], "value_num": 4.3}]},
        )
        assert resp.status_code == 200


async def test_item_limit_edit_frozen_in_locked_year() -> None:
    """列限度在锁定年度有录入值时冻结；名称等其他字段不受影响。"""
    async with _client(MANAGE | ENTER | LOCK) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        item = await _mk_item(ac, section["id"])
        batch = await _mk_batch(ac, section["id"], year=2025)
        await ac.put(
            f"/api/v1/qa/apr/batches/{batch['id']}/values",
            json={"values": [{"item_id": item["id"], "value_num": 4.3}]},
        )
        await ac.post(f"/api/v1/qa/apr/annual-reviews/{product['id']}/2025/lock")
        # 改限度 → 422
        resp = await ac.patch(
            f"/api/v1/qa/apr/items/{item['id']}", json={"spec_max": 4.8}
        )
        assert resp.status_code == 422
        assert "锁定" in resp.json()["message"]
        # 改名称（限度不动）→ 200
        resp = await ac.patch(
            f"/api/v1/qa/apr/items/{item['id']}", json={"name_cn": "酸碱度（新）"}
        )
        assert resp.status_code == 200
        # 未锁定年度（2026）有值时改限度仍允许
        item2 = await _mk_item(ac, section["id"], name_cn="水分")
        batch2 = await _mk_batch(ac, section["id"], year=2026)
        await ac.put(
            f"/api/v1/qa/apr/batches/{batch2['id']}/values",
            json={"values": [{"item_id": item2["id"], "value_num": 3.0}]},
        )
        resp = await ac.patch(
            f"/api/v1/qa/apr/items/{item2['id']}", json={"spec_min": 2.0}
        )
        assert resp.status_code == 200


async def test_item_limit_interval_validated() -> None:
    """限度区间下限大于上限：创建 422；PATCH 单边改成矛盾也 422。"""
    async with _client(MANAGE) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        resp = await ac.post(
            "/api/v1/qa/apr/items",
            json={
                "section_id": section["id"],
                "name_cn": "矛盾区间",
                "spec_min": 4.6,
                "spec_max": 4.0,
            },
        )
        assert resp.status_code == 422
        item = await _mk_item(ac, section["id"])  # spec 4.0-4.6
        # 同一请求里矛盾 → 422
        resp = await ac.patch(
            f"/api/v1/qa/apr/items/{item['id']}",
            json={"spec_min": 4.7, "spec_max": 4.1},
        )
        assert resp.status_code == 422
        # 单边改到与现值矛盾 → service 合并兜底 422
        resp = await ac.patch(
            f"/api/v1/qa/apr/items/{item['id']}", json={"spec_min": 4.8}
        )
        assert resp.status_code == 422
