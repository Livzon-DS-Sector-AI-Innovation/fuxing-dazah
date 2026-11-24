"""QA COA 域 API 测试：产品/标准 CRUD、项目替换守卫、矩阵同名项目合并列、
docx 导入预览、出具登记唯一约束、导入匹配与矩阵透视。

沿用 test_apr_api 的 harness：覆盖 get_db / get_current_user 并 patch 权限
集合，整条用例共用一个最终回滚的会话；随机前缀防共享开发库冲突。
docx 导入用例使用真实样本 fixture（coa_haf_sample.docx，30 项）。
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.main import app as fastapi_app
from app.modules.qa.models import CoaStandardItem
from app.modules.qa.service.coa import ai_parse as coa_ai_parse
from app.modules.qa.service.coa import import_standard, issuance
from app.platform.identity.deps import get_current_user
from app.platform.identity.models import User
from tests.conftest import _test_session_factory

READ = {"qa:coa:read"}
WILDCARD_READ = {"qa:all:read"}
MANAGE = READ | {"qa:coa:manage"}
ISSUE = READ | {"qa:coa:issue"}

FIXTURE = Path(__file__).parent / "fixtures" / "coa_haf_sample.docx"

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _stub_ai_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    """docx 导入预览打桩为固定 AI 载荷（上传/提取/复判链路由 test_coa_parse 覆盖）。

    按调用场景分流：标准导入（structure）返回含批次字段标签清单的结构载荷，
    报告导入（values）返回真实样本值载荷。
    """
    values_payload = json.loads(
        (Path(__file__).parent / "fixtures" / "coa_ai_payload.json").read_text()
    )
    structure_payload = {
        "report_no": "COA-HAF-3205-006",
        "batch_info_fields": [
            {"label_cn": "品  名", "label_en": "Product Name"},
            {"label_cn": "批  号", "label_en": "Batch No."},
            {"label_cn": "生产日期", "label_en": "Mfg. Date"},
            {"label_cn": "复验期", "label_en": "Retest Date"},
        ],
        "batch_info": {"product": "盐酸万古霉素 Vancomycin Hydrochloride"},
        "items": values_payload["items"],
    }

    async def _fake(
        data: bytes, filename: str = "coa.docx", *, mode: str = "values"
    ):
        assert data, "导入必须携带文件字节"
        payload = structure_payload if mode == "structure" else values_payload
        return coa_ai_parse._build_parse(payload)

    monkeypatch.setattr(import_standard, "parse_docx_ai", _fake)
    monkeypatch.setattr(issuance, "parse_docx_ai", _fake)


async def _ensure_test_user(session: AsyncSession) -> User:
    stmt = select(User).where(User.is_deleted == False).limit(1)  # noqa: E712
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing
    user = User(name="qa-coa测试用户", employee_no="QA-COA-TEST-001")
    session.add(user)
    await session.flush()
    return user


@asynccontextmanager
async def _client(
    perms: set[str] | None,
) -> AsyncGenerator[tuple[AsyncClient, AsyncSession], None]:
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


def _uniq(prefix: str) -> str:
    return f"{prefix}{uuid4().hex[:8].upper()}"


async def _mk_product(ac: AsyncClient, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": _uniq("HAF"),
        "name": f"盐酸万古霉素{uuid4().hex[:6]}",
        "name_en": "Vancomycin Hydrochloride",
    }
    payload.update(overrides)
    resp = await ac.post("/api/v1/qa/coa/products", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def _mk_standard(
    ac: AsyncClient, product_id: str, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "product_id": product_id,
        "code": _uniq("32"),
        "name": _uniq("USP 客户标准 "),
        "customer": "海外客户A",
        "market": "USP",
        "items": [
            {
                "name_cn": "pH",
                "value_type": "number",
                "spec_text": "2.5～4.5",
                "spec_min": 2.5,
                "spec_max": 4.5,
            },
            {
                "name_cn": "水分",
                "name_en": "Water",
                "value_type": "number",
                "spec_text": "≤5.0%",
                "spec_max": 5.0,
            },
            {
                "name_cn": "炽灼残渣",
                "value_type": "number",
                "spec_text": "≤1.0%",
                "spec_max": 1.0,
            },
        ],
    }
    payload.update(overrides)
    resp = await ac.post("/api/v1/qa/coa/standards", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def _mk_report(
    ac: AsyncClient, product_id: str, standard: dict[str, Any], **overrides: Any
) -> dict[str, Any]:
    ph = next(i for i in standard["items"] if i["name_cn"] == "pH")
    water = next(i for i in standard["items"] if i["name_cn"] == "水分")
    payload: dict[str, Any] = {
        "product_id": product_id,
        "standard_id": standard["id"],
        "batch_no": _uniq("HAF2607"),
        "serial_no": _uniq("26"),
        "values": [
            {"item_id": ph["id"], "value_num": 2.85, "value_text": "2.85"},
            {"item_id": water["id"], "value_num": 2.3, "value_text": "2.3%"},
        ],
    }
    payload.update(overrides)
    resp = await ac.post("/api/v1/qa/coa/reports", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


# ─────────────────────── 权限与产品 ───────────────────────


class TestProducts:
    async def test_read_requires_permission(self):
        async with _client(None) as (ac, _):
            resp = await ac.get("/api/v1/qa/coa/products")
            assert resp.status_code == 401

    async def test_wildcard_read_grants_listing(self):
        async with _client(WILDCARD_READ) as (ac, _):
            resp = await ac.get("/api/v1/qa/coa/products")
            assert resp.status_code == 200
            assert isinstance(resp.json()["data"], list)

    async def test_create_requires_manage(self):
        async with _client(READ) as (ac, _):
            resp = await ac.post(
                "/api/v1/qa/coa/products",
                json={"code": "ZZZ", "name": "无权限产品"},
            )
            assert resp.status_code == 403

    async def test_code_normalized_upper_and_unique(self):
        async with _client(MANAGE) as (ac, _):
            product = await _mk_product(ac, code="haf-test")
            assert product["code"] == "HAF-TEST"
            # 同码再建 → 409
            resp = await ac.post(
                "/api/v1/qa/coa/products",
                json={"code": "HAF-TEST", "name": _uniq("重名")},
            )
            assert resp.status_code == 409

    async def test_update_explicit_null_required_is_noop(self):
        """显式 null = 不改（schema 口径），不得写 NULL 触发 500。"""
        async with _client(MANAGE) as (ac, _):
            product = await _mk_product(ac)
            resp = await ac.patch(
                f"/api/v1/qa/coa/products/{product['id']}",
                json={"code": None, "name": None, "is_active": None},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
            assert data["code"] == product["code"]
            assert data["name"] == product["name"]
            assert data["is_active"] == product["is_active"]


# ─────────────────────── 客户标准 ───────────────────────


class TestStandards:
    async def test_create_with_items_and_code_generation(self):
        async with _client(MANAGE) as (ac, _):
            product = await _mk_product(ac)
            std = await _mk_standard(ac, product["id"])
            assert std["item_count"] == 3
            codes = {i["code"] for i in std["items"]}
            # code 由中英文名归一化生成，确定性可重放
            assert "ph" in codes
            assert "水分water" in codes

    async def test_update_explicit_null_required_is_noop(self):
        """显式 null = 不改（schema 口径），不得写 NULL 触发 500。"""
        async with _client(MANAGE) as (ac, _):
            product = await _mk_product(ac)
            std = await _mk_standard(ac, product["id"])
            resp = await ac.patch(
                f"/api/v1/qa/coa/standards/{std['id']}",
                json={"code": None, "name": None, "is_active": None},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
            assert data["code"] == std["code"]
            assert data["name"] == std["name"]
            assert data["is_active"] == std["is_active"]

    async def test_duplicate_code_same_product_rejected(self):
        async with _client(MANAGE) as (ac, _):
            product = await _mk_product(ac)
            std = await _mk_standard(ac, product["id"])
            resp = await ac.post(
                "/api/v1/qa/coa/standards",
                json={
                    "product_id": product["id"],
                    "code": std["code"],
                    "name": _uniq("撞码标准 "),
                },
            )
            assert resp.status_code == 409

    async def test_items_replace_reference_guard(self):
        """移除项统一软删让号（项目必然启用，无停用态）；值不受影响。"""
        async with _client(MANAGE | ISSUE) as (ac, session):
            product = await _mk_product(ac)
            std = await _mk_standard(ac, product["id"])
            report = await _mk_report(ac, product["id"], std)  # 录了 pH/水分

            ph = next(i for i in std["items"] if i["name_cn"] == "pH")
            water = next(i for i in std["items"] if i["name_cn"] == "水分")
            residue = next(i for i in std["items"] if i["name_cn"] == "炽灼残渣")
            # 仅保留 pH + 新增一列；水分（有值引用）与 炽灼残渣（无引用）被移除
            resp = await ac.put(
                f"/api/v1/qa/coa/standards/{std['id']}/items",
                json={
                    "items": [
                        {
                            "id": ph["id"],
                            "name_cn": "pH",
                            "value_type": "number",
                            "spec_text": "2.5～4.5",
                            "spec_min": 2.5,
                            "spec_max": 4.5,
                        },
                        {
                            "name_cn": "重金属",
                            "value_type": "number",
                            "spec_text": "≤10ppm",
                            "spec_max": 10.0,
                        },
                    ]
                },
            )
            assert resp.status_code == 200, resp.text
            items = {i["name_cn"]: i for i in resp.json()["data"]["items"]}
            assert "重金属" in items
            # 移除项（无论有无值引用）统一软删让号，详情不再列出
            assert "炽灼残渣" not in items
            assert "水分" not in items

            async def _row(item_id: str) -> CoaStandardItem:
                stmt = select(CoaStandardItem).where(
                    CoaStandardItem.id == UUID(item_id)
                )
                return (await session.execute(stmt)).scalar_one()

            water_row = await _row(water["id"])
            assert water_row.is_deleted is True  # 有值引用也软删（行保留，FK 有效）
            residue_row = await _row(residue["id"])
            assert residue_row.is_deleted is True

            # 报告值不受替换影响（历史值行仍引用软删行）
            detail = (await ac.get(f"/api/v1/qa/coa/reports/{report['id']}")).json()[
                "data"
            ]
            assert {UUID(v["item_id"]) for v in detail["values"]} >= {
                UUID(water["id"]),
                UUID(ph["id"]),
            }

    async def test_item_default_value_text_only(self):
        """text 型项目可配登记预填默认值；number 型配默认值 → 422。"""
        async with _client(MANAGE) as (ac, _):
            product = await _mk_product(ac)
            resp = await ac.post(
                "/api/v1/qa/coa/standards",
                json={
                    "product_id": product["id"],
                    "code": _uniq("DV"),
                    "name": "默认值标准",
                    "items": [
                        {
                            "name_cn": "外观",
                            "value_type": "text",
                            "spec_text": "白色粉末",
                            "default_value": "符合规定",
                        },
                        {"name_cn": "pH", "value_type": "number", "spec_min": 2.5},
                    ],
                },
            )
            assert resp.status_code == 201, resp.text
            items = {i["name_cn"]: i for i in resp.json()["data"]["items"]}
            assert items["外观"]["default_value"] == "符合规定"
            assert items["pH"]["default_value"] is None

            # number 型带默认值 → 422
            resp = await ac.post(
                "/api/v1/qa/coa/standards",
                json={
                    "product_id": product["id"],
                    "code": _uniq("DV"),
                    "name": "数值默认值标准",
                    "items": [
                        {
                            "name_cn": "水分",
                            "value_type": "number",
                            "default_value": "2.0%",
                        }
                    ],
                },
            )
            assert resp.status_code == 422

    async def test_standard_delete_guarded_by_reports(self):
        async with _client(MANAGE | ISSUE) as (ac, _):
            product = await _mk_product(ac)
            std = await _mk_standard(ac, product["id"])
            await _mk_report(ac, product["id"], std)
            resp = await ac.delete(f"/api/v1/qa/coa/standards/{std['id']}")
            assert resp.status_code == 409

            std2 = await _mk_standard(ac, product["id"])
            resp = await ac.delete(f"/api/v1/qa/coa/standards/{std2['id']}")
            assert resp.status_code == 200


# ─────────────────────── 矩阵同名项目合并列 ───────────────────────


class TestMatrixMergedColumns:
    """项目名称标准内唯一；跨标准同名（同 code）项目在矩阵中共用一列。"""

    async def test_same_name_items_merged_into_one_column(self):
        """两标准共享 水分 + 各自独有项 → 矩阵 columns 中 水分 恰一列且
        item_ids 含两标准的项目 id，两份报告的值都能落在该列。"""
        async with _client(MANAGE | ISSUE) as (ac, _):
            product = await _mk_product(ac)
            std1 = await _mk_standard(ac, product["id"], code="3201")
            std2 = await _mk_standard(
                ac,
                product["id"],
                code="3202",
                items=[
                    {
                        "name_cn": "水分",
                        "name_en": "Water",
                        "value_type": "number",
                        "spec_text": "≤4.0%",
                    },
                    {
                        "name_cn": "透光率",
                        "value_type": "number",
                        "spec_text": "≥90.0%",
                    },
                ],
            )
            await _mk_report(ac, product["id"], std1)  # pH + 水分
            water2 = next(i for i in std2["items"] if i["name_cn"] == "水分")
            trans = next(i for i in std2["items"] if i["name_cn"] == "透光率")
            await ac.post(
                "/api/v1/qa/coa/reports",
                json={
                    "product_id": product["id"],
                    "standard_id": std2["id"],
                    "batch_no": _uniq("HAF2622"),
                    "serial_no": _uniq("26"),
                    "values": [
                        {"item_id": water2["id"], "value_num": 2.8},
                        {"item_id": trans["id"], "value_num": 92.5},
                    ],
                },
            )

            matrix = (
                await ac.get(
                    f"/api/v1/qa/coa/reports/matrix?product_id={product['id']}"
                )
            ).json()["data"]
            # 列按标准顺序→项目顺序首现定位（std1 code=3201 在前）
            assert [c["code"] for c in matrix["columns"]] == [
                "ph",
                "水分water",
                "炽灼残渣",
                "透光率",
            ]
            water_col = next(c for c in matrix["columns"] if c["code"] == "水分water")
            water_ids = {
                i["id"]
                for s in matrix["standards"]
                for i in s["items"]
                if i["name_cn"] == "水分"
            }
            assert set(water_col["item_ids"]) == water_ids
            # 两标准规格不同 → 去重并列提示
            assert set(water_col["spec_texts"]) == {"≤5.0%", "≤4.0%"}
            # 两行报告都能在合并列取到值
            rows = matrix["rows"]
            assert len(rows) == 2
            for row in rows:
                hit = next(
                    (
                        row["value_map"][iid]
                        for iid in water_col["item_ids"]
                        if iid in row["value_map"]
                    ),
                    None,
                )
                assert hit is not None and hit["num"] is not None

    async def test_replace_rename_recomputes_code(self):
        """跨标准同名允许；改名后 code 同步重算（矩阵合并/docx 匹配依据）。"""
        async with _client(MANAGE) as (ac, _):
            product = await _mk_product(ac)
            std = await _mk_standard(ac, product["id"])
            # 同产品第二标准复用同名三件套 → 允许（跨标准不查重）
            other = await _mk_standard(ac, product["id"])
            assert other["item_count"] == 3

            ph = next(i for i in std["items"] if i["name_cn"] == "pH")
            resp = await ac.put(
                f"/api/v1/qa/coa/standards/{std['id']}/items",
                json={
                    "items": [
                        {"id": ph["id"], "name_cn": "酸度", "value_type": "number"}
                    ]
                },
            )
            assert resp.status_code == 200, resp.text
            items = resp.json()["data"]["items"]
            # 无引用的 水分/炽灼残渣 已软删让号，详情只剩改名后的 酸度
            assert [i["name_cn"] for i in items] == ["酸度"]
            assert items[0]["code"] == "酸度"  # code 缺省由当前名称重算

            # 改成与另一标准同名 → 仍允许
            resp = await ac.put(
                f"/api/v1/qa/coa/standards/{std['id']}/items",
                json={
                    "items": [
                        {"id": ph["id"], "name_cn": "水分", "value_type": "number"}
                    ]
                },
            )
            assert resp.status_code == 200, resp.text

    async def test_standard_delete_cascades_to_items(self):
        """删除标准时其项目随之软删（可删标准=无报告=项目无值引用）。"""
        async with _client(MANAGE) as (ac, session):
            product = await _mk_product(ac)
            std = await _mk_standard(ac, product["id"])
            resp = await ac.delete(f"/api/v1/qa/coa/standards/{std['id']}")
            assert resp.status_code == 200
            rows = (
                (
                    await session.execute(
                        select(CoaStandardItem).where(
                            CoaStandardItem.standard_id == UUID(std["id"])
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert rows and all(r.is_deleted for r in rows)


# ─────────────────────── 出具登记 ───────────────────────


class TestReports:
    async def test_batch_unique_per_standard(self):
        async with _client(MANAGE | ISSUE) as (ac, _):
            product = await _mk_product(ac)
            std = await _mk_standard(ac, product["id"])
            report = await _mk_report(ac, product["id"], std)
            resp = await ac.post(
                "/api/v1/qa/coa/reports",
                json={
                    "product_id": product["id"],
                    "standard_id": std["id"],
                    "batch_no": report["batch_no"],  # 同批同标准
                    "serial_no": _uniq("26"),
                },
            )
            assert resp.status_code == 409

    async def test_value_item_must_belong_to_standard(self):
        async with _client(MANAGE | ISSUE) as (ac, _):
            product = await _mk_product(ac)
            std = await _mk_standard(ac, product["id"])
            other = await _mk_standard(ac, product["id"])
            foreign = next(i for i in other["items"] if i["name_cn"] == "pH")
            resp = await ac.post(
                "/api/v1/qa/coa/reports",
                json={
                    "product_id": product["id"],
                    "standard_id": std["id"],
                    "batch_no": _uniq("HAF2699"),
                    "serial_no": _uniq("26"),
                    "values": [{"item_id": foreign["id"], "value_num": 3.0}],
                },
            )
            assert resp.status_code == 404

    async def test_update_values_full_replace(self):
        """PATCH 带 values = 全量替换（回归：service 曾对 model_dump 后的
        dict 按属性访问炸 500）；重复项目 400。"""
        async with _client(MANAGE | ISSUE) as (ac, _):
            product = await _mk_product(ac)
            std = await _mk_standard(ac, product["id"])
            report = await _mk_report(ac, product["id"], std)
            ph = next(i for i in std["items"] if i["name_cn"] == "pH")
            resp = await ac.patch(
                f"/api/v1/qa/coa/reports/{report['id']}",
                json={
                    "values": [
                        {"item_id": ph["id"], "value_num": 6.5},
                        {"item_id": ph["id"], "value_text": "6.5"},
                    ]
                },
            )
            assert resp.status_code == 400
            assert "结果值项目重复" in resp.json()["message"]
            resp = await ac.patch(
                f"/api/v1/qa/coa/reports/{report['id']}",
                json={"values": [{"item_id": ph["id"], "value_num": 6.5}]},
            )
            assert resp.status_code == 200, resp.text
            detail = resp.json()["data"]
            assert detail["values"] == [
                {
                    "item_id": ph["id"],
                    "value_num": 6.5,
                    "value_text": None,
                    "remark": None,
                }
            ]
            # 不带 values 的更新：值不动
            resp = await ac.patch(
                f"/api/v1/qa/coa/reports/{report['id']}",
                json={"remark": "补录备注"},
            )
            assert resp.status_code == 200
            assert resp.json()["data"]["values"] == detail["values"]

    async def test_standard_must_belong_to_product(self):
        async with _client(MANAGE | ISSUE) as (ac, _):
            product = await _mk_product(ac)
            product2 = await _mk_product(ac)
            std = await _mk_standard(ac, product2["id"])
            resp = await ac.post(
                "/api/v1/qa/coa/reports",
                json={
                    "product_id": product["id"],
                    "standard_id": std["id"],
                    "batch_no": _uniq("HAF2688"),
                    "serial_no": _uniq("26"),
                },
            )
            assert resp.status_code == 400

    async def test_serial_no_required(self):
        """流水号为内置必填批次字段：缺失 → 422。"""
        async with _client(MANAGE | ISSUE) as (ac, _):
            product = await _mk_product(ac)
            std = await _mk_standard(ac, product["id"])
            payload = {
                "product_id": product["id"],
                "standard_id": std["id"],
                "batch_no": _uniq("HAF2601"),
            }
            resp = await ac.post("/api/v1/qa/coa/reports", json=payload)
            assert resp.status_code == 422
            # 纯空白同样拒绝（清洗后为空）
            resp = await ac.post(
                "/api/v1/qa/coa/reports", json={**payload, "serial_no": " 　"}
            )
            assert resp.status_code == 422


async def _mk_product_with_batch_fields(
    ac: AsyncClient,
    fields: list[dict[str, Any]],
) -> dict[str, Any]:
    """建产品并配置自定义批次字段（产品默认字段集）。"""
    product = await _mk_product(ac)
    resp = await ac.put(
        f"/api/v1/qa/coa/products/{product['id']}/fields", json={"fields": fields}
    )
    assert resp.status_code == 200, resp.text
    return product


class TestReportBatchData:
    async def test_batch_data_mirror_custom_and_matrix_view(self):
        """固定列别名键镜像写列、自定义键进 JSONB；详情/矩阵按字段集合成
        batch_info（含内置 3 键：品名取产品、批号/流水号取报告头）。"""
        async with _client(MANAGE | ISSUE) as (ac, _):
            product = await _mk_product_with_batch_fields(
                ac,
                [
                    {
                        "key": "manufacturing_date",
                        "label_cn": "生产日期",
                        "field_type": "date",
                    },
                    {"key": "retest_date", "label_cn": "复验期", "field_type": "date"},
                    {"key": "appearance", "label_cn": "性状", "field_type": "text"},
                ],
            )
            std = await _mk_standard(ac, product["id"])
            report = await _mk_report(
                ac,
                product["id"],
                std,
                batch_data={
                    "manufacturing_date": "2026-07-01",
                    "retest_date": "2027-07-01",
                    "appearance": "白色粉末",
                },
            )
            # 镜像：manufacturing_date 命中生产日期固定列
            assert report["mfg_date"] == "2026-07-01"
            assert report["batch_info"] == {
                "product_name": product["name"],
                "batch_no": report["batch_no"],
                "serial_no": report["serial_no"],
                "manufacturing_date": "2026-07-01",
                "retest_date": "2027-07-01",
                "appearance": "白色粉末",
            }
            # 矩阵（按标准筛）：standards 带生效字段集，行带 batch_info 合成视图
            matrix = (
                await ac.get(
                    f"/api/v1/qa/coa/reports/matrix?product_id={product['id']}"
                    f"&standard_id={std['id']}"
                )
            ).json()["data"]
            assert [f["key"] for f in matrix["standards"][0]["batch_fields"]] == [
                "product_name",
                "batch_no",
                "serial_no",
                "manufacturing_date",
                "retest_date",
                "appearance",
            ]
            row = next(r for r in matrix["rows"] if r["id"] == report["id"])
            assert row["batch_info"]["retest_date"] == "2027-07-01"
            assert row["batch_info"]["appearance"] == "白色粉末"

    async def test_batch_data_guards(self):
        """未知键 / 内置键 / 非法日期 → 400。"""
        async with _client(MANAGE | ISSUE) as (ac, _):
            product = await _mk_product_with_batch_fields(
                ac, [{"key": "retest_date", "label_cn": "复验期", "field_type": "date"}]
            )
            std = await _mk_standard(ac, product["id"])
            base = {"product_id": product["id"], "standard_id": std["id"]}
            resp = await ac.post(
                "/api/v1/qa/coa/reports",
                json={
                    **base,
                    "batch_no": _uniq("HAF2611"),
                    "serial_no": _uniq("26"),
                    "batch_data": {"no_such_field": "x"},
                },
            )
            assert resp.status_code == 400
            assert "不在模板字段集中" in resp.json()["message"]
            resp = await ac.post(
                "/api/v1/qa/coa/reports",
                json={
                    **base,
                    "batch_no": _uniq("HAF2612"),
                    "serial_no": _uniq("26"),
                    "batch_data": {"batch_no": "X"},
                },
            )
            assert resp.status_code == 400
            assert "内置字段" in resp.json()["message"]
            resp = await ac.post(
                "/api/v1/qa/coa/reports",
                json={
                    **base,
                    "batch_no": _uniq("HAF2613"),
                    "serial_no": _uniq("26"),
                    "batch_data": {"retest_date": "不是日期"},
                },
            )
            assert resp.status_code == 400
            assert "不是有效日期" in resp.json()["message"]

    async def test_update_batch_data_full_replace(self):
        """batch_data 提供即全量替换：没给的键清空（固定列镜像一并清零），
        不带 batch_data 的更新不动批次字段。"""
        async with _client(MANAGE | ISSUE) as (ac, _):
            product = await _mk_product_with_batch_fields(
                ac,
                [
                    {
                        "key": "manufacturing_date",
                        "label_cn": "生产日期",
                        "field_type": "date",
                    },
                    {"key": "appearance", "label_cn": "性状", "field_type": "text"},
                ],
            )
            std = await _mk_standard(ac, product["id"])
            report = await _mk_report(
                ac,
                product["id"],
                std,
                batch_data={
                    "manufacturing_date": "2026-07-01",
                    "appearance": "白色粉末",
                },
            )
            resp = await ac.patch(
                f"/api/v1/qa/coa/reports/{report['id']}",
                json={"batch_data": {"appearance": "类白色粉末"}},
            )
            assert resp.status_code == 200, resp.text
            detail = resp.json()["data"]
            assert detail["mfg_date"] is None  # 固定列镜像清零
            assert detail["batch_info"]["appearance"] == "类白色粉末"
            assert "manufacturing_date" not in detail["batch_info"]
            # 不带 batch_data 的更新：批次字段不动
            resp = await ac.patch(
                f"/api/v1/qa/coa/reports/{report['id']}",
                json={"remark": "补录备注"},
            )
            assert resp.status_code == 200
            detail = resp.json()["data"]
            assert detail["batch_info"]["appearance"] == "类白色粉末"


# ─────────────────────── docx 导入（真实样本） ───────────────────────


async def _import_products_and_standard(ac: AsyncClient) -> dict[str, Any]:
    """用真实样本跑标准导入预览，再落库。返回 {product, standard}。"""
    resp = await ac.post(
        "/api/v1/qa/coa/standards/import-preview",
        files={
            "file": (
                "sample.docx",
                FIXTURE.read_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert resp.status_code == 200, resp.text
    preview = resp.json()["data"]
    # 共享开发库可能已有 HAF 产品（页面真实导入过）：匹配到或给建品草稿都合法
    if preview["product"] is None:
        assert preview["product_draft"]["code"] == "HAF"
    else:
        assert preview["product"]["code"] == "HAF"
    assert len(preview["standard_draft"]["items"]) == 30

    product = (
        await ac.post(
            "/api/v1/qa/coa/products",
            json={
                "code": _uniq("HAF"),
                "name": f"盐酸万古霉素{uuid4().hex[:6]}",
                "name_en": preview["product_draft"]["name_en"],
            },
        )
    ).json()["data"]
    draft = preview["standard_draft"]
    draft["product_id"] = product["id"]
    draft["code"] = _uniq("32")
    draft["raw_extract"] = preview["raw_extract"]
    standard = (await ac.post("/api/v1/qa/coa/standards", json=draft)).json()["data"]
    assert standard["item_count"] == 30
    assert standard["source"] == "import"
    return {"product": product, "standard": standard, "preview": preview}


class TestImportStandard:
    async def test_preview_parses_real_docx(self):
        async with _client(MANAGE) as (ac, _):
            resp = await ac.post(
                "/api/v1/qa/coa/standards/import-preview",
                files={
                    "file": ("s.docx", FIXTURE.read_bytes(), "application/octet-stream")
                },
            )
            assert resp.status_code == 200
            data = resp.json()["data"]
            draft = data["standard_draft"]
            assert draft["code"] == "HAF-3205-006"
            assert draft["name"] == "s"  # 名称默认取上传文件名（去扩展名）
            names = [i["name_cn"] for i in draft["items"]]
            assert "pH" in names
            van_b = next(i for i in draft["items"] if "万古霉素B" in i["name_cn"])
            assert van_b["spec_min"] == 93.0
            assert van_b["value_type"] == "number"
            # 结构模式提取：批次信息字段标签清单（key/type 系统生成）；
            # 品名/批号/流水号及同义变体恒为内置字段，不进草稿（raw 留底保留原文）
            fields = {f["key"]: f for f in data["batch_fields_draft"]}
            assert set(fields) == {"mfg_date", "retest_date"}
            assert fields["retest_date"]["label_cn"] == "复验期"
            assert fields["retest_date"]["field_type"] == "date"
            assert fields["mfg_date"]["field_type"] == "date"
            raw_labels = [
                f["label_cn"] for f in data["raw_extract"]["batch_info_fields"]
            ]
            assert raw_labels == ["品  名", "批  号", "生产日期", "复验期"]


class TestProductFields:
    """自定义字段全量替换 + 内置字段（品名/批号/流水号）恒定置顶必填。"""

    _BUILTIN_KEYS = ["product_name", "batch_no", "serial_no"]

    async def test_replace_and_list_roundtrip(self):
        async with _client(MANAGE) as (ac, _):
            product = await _mk_product(ac)
            url = f"/api/v1/qa/coa/products/{product['id']}/fields"
            resp = await ac.put(
                url,
                json={
                    "fields": [
                        {
                            "key": "retest_date",
                            "label_cn": "复验期",
                            "label_en": "Retest Date",
                            "field_type": "date",
                        },
                        {
                            "key": "storage_conditions",
                            "label_cn": "储存条件",
                            "label_en": "Storage Conditions",
                        },
                    ]
                },
            )
            assert resp.status_code == 200, resp.text
            listed = resp.json()["data"]
            # 内置 3 字段置顶（必填锁定），自定义字段顺延
            assert [f["key"] for f in listed] == [
                *self._BUILTIN_KEYS, "retest_date", "storage_conditions",
            ]
            builtin_rows = listed[:3]
            assert all(
                f["builtin"] is True and f["required"] is True and f["id"] is None
                for f in builtin_rows
            )
            assert [f["label_cn"] for f in builtin_rows] == ["品名", "批号", "流水号"]
            customs = listed[3:]
            assert customs[0]["field_type"] == "date"
            assert customs[1]["field_type"] == "text"  # 缺省 text
            assert all(f["builtin"] is False for f in customs)
            assert [f["sort_order"] for f in customs] == [0, 1]  # 缺省按载荷顺序

            # 全量替换语义：再 PUT 只剩新载荷（内置不受影响）
            resp = await ac.put(
                url, json={"fields": [{"key": "贸易项", "label_cn": "贸易项"}]}
            )
            assert resp.status_code == 200
            assert [f["key"] for f in resp.json()["data"]] == [
                *self._BUILTIN_KEYS, "贸易项",
            ]

            # GET 读取一致
            resp = await ac.get(url)
            assert [f["key"] for f in resp.json()["data"]] == [
                *self._BUILTIN_KEYS, "贸易项",
            ]

    async def test_builtin_keys_rejected(self):
        """品名/批号/流水号及同义变体不可作为自定义字段配置。"""
        async with _client(MANAGE) as (ac, _):
            product = await _mk_product(ac)
            url = f"/api/v1/qa/coa/products/{product['id']}/fields"
            for key in ("product_name", "batch_no", "serial_no", "series", "Lot No."):
                resp = await ac.put(
                    url, json={"fields": [{"key": key, "label_cn": "自定义"}]}
                )
                assert resp.status_code == 400, key
            # 同义中文标签同样拒绝（防与内置重复展示）
            resp = await ac.put(
                url, json={"fields": [{"key": "custom_1", "label_cn": "流水号"}]}
            )
            assert resp.status_code == 400

    async def test_empty_fields_keep_builtin(self):
        """空载荷=清空自定义字段，内置 3 字段仍恒定返回。"""
        async with _client(MANAGE) as (ac, _):
            product = await _mk_product(ac)
            url = f"/api/v1/qa/coa/products/{product['id']}/fields"
            resp = await ac.put(
                url,
                json={"fields": [{"key": "贸易项", "label_cn": "贸易项"}]},
            )
            assert resp.status_code == 200
            resp = await ac.put(url, json={"fields": []})
            assert resp.status_code == 200
            assert [f["key"] for f in resp.json()["data"]] == self._BUILTIN_KEYS

    async def test_read_can_list_but_not_replace(self):
        """读码鉴权：GET 过读权限（404=仅产品不存在），PUT 无 manage → 403。"""
        async with _client(READ) as (ac, _):
            resp = await ac.get(f"/api/v1/qa/coa/products/{uuid4()}/fields")
            assert resp.status_code == 404
            resp = await ac.put(
                f"/api/v1/qa/coa/products/{uuid4()}/fields", json={"fields": []}
            )
            assert resp.status_code == 403

    async def test_duplicate_key_in_payload_400(self):
        async with _client(MANAGE) as (ac, _):
            product = await _mk_product(ac)
            resp = await ac.put(
                f"/api/v1/qa/coa/products/{product['id']}/fields",
                json={
                    "fields": [
                        {"key": "trade_item", "label_cn": "贸易项"},
                        {"key": "trade_item", "label_cn": "贸易项2"},
                    ]
                },
            )
            assert resp.status_code == 400

    async def test_missing_product_404(self):
        async with _client(MANAGE) as (ac, _):
            resp = await ac.get(f"/api/v1/qa/coa/products/{uuid4()}/fields")
            assert resp.status_code == 404


class TestStandardFieldOverride:
    """产品默认 + 标准覆盖：生效集 = 内置置顶 +（覆盖 ?? 产品默认）。"""

    _BUILTIN_KEYS = {"product_name", "batch_no", "serial_no"}
    _DEFAULTS = [
        {"key": "storage_conditions", "label_cn": "储存条件", "label_en": "Storage Conditions"},
        {"key": "retest_date", "label_cn": "复验期", "field_type": "date"},
    ]

    async def _mk_product_with_defaults(self, ac: AsyncClient) -> dict[str, Any]:
        product = await _mk_product(ac)
        resp = await ac.put(
            f"/api/v1/qa/coa/products/{product['id']}/fields",
            json={"fields": self._DEFAULTS},
        )
        assert resp.status_code == 200, resp.text
        return product

    async def test_create_same_as_defaults_no_override(self):
        """创建标准带的字段集与产品默认一致 → 不落覆盖，详情生效集=默认。"""
        async with _client(MANAGE) as (ac, _):
            product = await self._mk_product_with_defaults(ac)
            resp = await ac.post(
                "/api/v1/qa/coa/standards",
                json={
                    "product_id": product["id"],
                    "code": _uniq("SO"),
                    "name": "同默认标准",
                    "items": [],
                    "batch_fields": self._DEFAULTS,  # 顺序打乱也视为一致
                },
            )
            assert resp.status_code == 201, resp.text
            detail = resp.json()["data"]
            assert detail["batch_fields_custom"] is False
            assert {f["key"] for f in detail["batch_fields"]} == self._BUILTIN_KEYS | {
                "storage_conditions", "retest_date",
            }

    async def test_create_different_falls_back_to_override(self):
        """创建标准带的字段集有差异 → 落标准覆盖，详情标记自定义+返回产品默认。"""
        async with _client(MANAGE) as (ac, _):
            product = await self._mk_product_with_defaults(ac)
            draft = [*self._DEFAULTS, {"key": "trade_item", "label_cn": "贸易项"}]
            resp = await ac.post(
                "/api/v1/qa/coa/standards",
                json={
                    "product_id": product["id"],
                    "code": _uniq("SO"),
                    "name": "差异标准",
                    "items": [],
                    "batch_fields": draft,
                },
            )
            assert resp.status_code == 201, resp.text
            detail = resp.json()["data"]
            assert detail["batch_fields_custom"] is True
            assert {f["key"] for f in detail["batch_fields"]} == self._BUILTIN_KEYS | {
                "storage_conditions", "retest_date", "trade_item",
            }
            # 产品默认一并返回（前端差异标注用），不受覆盖影响
            assert {f["key"] for f in detail["product_fields"]} == self._BUILTIN_KEYS | {
                "storage_conditions", "retest_date",
            }

    async def test_create_without_fields_uses_defaults(self):
        """未传 batch_fields 的新标准直接用产品默认。"""
        async with _client(MANAGE) as (ac, _):
            product = await self._mk_product_with_defaults(ac)
            std = await _mk_standard(ac, product["id"])
            resp = await ac.get(f"/api/v1/qa/coa/standards/{std['id']}")
            detail = resp.json()["data"]
            assert detail["batch_fields_custom"] is False
            assert [f["key"] for f in detail["batch_fields"]][:3] == [
                "product_name", "batch_no", "serial_no",
            ]
            assert len(detail["batch_fields"]) == 5  # 3 内置 + 2 默认

    async def test_replace_and_restore_override(self):
        """PUT 写覆盖 → 生效集切换；DELETE 恢复产品默认。"""
        async with _client(MANAGE) as (ac, _):
            product = await self._mk_product_with_defaults(ac)
            std = await _mk_standard(ac, product["id"])
            url = f"/api/v1/qa/coa/standards/{std['id']}/fields"
            resp = await ac.put(
                url,
                json={"fields": [{"key": "exp_date", "label_cn": "有效期", "field_type": "date"}]},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
            assert data["batch_fields_custom"] is True
            assert [f["key"] for f in data["batch_fields"]] == [
                "product_name", "batch_no", "serial_no", "exp_date",
            ]

            resp = await ac.delete(url)
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["batch_fields_custom"] is False
            assert {f["key"] for f in data["batch_fields"]} == self._BUILTIN_KEYS | {
                "storage_conditions", "retest_date",
            }

    async def test_empty_override_is_custom_empty_set(self):
        """PUT 空列表 = 显式空自定义集（仅内置 3 字段），不回落产品默认；
        DELETE 才恢复默认。"""
        async with _client(MANAGE) as (ac, _):
            product = await self._mk_product_with_defaults(ac)
            std = await _mk_standard(ac, product["id"])
            url = f"/api/v1/qa/coa/standards/{std['id']}/fields"
            resp = await ac.put(url, json={"fields": []})
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
            assert data["batch_fields_custom"] is True
            assert [f["key"] for f in data["batch_fields"]] == [
                "product_name", "batch_no", "serial_no",
            ]
            detail = (
                await ac.get(f"/api/v1/qa/coa/standards/{std['id']}")
            ).json()["data"]
            assert detail["batch_fields_custom"] is True
            assert [f["key"] for f in detail["batch_fields"]] == [
                "product_name", "batch_no", "serial_no",
            ]
            restored = (await ac.delete(url)).json()["data"]
            assert restored["batch_fields_custom"] is False
            assert "retest_date" in {f["key"] for f in restored["batch_fields"]}

    async def test_create_with_explicit_empty_fields_overrides(self):
        """创建标准显式传空列表 = 空自定义集（覆盖产品默认）。"""
        async with _client(MANAGE) as (ac, _):
            product = await self._mk_product_with_defaults(ac)
            resp = await ac.post(
                "/api/v1/qa/coa/standards",
                json={
                    "product_id": product["id"],
                    "code": _uniq("SO"),
                    "name": "空字段标准",
                    "items": [],
                    "batch_fields": [],
                },
            )
            assert resp.status_code == 201, resp.text
            detail = resp.json()["data"]
            assert detail["batch_fields_custom"] is True
            assert [f["key"] for f in detail["batch_fields"]] == [
                "product_name", "batch_no", "serial_no",
            ]

    async def test_override_rejects_builtin_keys(self):
        """标准覆盖同样拒绝内置保留键。"""
        async with _client(MANAGE) as (ac, _):
            product = await self._mk_product_with_defaults(ac)
            std = await _mk_standard(ac, product["id"])
            resp = await ac.put(
                f"/api/v1/qa/coa/standards/{std['id']}/fields",
                json={"fields": [{"key": "serial_no", "label_cn": "流水号"}]},
            )
            assert resp.status_code == 400

    async def test_override_requires_manage(self):
        async with _client(READ) as (ac, _):
            resp = await ac.put(
                f"/api/v1/qa/coa/standards/{uuid4()}/fields", json={"fields": []}
            )
            assert resp.status_code == 403


class TestImportReportAndMatrix:
    async def test_full_chain_import_report_and_matrix(self):
        async with _client(MANAGE | ISSUE) as (ac, _):
            ctx = await _import_products_and_standard(ac)
            product, standard = ctx["product"], ctx["standard"]

            # 报告导入预览：产品短码被随机化了 → 显式传 standard_id 匹配
            resp = await ac.post(
                "/api/v1/qa/coa/reports/import-preview",
                params={"standard_id": standard["id"]},
                files={
                    "file": ("s.docx", FIXTURE.read_bytes(), "application/octet-stream")
                },
            )
            assert resp.status_code == 200, resp.text
            preview = resp.json()["data"]
            assert preview["standard"]["id"] == standard["id"]
            assert len(preview["matched_items"]) == 30
            assert preview["unmatched_items"] == []
            ph = next(m for m in preview["matched_items"] if m["name"] == "pH")
            assert ph["value_num"] == 2.85

            # 落库（导入路径：raw_extract 留底 → source=import）
            draft = preview["report_draft"]
            report = (
                await ac.post(
                    "/api/v1/qa/coa/reports",
                    json={
                        **draft,
                        "product_id": product["id"],
                        "standard_id": standard["id"],
                        "raw_extract": preview["raw_extract"],
                        "values": [
                            {
                                "item_id": m["item_id"],
                                "value_num": m["value_num"],
                                "value_text": m["value_text"],
                            }
                            for m in preview["matched_items"]
                        ],
                    },
                )
            ).json()["data"]
            assert report["source"] == "import"
            assert report["serial_no"] == "26081215"
            assert len(report["values"]) == 30

            # 矩阵：产品维度，30 列 × 1 行
            matrix = (
                await ac.get(
                    f"/api/v1/qa/coa/reports/matrix?product_id={product['id']}"
                )
            ).json()["data"]
            assert len(matrix["standards"]) == 1
            assert len(matrix["standards"][0]["items"]) == 30
            assert len(matrix["rows"]) == 1
            row = matrix["rows"][0]
            assert row["batch_no"] == "HAF2607025A"
            ph_col = next(
                i for i in matrix["standards"][0]["items"] if i["name_cn"] == "pH"
            )
            assert row["value_map"][ph_col["id"]]["num"] == 2.85

    async def test_import_maps_dynamic_batch_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """docx 里的模板动态字段（复验期）按生效字段键回写，确认时落 batch_data。"""
        async with _client(MANAGE | ISSUE) as (ac, _):
            product = await _mk_product_with_batch_fields(
                ac, [{"key": "retest_date", "label_cn": "复验期", "field_type": "date"}]
            )
            std = await _mk_standard(ac, product["id"])
            parse = coa_ai_parse._build_parse(
                {
                    "batch_info": {"batch_no": _uniq("IMP2607")},
                    "batch_info_fields": [
                        {
                            "label_cn": "复验期",
                            "label_en": "Retest Date",
                            "value": "2027-07-01",
                        }
                    ],
                    "items": [],
                }
            )

            async def _fake(data: bytes, filename: str = "coa.docx", *, mode: str = "values"):
                return parse

            monkeypatch.setattr(issuance, "parse_docx_ai", _fake)
            resp = await ac.post(
                "/api/v1/qa/coa/reports/import-preview",
                params={"standard_id": std["id"]},
                files={"file": ("d.docx", b"docx-bytes", "application/octet-stream")},
            )
            assert resp.status_code == 200, resp.text
            preview = resp.json()["data"]
            assert preview["batch_dynamic"] == [
                {"key": "retest_date", "label_cn": "复验期", "value": "2027-07-01"}
            ]
            report = await ac.post(
                "/api/v1/qa/coa/reports",
                json={
                    "product_id": product["id"],
                    "standard_id": std["id"],
                    "batch_no": _uniq("IMP2607"),
                    "serial_no": _uniq("26"),
                    "batch_data": {
                        d["key"]: d["value"] for d in preview["batch_dynamic"]
                    },
                },
            )
            assert report.status_code == 201, report.text
            assert report.json()["data"]["batch_info"]["retest_date"] == "2027-07-01"

    async def test_legacy_mid_segment_standard_code_matches(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """存量标准按旧口径（编号中缀 3205）建码，新建议是整段 → 仍要命中。"""
        async with _client(MANAGE | ISSUE) as (ac, _):
            # 产品码必须是纯字母（_suggest_codes 只认 isalpha 段）
            product_code = "LEG" + "".join(
                c for c in uuid4().hex.upper() if c.isalpha()
            )[:5]
            product = await _mk_product(ac, code=product_code)
            std_code = str(uuid4().int % 1_000_000)
            std = await _mk_standard(ac, product["id"], code=std_code)
            parse = coa_ai_parse._build_parse(
                {"report_no": f"COA-{product_code}-{std_code}-006", "items": []}
            )
            assert parse.suggested_standard_code == f"{product_code}-{std_code}-006"

            async def _fake(data: bytes, filename: str = "coa.docx", *, mode: str = "values"):
                return parse

            monkeypatch.setattr(issuance, "parse_docx_ai", _fake)
            resp = await ac.post(
                "/api/v1/qa/coa/reports/import-preview",
                files={"file": ("legacy.docx", b"docx-bytes", "application/octet-stream")},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["data"]["standard"]["id"] == std["id"]

    async def test_import_unmatched_not_merged(self):
        """docx 项目在标准中不存在 → 预览标未命中；确认只录命中值，
        未命中项不并入标准（导入不改标准配置，扩项目走标准配置维护）。"""
        async with _client(MANAGE | ISSUE) as (ac, _):
            ctx = await _import_products_and_standard(ac)
            product, standard = ctx["product"], ctx["standard"]

            resp = await ac.post(
                "/api/v1/qa/coa/reports/import-preview",
                params={"standard_id": standard["id"]},
                files={
                    "file": ("s.docx", FIXTURE.read_bytes(), "application/octet-stream")
                },
            )
            preview = resp.json()["data"]
            # 标准由同一 docx 生成 → 全命中；人造未命中：删掉 pH 再导
            keep = [
                {
                    "id": i["id"],
                    "name_cn": i["name_cn"],
                    "name_en": i["name_en"],
                    "value_type": i["value_type"],
                    "spec_text": i["spec_text"],
                    "spec_min": i["spec_min"],
                    "spec_max": i["spec_max"],
                    "sort_order": i["sort_order"],
                }
                for i in standard["items"]
                if i["name_cn"] != "pH"
            ]
            replaced = (
                await ac.put(
                    f"/api/v1/qa/coa/standards/{standard['id']}/items",
                    json={"items": keep},
                )
            ).json()["data"]
            assert "pH" not in {i["name_cn"] for i in replaced["items"]}

            resp = await ac.post(
                "/api/v1/qa/coa/reports/import-preview",
                params={"standard_id": standard["id"]},
                files={
                    "file": ("s.docx", FIXTURE.read_bytes(), "application/octet-stream")
                },
            )
            preview = resp.json()["data"]
            assert len(preview["unmatched_items"]) == 1
            assert preview["unmatched_items"][0]["name_cn"] == "pH"
            assert preview["unmatched_items"][0]["value_num"] == 2.85

            # 确认：只录命中值；未命中项（pH）不并入标准、不落值
            draft = preview["report_draft"]
            report = await ac.post(
                "/api/v1/qa/coa/reports",
                json={
                    **draft,
                    "product_id": product["id"],
                    "standard_id": standard["id"],
                    "raw_extract": preview["raw_extract"],
                    "values": [
                        {
                            "item_id": m["item_id"],
                            "value_num": m["value_num"],
                            "value_text": m["value_text"],
                        }
                        for m in preview["matched_items"]
                    ],
                },
            )
            assert report.status_code == 201, report.text
            values = report.json()["data"]["values"]
            assert len(values) == 29  # 仅命中项；未命中的 pH 不落值
            assert "pH" not in {v.get("item_id") for v in values}
            # 标准项目集不被导入改动：pH 仍不在标准中
            detail = (
                await ac.get(f"/api/v1/qa/coa/standards/{standard['id']}")
            ).json()["data"]
            assert "pH" not in {i["name_cn"] for i in detail["items"]}

    async def test_import_cn_only_fallback_match(self, monkeypatch: pytest.MonkeyPatch):
        """英文名转写错误（flash 抄长词掉字符，Monodechlorovancomycin→…vanomycin）
        导致中英拼接键失配 → 中文名-only 键兜底唯一命中：仍算命中，
        不落标准外、不算缺失。"""
        async with _client(MANAGE | ISSUE) as (ac, _):
            ctx = await _import_products_and_standard(ac)
            standard = ctx["standard"]
            payload = json.loads(
                (Path(__file__).parent / "fixtures" / "coa_ai_payload.json").read_text()
            )
            for item in payload["items"]:
                if item["name_cn"] == "单去氯万古霉素":
                    item["name_en"] = "Monodechlorovanomycin"  # 掉一个 c
            parse = coa_ai_parse._build_parse(payload)

            async def _fake(data: bytes, filename: str = "coa.docx", *, mode: str = "values"):
                return parse

            monkeypatch.setattr(issuance, "parse_docx_ai", _fake)
            resp = await ac.post(
                "/api/v1/qa/coa/reports/import-preview",
                params={"standard_id": standard["id"]},
                files={
                    "file": ("typo.docx", FIXTURE.read_bytes(), "application/octet-stream")
                },
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
            assert "单去氯万古霉素" in {m["name"] for m in data["matched_items"]}
            assert "单去氯万古霉素" not in {
                u["name_cn"] for u in data["unmatched_items"]
            }
            assert "单去氯万古霉素" not in {
                i["name_cn"] for i in data["missing_items"]
            }


# ─────────────────────── 字符串入参统一清洗 ───────────────────────


class TestInputCleaning:
    """schema 层收口：NFKC（全角→半角）+ 去零宽/BOM 等不可见字符 + 去首尾空白。

    必填清洗后为空 → 422；可空清洗后为空 → 归一 None。覆盖产品/标准/项目/
    报告头/结果值全部可编辑字段（含直接 API 调用，不依赖前端 trim）。
    """

    async def test_product_fields_cleaned(self):
        async with _client(MANAGE) as (ac, _):
            product = await _mk_product(
                ac,
                name="　酒石酸\u200b万古霉素\u00a0",  # 全角空格+零宽字符+NBSP
                name_en="　Ｖａｎｃｏｍｙｃｉｎ　",  # 全角字母
                remark="  冷藏保存  ",
            )
            assert product["name"] == "酒石酸万古霉素"
            assert product["name_en"] == "Vancomycin"
            assert product["remark"] == "冷藏保存"

    async def test_product_blank_name_rejected(self):
        """纯空白/零宽字符满足 min_length=1 但清洗后为空 → 422。"""
        async with _client(MANAGE) as (ac, _):
            resp = await ac.post(
                "/api/v1/qa/coa/products",
                json={"code": "BLANK-1", "name": " \u200b\u3000"},
            )
            assert resp.status_code == 422

    async def test_standard_and_item_fields_cleaned(self):
        async with _client(MANAGE) as (ac, _):
            product = await _mk_product(ac)
            std = await _mk_standard(
                ac,
                product["id"],
                name="　ＵＳＰ客户标准　",
                customer="  海外客户A  ",
                version="　Ｖ2　",
                items=[
                    {
                        "name_cn": "　水分　",
                        "name_en": " Water ",
                        "unit": " % ",
                        "spec_text": " ≤5.0% ",
                        "remark": "  重点关注  ",
                    }
                ],
            )
            assert std["name"] == "USP客户标准"
            assert std["customer"] == "海外客户A"
            assert std["version"] == "V2"
            item = std["items"][0]
            assert item["name_cn"] == "水分"
            assert item["name_en"] == "Water"
            assert item["unit"] == "%"
            assert item["spec_text"] == "≤5.0%"
            assert item["remark"] == "重点关注"
            # 清洗不改归一化口径：code 仍由中英文名确定性生成
            assert item["code"] == "水分water"

    async def test_item_blank_name_rejected(self):
        async with _client(MANAGE) as (ac, _):
            product = await _mk_product(ac)
            resp = await ac.post(
                "/api/v1/qa/coa/standards",
                json={
                    "product_id": product["id"],
                    "code": _uniq("BK"),
                    "name": "空白项目名标准",
                    "items": [{"name_cn": " \u200b\u3000 "}],
                },
            )
            assert resp.status_code == 422

    async def test_report_fields_and_values_cleaned(self):
        async with _client(MANAGE | ISSUE) as (ac, _):
            product = await _mk_product(ac)
            std = await _mk_standard(ac, product["id"])
            water = next(i for i in std["items"] if i["name_cn"] == "水分")
            report = await _mk_report(
                ac,
                product["id"],
                std,
                serial_no=" 26081215 ",
                packaging="  10kg/桶　",
                values=[
                    {
                        "item_id": water["id"],
                        "value_num": 2.3,
                        "value_text": " 2.3% ",
                    }
                ],
            )
            assert report["serial_no"] == "26081215"
            assert report["packaging"] == "10kg/桶"
            assert report["values"][0]["value_text"] == "2.3%"
