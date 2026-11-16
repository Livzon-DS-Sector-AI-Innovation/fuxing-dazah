"""QA COA 域 API 测试：产品/标准 CRUD、项目替换守卫、矩阵同名项目合并列、
docx 导入预览、出具登记唯一约束、导入匹配与矩阵透视。

沿用 test_apr_api 的 harness：覆盖 get_db / get_current_user 并 patch 权限
集合，整条用例共用一个最终回滚的会话；随机前缀防共享开发库冲突。
docx 导入用例使用真实样本 fixture（coa_haf_sample.docx，30 项）。
"""

from __future__ import annotations

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
from app.platform.identity.deps import get_current_user
from app.platform.identity.models import User
from tests.conftest import _test_session_factory

READ = {"qa:coa:read"}
WILDCARD_READ = {"qa:*:read"}
MANAGE = READ | {"qa:coa:standard:manage"}
ISSUE = READ | {"qa:coa:issue:create"}

FIXTURE = Path(__file__).parent / "fixtures" / "coa_haf_sample.docx"

pytestmark = pytest.mark.anyio


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
        "report_no": _uniq("COA-XX-0000-"),
        "batch_no": _uniq("HAF2607"),
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
        """被报告值引用的项目移除 → 停用保留；无引用 → 软删让号；值不受影响。"""
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
            assert "炽灼残渣" not in items  # 无引用 → 软删让号，详情不列
            assert items["水分"]["is_active"] is False  # 有值引用 → 停用保留

            async def _row(item_id: str) -> CoaStandardItem:
                stmt = select(CoaStandardItem).where(
                    CoaStandardItem.id == UUID(item_id)
                )
                return (await session.execute(stmt)).scalar_one()

            water_row = await _row(water["id"])
            assert water_row.is_active is False and water_row.is_deleted is False
            residue_row = await _row(residue["id"])
            assert residue_row.is_deleted is True  # 无引用 → 软删让号

            # 报告值不受替换影响
            detail = (await ac.get(f"/api/v1/qa/coa/reports/{report['id']}")).json()[
                "data"
            ]
            assert {UUID(v["item_id"]) for v in detail["values"]} >= {
                UUID(water["id"]),
                UUID(ph["id"]),
            }

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
                    {"name_cn": "透光率", "value_type": "number", "spec_text": "≥90.0%"},
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
                    "report_no": _uniq("COA-MG-0000-"),
                    "batch_no": _uniq("HAF2622"),
                    "values": [
                        {"item_id": water2["id"], "value_num": 2.8},
                        {"item_id": trans["id"], "value_num": 92.5},
                    ],
                },
            )

            matrix = (
                await ac.get(f"/api/v1/qa/coa/reports/matrix?product_id={product['id']}")
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
    async def test_report_no_global_unique(self):
        async with _client(MANAGE | ISSUE) as (ac, _):
            product = await _mk_product(ac)
            std = await _mk_standard(ac, product["id"])
            report = await _mk_report(ac, product["id"], std)
            # 另一产品另一标准，同编号 → 仍 409（全局唯一）
            product2 = await _mk_product(ac)
            std2 = await _mk_standard(ac, product2["id"])
            resp = await ac.post(
                "/api/v1/qa/coa/reports",
                json={
                    "product_id": product2["id"],
                    "standard_id": std2["id"],
                    "report_no": report["report_no"],
                    "batch_no": _uniq("OTHER"),
                },
            )
            assert resp.status_code == 409

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
                    "report_no": _uniq("COA-YY-0000-"),
                    "batch_no": report["batch_no"],  # 同批同标准
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
                    "report_no": _uniq("COA-ZZ-0000-"),
                    "batch_no": _uniq("HAF2699"),
                    "values": [{"item_id": foreign["id"], "value_num": 3.0}],
                },
            )
            assert resp.status_code == 404

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
                    "report_no": _uniq("COA-PP-0000-"),
                    "batch_no": _uniq("HAF2688"),
                },
            )
            assert resp.status_code == 400


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
            draft = resp.json()["data"]["standard_draft"]
            assert draft["code"] == "3205"
            names = [i["name_cn"] for i in draft["items"]]
            assert "pH" in names
            van_b = next(i for i in draft["items"] if "万古霉素B" in i["name_cn"])
            assert van_b["spec_min"] == 93.0
            assert van_b["value_type"] == "number"


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
            # report_no 全局唯一且开发库已有页面导入的同号真实报告 → 随机化
            draft["report_no"] = _uniq("COA-XX-0000-")
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

    async def test_import_unmatched_merge_into_standard(self):
        """docx 项目在标准中不存在 → 预览标未命中，确认时并入标准并落值。"""
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

            # 确认：unmatched 勾选并入标准（new_items 带值），其余走 values
            draft = preview["report_draft"]
            draft["report_no"] = _uniq("COA-UM-0000-")
            un = preview["unmatched_items"][0]
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
                    "new_items": [
                        {
                            "name_cn": un["name_cn"],
                            "name_en": un["name_en"],
                            "value_type": un["value_type"],
                            "spec_text": un["spec_text"],
                            "spec_min": un["spec_min"],
                            "spec_max": un["spec_max"],
                            "value_num": un["value_num"],
                            "value_text": un["value_text"],
                        }
                    ],
                },
            )
            assert report.status_code == 201, report.text
            values = report.json()["data"]["values"]
            assert len(values) == 30  # 29 命中 + 1 并入
