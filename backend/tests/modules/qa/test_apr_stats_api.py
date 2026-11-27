"""QA 年度产品审核（PQR）统计口径与报告测试：CPK 家族统计、表尾全量统计行、
段级 Word 年度回顾报告。

统计口径对齐独立工具 qa_year_review（stats.py/charts.py/gen_template.py）：
±4σ / 规格公差 T / 中心值 U / ca / cp / CPKu / CPKl / CPK / CPK级别 /
警告限（U±0.5·T/2）/ 行动限（U±0.8·T/2）；单限只算单侧 CPK，σ=0 或样本
不足时 CPK 系不输出。沿用 test_apr_api 的 harness 模式。
"""

from __future__ import annotations

import io
import zipfile
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
MANAGE = READ | {"qa:apr:manage"}
ENTER = READ | {"qa:apr:enter"}
EXPORT = READ | {"qa:apr:export"}

# 表尾统计行完整清单（对齐 qa_year_review STAT_KEYS_CN 22 项 + 未检出透明行）
FULL_STAT_ROWS = [
    "标准上限(USL)",
    "标准下限(LSL)",
    "平均值",
    "最大值",
    "最小值",
    "STDEVA",
    "+3σ",
    "-3σ",
    "+4σ",
    "-4σ",
    "规格公差(T)",
    "规格中心值(U)",
    "制程准确度(ca)",
    "制程精密度(cp)",
    "制程能力(CPKu)",
    "制程能力(CPKl)",
    "制程能力(CPK)",
    "CPK级别",
    "警告限上限",
    "警告限下限",
    "行动限上限",
    "行动限下限",
]


async def _ensure_test_user(session: AsyncSession) -> User:
    stmt = select(User).where(User.is_deleted == False).limit(1)  # noqa: E712
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing
    user = User(name="qa-apr统计测试用户", employee_no="QA-APR-STAT-001")
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
            # 不拷贝：测试内可动态增删权限码（如先 seed 再撤权验证 403）
            return perms if perms is not None else set()

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
        "name": "卡那霉素",
        "name_en": "Kanamycin",
    }
    payload.update(overrides)
    payload["name"] = f"{payload['name']}{uuid4().hex[:6]}"
    resp = await ac.post("/api/v1/qa/apr/products", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def _mk_section(ac: AsyncClient, product_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "product_id": product_id,
        "name": "成品检验-USP",
        "data_kind": "inspection",
        "market": "US",
    }
    payload.update(overrides)
    resp = await ac.post("/api/v1/qa/apr/sections", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def _mk_item(ac: AsyncClient, section_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "section_id": section_id,
        "category": "test",
        "name_cn": "酸碱度",
        "value_type": "number",
        "spec_min": 4.0,
        "spec_max": 4.6,
    }
    payload.update(overrides)
    resp = await ac.post("/api/v1/qa/apr/items", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def _mk_batch(
    ac: AsyncClient, section_id: str, seq: int, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "section_id": section_id,
        "year": 2025,
        "batch_no": _code("B"),
        "seq": seq,
    }
    payload.update(overrides)
    resp = await ac.post("/api/v1/qa/apr/batches", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def _fill_values(
    ac: AsyncClient,
    section_id: str,
    item_id: str,
    values: list[Any],
    *,
    year: int = 2025,
) -> None:
    """按顺序登记 len(values) 个批次并逐批填值；str 表示文字结果。"""
    for i, v in enumerate(values, start=1):
        batch = await _mk_batch(ac, section_id, seq=i, year=year)
        cell: dict[str, Any] = (
            {"item_id": item_id, "value_text": v}
            if isinstance(v, str)
            else {"item_id": item_id, "value_num": v}
        )
        resp = await ac.put(
            f"/api/v1/qa/apr/batches/{batch['id']}/values", json={"values": [cell]}
        )
        assert resp.status_code == 200, resp.text


# ───────────────────── 列定义统计精度 ─────────────────────


def test_build_trend_points_shared_by_trend_and_report() -> None:
    """页面趋势与 Word 报告图共用同一点集构建（单一数据管线）：

    ND（未检出）zero 口径按 0 进点进样本、exclude 不进点不进样本但计数；
    OOS/OOT 状态逐点判定；顺序按传入序列（load_numeric_series 已按批序）。
    """
    from app.modules.qa.service.apr.analysis import build_trend_points

    series = [
        ("b1", "DT2501001", 1, 2025, 1, 4.3, None),
        ("b2", "DT2501002", 2, 2025, 1, None, "未检出"),
        ("b3", "DT2501003", 3, 2025, 2, 4.7, None),
    ]
    points, values, nd_count = build_trend_points(
        series,
        nd_policy="zero",
        spec_min=4.0,
        spec_max=4.6,
        oot_min=None,
        oot_max=None,
    )
    assert [p["value"] for p in points] == [4.3, 0.0, 4.7]
    assert values == [4.3, 0.0, 4.7]
    assert nd_count == 1
    assert points[1]["nd"] is True
    assert points[1]["text"] == "未检出"
    assert [p["status"] for p in points] == ["normal", "normal", "oos"]
    assert [p["row_seq"] for p in points] == [1, 1, 2]

    # exclude：ND 不进点也不进样本，nd_count 仍透明
    points, values, nd_count = build_trend_points(
        series,
        nd_policy="exclude",
        spec_min=4.0,
        spec_max=4.6,
        oot_min=None,
        oot_max=None,
    )
    assert [p["batch_no"] for p in points] == ["DT2501001", "DT2501003"]
    assert values == [4.3, 4.7]
    assert nd_count == 1


async def test_item_stat_precision_roundtrip() -> None:
    """stat_precision：建列携带、默认空、可编辑、批量建列透传。"""
    async with _client(MANAGE) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        item = await _mk_item(ac, section["id"], stat_precision=3)
        assert item["stat_precision"] == 3
        # 未传 → None（导出/报告侧按 2 位处理）
        plain = await _mk_item(ac, section["id"], name_cn="水分")
        assert plain["stat_precision"] is None
        # 编辑
        resp = await ac.patch(
            f"/api/v1/qa/apr/items/{item['id']}", json={"stat_precision": 4}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["stat_precision"] == 4
        # 越界拒绝
        resp = await ac.patch(
            f"/api/v1/qa/apr/items/{item['id']}", json={"stat_precision": 7}
        )
        assert resp.status_code == 422
        # 批量建列透传
        resp = await ac.post(
            f"/api/v1/qa/apr/sections/{section['id']}/items/bulk",
            json={
                "items": [
                    {"name_cn": "残留溶剂", "category": "test", "stat_precision": 0}
                ]
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["data"]["items"][0]["stat_precision"] == 0


# ───────────────────── 统计口径（CPK 家族） ─────────────────────


async def test_summary_stats_cpk_dual_limits() -> None:
    """双限列完整统计：T/U/ca/cp/CPKu/CPKl/CPK/级别/警告限/行动限/±4σ。

    值 [4.3,4.4,4.5]、spec 4.0~4.6：mean=4.4、σ=0.1、T=0.6、U=4.3、
    ca=1/3、cp=1、CPKu=2/3、CPKl=4/3、CPK=2/3（级别 一般）、
    警告限 4.15~4.45、行动限 4.06~4.54。
    """
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        item = await _mk_item(ac, section["id"])
        await _fill_values(ac, section["id"], item["id"], [4.3, 4.4, 4.5])

        resp = await ac.get(
            f"/api/v1/qa/apr/summary?product_id={product['id']}&year=2025"
        )
        assert resp.status_code == 200, resp.text
        stats = resp.json()["data"]["sections"][0]["column_stats"][item["id"]]
        assert stats["count"] == 3
        assert stats["mean"] == pytest.approx(4.4)
        assert stats["max"] == 4.5
        assert stats["min"] == 4.3
        assert stats["stdev"] == pytest.approx(0.1)
        assert stats["plus3s"] == pytest.approx(4.7)
        assert stats["minus3s"] == pytest.approx(4.1)
        assert stats["plus4s"] == pytest.approx(4.8)
        assert stats["minus4s"] == pytest.approx(4.0)
        assert stats["tolerance"] == pytest.approx(0.6)
        assert stats["spec_center"] == pytest.approx(4.3)
        assert stats["ca"] == pytest.approx(1 / 3)
        assert stats["cp"] == pytest.approx(1.0)
        assert stats["cpku"] == pytest.approx(2 / 3)
        assert stats["cpkl"] == pytest.approx(4 / 3)
        assert stats["cpk"] == pytest.approx(2 / 3)
        assert stats["cpk_level"] == "一般"
        assert stats["warn_max"] == pytest.approx(4.45)
        assert stats["warn_min"] == pytest.approx(4.15)
        assert stats["action_max"] == pytest.approx(4.54)
        assert stats["action_min"] == pytest.approx(4.06)


async def test_summary_stats_single_limit_and_no_limit() -> None:
    """单限列只算单侧 CPK（CPK=CPKu 或 CPKl），T/U/ca/cp/警告/行动限不输出；
    无限列 CPK 系整体不输出。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        # 只有上限 ≤5.0：mean=4.4、σ=0.2 → CPKu=CPK=1.0（良）
        only_max = await _mk_item(
            ac, section["id"], name_cn="水分", spec_min=None, spec_max=5.0
        )
        await _fill_values(ac, section["id"], only_max["id"], [4.2, 4.4, 4.6])
        # 只有下限 ≥4.0：mean=4.2、σ=0.2 → CPKl=CPK=1/3（差）
        only_min = await _mk_item(
            ac, section["id"], name_cn="比旋度", spec_min=4.0, spec_max=None
        )
        await _fill_values(ac, section["id"], only_min["id"], [4.0, 4.2, 4.4])
        # 无限（纯工艺参数）
        no_limit = await _mk_item(
            ac, section["id"], name_cn="培养温度", category="cpp",
            spec_min=None, spec_max=None,
        )
        await _fill_values(ac, section["id"], no_limit["id"], [30.0, 30.2])

        resp = await ac.get(
            f"/api/v1/qa/apr/summary?product_id={product['id']}&year=2025"
        )
        stats_by_id = resp.json()["data"]["sections"][0]["column_stats"]

        max_stats = stats_by_id[only_max["id"]]
        assert max_stats["cpku"] == pytest.approx(1.0)
        assert max_stats["cpk"] == pytest.approx(1.0)
        assert max_stats["cpk_level"] == "良"
        for key in ("cpkl", "tolerance", "spec_center", "ca", "cp",
                    "warn_max", "warn_min", "action_max", "action_min"):
            assert key not in max_stats

        min_stats = stats_by_id[only_min["id"]]
        assert min_stats["cpkl"] == pytest.approx(1 / 3)
        assert min_stats["cpk"] == pytest.approx(1 / 3)
        assert min_stats["cpk_level"] == "差"
        assert "cpku" not in min_stats

        none_stats = stats_by_id[no_limit["id"]]
        assert none_stats["mean"] == pytest.approx(30.1)
        # [30.0, 30.2] 样本标准差 = sqrt(0.01+0.01)（n-1 分母）
        assert none_stats["stdev"] == pytest.approx((0.02) ** 0.5)
        for key in ("cpku", "cpkl", "cpk", "cpk_level"):
            assert key not in none_stats


async def test_summary_stats_constant_and_single_sample() -> None:
    """全列同值（σ=0）与单样本：CPK 系不输出（单点/无离散无意义）。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        constant = await _mk_item(
            ac, section["id"], name_cn="炽灼残渣", spec_min=None, spec_max=0.3
        )
        await _fill_values(ac, section["id"], constant["id"], [0.10, 0.10])
        single = await _mk_item(ac, section["id"], name_cn="水分")
        await _fill_values(ac, section["id"], single["id"], [4.30])

        resp = await ac.get(
            f"/api/v1/qa/apr/summary?product_id={product['id']}&year=2025"
        )
        stats_by_id = resp.json()["data"]["sections"][0]["column_stats"]

        const_stats = stats_by_id[constant["id"]]
        assert const_stats["mean"] == pytest.approx(0.10)
        assert const_stats["stdev"] == pytest.approx(0.0)
        assert "cpk" not in const_stats

        single_stats = stats_by_id[single["id"]]
        assert single_stats["count"] == 1
        assert "stdev" not in single_stats
        assert "cpk" not in single_stats


async def test_summary_stats_nd_policy_with_cpk() -> None:
    """ND 口径作用于 CPK 样本：zero 按计入（拉低均值），exclude 不进样本。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        item = await _mk_item(ac, section["id"])
        await _fill_values(ac, section["id"], item["id"], [4.3, 4.4, "未检出"])

        resp = await ac.get(
            f"/api/v1/qa/apr/summary?product_id={product['id']}&year=2025"
        )
        stats = resp.json()["data"]["sections"][0]["column_stats"][item["id"]]
        assert stats["nd_count"] == 1
        assert stats["mean"] == pytest.approx((4.3 + 4.4 + 0.0) / 3)
        assert stats["min"] == 0.0
        assert "cpk" in stats

        # 切 exclude：ND 不进样本
        await ac.patch(
            f"/api/v1/qa/apr/items/{item['id']}", json={"nd_policy": "exclude"}
        )
        resp = await ac.get(
            f"/api/v1/qa/apr/summary?product_id={product['id']}&year=2025"
        )
        stats = resp.json()["data"]["sections"][0]["column_stats"][item["id"]]
        assert stats["count"] == 2
        assert stats["min"] == 4.3
        # [4.3, 4.4]：σ=sqrt(0.005)，CPK=CPKu=(4.6-4.35)/(3σ)
        assert stats["cpk"] == pytest.approx(0.25 / (3 * 0.005**0.5))


async def test_trend_stats_extended_keys() -> None:
    """趋势接口统计与汇总同源：±4σ 与 CPK 家族同口径输出。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        item = await _mk_item(ac, section["id"])
        await _fill_values(ac, section["id"], item["id"], [4.3, 4.4, 4.5])
        resp = await ac.get(f"/api/v1/qa/apr/trends?item_id={item['id']}&year=2025")
        stats = resp.json()["data"]["stats"]
        assert stats["plus4s"] == pytest.approx(4.8)
        assert stats["minus4s"] == pytest.approx(4.0)
        assert stats["cpk"] == pytest.approx(2 / 3)
        assert stats["cpk_level"] == "一般"
        assert stats["warn_max"] == pytest.approx(4.45)
        assert stats["action_min"] == pytest.approx(4.06)


# ───────────────────── Excel 表尾全量统计行 ─────────────────────


async def test_summary_export_layout_and_na_cells() -> None:
    """导出无大标题行（首行即分组行，第二行序号/批号）；不适用统计显示
    N/A：单上限列缺 CPKl/LSL，文字列统计全空。"""
    from openpyxl import load_workbook

    async with _client(MANAGE | ENTER | EXPORT) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        dual = await _mk_item(ac, section["id"], name_cn="酸碱度")
        only_max = await _mk_item(
            ac, section["id"], name_cn="水分", spec_min=None, spec_max=5.0
        )
        text_item = await _mk_item(
            ac, section["id"], name_cn="性状", value_type="text",
            spec_min=None, spec_max=None, spec_text="符合规定",
        )
        await _fill_values(ac, section["id"], dual["id"], [4.3, 4.4])
        await _fill_values(ac, section["id"], only_max["id"], [4.2, 4.4])
        await _fill_values(ac, section["id"], text_item["id"], ["符合规定", "符合规定"])

        resp = await ac.get(f"/api/v1/qa/apr/sections/{section['id']}/export?year=2025")
        assert resp.status_code == 200, resp.text
        wb = load_workbook(io.BytesIO(resp.content))
        ws = wb.worksheets[0]
        # 首行不再是标题：r1 分组行（A1 空），r2 序号/批号
        assert ws.cell(1, 1).value in (None, "")
        assert ws.cell(2, 1).value == "序号"
        for row in ws.iter_rows():
            for cell in row:
                assert "ANNUAL PRODUCT REVIEW" not in str(cell.value or "")
        # 数据单元格默认居中（不设 alignment 时数值右对齐/文本左对齐）
        assert ws.cell(4, 1).alignment.horizontal == "center"  # 序号
        assert ws.cell(4, 2).alignment.horizontal == "center"  # 批号
        assert ws.cell(4, 3).alignment.horizontal == "center"  # 酸碱度数值

        col_a = [row[0].value for row in ws.iter_rows(min_col=1, max_col=1)]

        def _cell(label: str, col: int) -> Any:
            row_idx = next(i for i, v in enumerate(col_a, start=1) if v == label)
            return ws.cell(row=row_idx, column=col).value

        # 列布局：序号 | 批号 | 酸碱度 | 水分 | 性状
        assert _cell("标准上限(USL)", 4) == pytest.approx(5.0)
        assert _cell("标准下限(LSL)", 4) == "N/A"
        assert _cell("制程能力(CPKl)", 4) == "N/A"
        assert _cell("规格公差(T)", 4) == "N/A"
        assert _cell("制程能力(CPKl)", 3) != "N/A"  # 双限列正常出数
        # 文字列：统计行全 N/A
        assert _cell("平均值", 5) == "N/A"
        assert _cell("标准上限(USL)", 5) == "N/A"
        # 无 ND 数据：不出现未检出行
        assert "未检出" not in col_a


async def test_section_export_xlsx_single_sheet() -> None:
    """段级 Excel 导出：只含该段一个 sheet（模板数据+全量统计），文件名含
    产品与段名；该年度无批次给可读 422。"""
    from openpyxl import load_workbook

    async with _client(MANAGE | ENTER | EXPORT) as (ac, _):
        product = await _mk_product(ac)
        us = await _mk_section(ac, product["id"], name="成品检验-US", market="US")
        chp = await _mk_section(ac, product["id"], name="成品检验-ChP", market="Ch.P")
        item = await _mk_item(ac, us["id"])
        other = await _mk_item(ac, chp["id"])
        await _fill_values(ac, us["id"], item["id"], [4.3, 4.4, 4.5])
        await _fill_values(ac, chp["id"], other["id"], [7.0, 7.1])

        resp = await ac.get(f"/api/v1/qa/apr/sections/{us['id']}/export?year=2025")
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        from urllib.parse import unquote

        filename = unquote(
            resp.headers["content-disposition"].split("filename*=UTF-8''")[-1]
        )
        assert product["name"] in filename
        assert "成品检验-US" in filename
        # 只导出该段：另一段不进来；表尾统计仍全量
        wb = load_workbook(io.BytesIO(resp.content))
        assert wb.sheetnames == ["成品检验-US-US"]
        col_a = [row[0].value for row in wb.worksheets[0].iter_rows(min_col=1, max_col=1)]
        assert "CPK级别" in col_a
        # 该年度无批次 → 422 可读提示，不出空报告
        resp = await ac.get(f"/api/v1/qa/apr/sections/{us['id']}/export?year=2026")
        assert resp.status_code == 422
        assert "批次" in resp.json()["message"]


async def test_summary_export_footer_full_stat_rows() -> None:
    """导出表尾含完整统计行清单，数值按列精度圆整，CPK级别为文字。"""
    from openpyxl import load_workbook

    async with _client(MANAGE | ENTER | EXPORT) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        # 精度 0：mean 4.45 → 4；精度 3：mean 4.45 原样
        p0 = await _mk_item(
            ac, section["id"], name_cn="残留溶剂", stat_precision=0, spec_max=5000.0
        )
        p3 = await _mk_item(ac, section["id"], name_cn="比旋度", stat_precision=3)
        await _fill_values(ac, section["id"], p0["id"], [4.4, 4.5])
        await _fill_values(ac, section["id"], p3["id"], [4.3, 4.4, 4.5])

        resp = await ac.get(f"/api/v1/qa/apr/sections/{section['id']}/export?year=2025")
        assert resp.status_code == 200, resp.text
        wb = load_workbook(io.BytesIO(resp.content))
        ws = wb.worksheets[0]
        # 收集 A 列的表尾标签（跳过矩阵自身的 序号/批号 表头区）
        col_a = [row[0].value for row in ws.iter_rows(min_col=1, max_col=1)]
        footer_labels = [v for v in col_a if isinstance(v, str) and v in FULL_STAT_ROWS]
        assert footer_labels == FULL_STAT_ROWS

        def _cell(label: str, col: int) -> Any:
            row_idx = next(
                i for i, v in enumerate(col_a, start=1) if v == label
            )
            return ws.cell(row=row_idx, column=col).value

        # 数据列布局：序号 | 批号 | 残留溶剂 | 比旋度 → 列 3/4
        assert _cell("平均值", 3) == pytest.approx(4.0)  # 精度 0 圆整
        assert _cell("平均值", 4) == pytest.approx(4.4)  # 精度 3 原样
        assert _cell("CPK级别", 4) == "一般"
        assert _cell("标准上限(USL)", 4) == pytest.approx(4.6)
        assert _cell("标准下限(LSL)", 4) == pytest.approx(4.0)
        assert _cell("警告限上限", 4) == pytest.approx(4.45)


async def test_summary_export_footer_nd_row() -> None:
    """未检出透明行：列有 ND 时表尾输出批数，无 ND 列留空。"""
    from openpyxl import load_workbook

    async with _client(MANAGE | ENTER | EXPORT) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        nd_item = await _mk_item(ac, section["id"], name_cn="水分")
        plain = await _mk_item(ac, section["id"], name_cn="比旋度")
        await _fill_values(ac, section["id"], nd_item["id"], [4.3, "未检出"])
        await _fill_values(ac, section["id"], plain["id"], [16.0, 17.0])

        resp = await ac.get(f"/api/v1/qa/apr/sections/{section['id']}/export?year=2025")
        assert resp.status_code == 200, resp.text
        wb = load_workbook(io.BytesIO(resp.content))
        ws = wb.worksheets[0]
        col_a = [row[0].value for row in ws.iter_rows(min_col=1, max_col=1)]
        assert "未检出" in col_a
        nd_row = next(i for i, v in enumerate(col_a, start=1) if v == "未检出")
        assert ws.cell(row=nd_row, column=3).value == 1
        assert ws.cell(row=nd_row, column=4).value in (None, "")


# ───────────────────── 段级 Word 报告 ─────────────────────


async def _seed_report_section(ac: AsyncClient) -> dict[str, Any]:
    """一个可出报告的段：文字项 + 变值数值项(t2) + 恒值数值项(t1)。"""
    product = await _mk_product(ac)
    section = await _mk_section(ac, product["id"])
    text_item = await _mk_item(
        ac,
        section["id"],
        name_cn="性状",
        value_type="text",
        spec_text="白色或类白色粉末",
        trend_enabled=False,
    )
    varying = await _mk_item(ac, section["id"], name_cn="酸碱度")
    constant = await _mk_item(
        ac, section["id"], name_cn="炽灼残渣", spec_min=None, spec_max=0.3,
        stat_precision=1,
    )
    for i, v in enumerate(["符合规定", "符合规定"], start=1):
        batch = await _mk_batch(ac, section["id"], seq=i)
        resp = await ac.put(
            f"/api/v1/qa/apr/batches/{batch['id']}/values",
            json={"values": [
                {"item_id": text_item["id"], "value_text": v},
                {"item_id": varying["id"], "value_num": 4.20 + 0.10 * i},
                {"item_id": constant["id"], "value_num": 0.10},
            ]},
        )
        assert resp.status_code == 200, resp.text
    return {"product": product, "section": section, "ids": [text_item["id"], varying["id"], constant["id"]]}


def _read_docx_xml(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    # docx 的 run 会把文字打碎，先去掉标签再断言整句
    import re

    return re.sub(r"<[^>]+>", "", xml)


def _read_docx_text(content: bytes) -> str:
    """docx 正文的纯文本：XML 解析会还原 &amp; 等实体；XML 坏掉直接抛错。"""
    from xml.etree import ElementTree

    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        xml = zf.read("word/document.xml")
    return "".join(ElementTree.fromstring(xml).itertext())


async def test_section_report_requires_export_permission() -> None:
    """报告导出走独立导出权限：manage/enter 不放行，补 export 后放行。"""
    grants = set(MANAGE | ENTER)
    async with _client(grants) as (ac, _):
        seeded = await _seed_report_section(ac)
        grants.clear()
        grants.update(MANAGE)
        resp = await ac.get(
            f"/api/v1/qa/apr/sections/{seeded['section']['id']}/report?year=2025"
        )
        assert resp.status_code == 403
        grants.update(EXPORT)
        resp = await ac.get(
            f"/api/v1/qa/apr/sections/{seeded['section']['id']}/report?year=2025"
        )
        assert resp.status_code == 200


async def test_section_report_docx_smoke() -> None:
    """段级报告：docx 结构合法、三种列各按模板渲染、文件名含产品/段/年度。"""
    async with _client(MANAGE | ENTER | EXPORT) as (ac, _):
        seeded = await _seed_report_section(ac)
        resp = await ac.get(
            f"/api/v1/qa/apr/sections/{seeded['section']['id']}/report?year=2025"
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        assert "attachment" in resp.headers["content-disposition"]
        # 文件名走 filename*=UTF-8'' 百分号编码：解回原文再断言
        from urllib.parse import unquote

        filename = unquote(
            resp.headers["content-disposition"].split("filename*=UTF-8''")[-1]
        )
        assert "年度回顾报告" in filename
        assert seeded["product"]["name"] in filename
        assert seeded["section"]["name"] in filename
        # docx = zip，PK 头
        assert resp.content[:2] == b"PK"

        text = _read_docx_xml(resp.content)
        assert "符合内控质量标准" in text
        # 文字项（t1）：常数结论 + 标准原文
        assert "性状" in text
        assert "符合规定" in text
        # 恒值数值项（t1）：结论句含 0.1（精度 1）
        assert "炽灼残渣" in text
        assert "0.1" in text
        # 变值数值项（t2）：均值 + CPK 结论；两批均值 4.35
        assert "酸碱度" in text
        assert "4.35" in text
        assert "Cpk" in text or "CPK" in text
        # 嵌入的趋势图（t2 列至少一张 PNG）
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            media = [n for n in zf.namelist() if n.startswith("word/media/")]
        assert media


async def test_section_report_escapes_special_characters() -> None:
    """产品名/项目名/标准原文含 & 或 < 时报告文字完整（docxtpl autoescape）：

    docxtpl 默认不转义，recover 解析会把 &、< 之后的内容静默丢掉；
    产品名、项目名、标准原文都必须原样出现在报告里。
    """
    async with _client(MANAGE | ENTER | EXPORT) as (ac, _):
        product = await _mk_product(ac, name="卡那&霉素")
        section = await _mk_section(ac, product["id"])
        item = await _mk_item(
            ac,
            section["id"],
            name_cn="重金属(<1)",
            value_type="text",
            spec_text="<1.0 ppm & 无",
            spec_min=None,
            spec_max=None,
        )
        for i, v in enumerate(["符合规定", "符合规定"], start=1):
            batch = await _mk_batch(ac, section["id"], seq=i)
            resp = await ac.put(
                f"/api/v1/qa/apr/batches/{batch['id']}/values",
                json={"values": [{"item_id": item["id"], "value_text": v}]},
            )
            assert resp.status_code == 200, resp.text

        resp = await ac.get(
            f"/api/v1/qa/apr/sections/{section['id']}/report?year=2025"
        )
        assert resp.status_code == 200, resp.text
        text = _read_docx_text(resp.content)
        assert product["name"] in text
        assert "重金属(<1)" in text
        assert "<1.0 ppm & 无" in text


async def test_section_report_empty_year_rejected() -> None:
    """该年度无批次数据时报告导出给可读 422，不产出空报告。"""
    async with _client(MANAGE | ENTER | EXPORT) as (ac, _):
        seeded = await _seed_report_section(ac)
        resp = await ac.get(
            f"/api/v1/qa/apr/sections/{seeded['section']['id']}/report?year=2026"
        )
        assert resp.status_code == 422
        assert "批次" in resp.json()["message"]


def test_report_all_nd_column_uses_nd_text() -> None:
    """整列都是未检出（按 0 计）时 t1 结论写原文，而不是 0.00%。"""
    from app.modules.qa.service.apr.report import build_report_rows

    rows = build_report_rows(
        [
            {
                "id": "i1", "code": "HM", "name_cn": "重金属",
                "value_type": "number", "unit": "%", "spec_text": None,
                "spec_min": None, "spec_max": 0.002, "stat_precision": 3,
                "points": [("b1", "未检出"), ("b2", "未检出"), ("b3", "未检出")],
            }
        ],
        product="卡那霉素",
    )
    assert [r["tpl"] for r in rows] == ["t1"]
    assert rows[0]["const"] == "未检出"
    assert rows[0]["range"] == "≤0.002%"


def test_report_row_classification_and_formatting() -> None:
    """报告行分类与格式化（纯函数）：

    - 文字项 → t1，const=众数文字，range=标准原文；
    - 恒值数值项 → t1，const=按精度格式化的值；
    - 变值数值项 → t2，avg/max/min 按精度+单位，min 为 0 且有 ND 时用 ND 文本；
    - 无数据列跳过；range 由限值推导（≤/≥/区间）。
    """
    from app.modules.qa.service.apr.report import build_report_rows

    items = [
        {  # 文字项：两批 符合规定
            "id": "i1", "name_cn": "性状", "value_type": "text",
            "spec_text": "白色粉末", "unit": None, "spec_min": None,
            "spec_max": None, "stat_precision": None,
            "points": [("b1", "符合规定"), ("b2", "符合规定")],
        },
        {  # 恒值数值项：t1
            "id": "i2", "name_cn": "炽灼残渣", "value_type": "number",
            "spec_text": None, "unit": "%", "spec_min": None,
            "spec_max": 0.3, "stat_precision": 1,
            "points": [("b1", 0.1), ("b2", 0.1)],
        },
        {  # 变值数值项：t2，min 是 ND 文本
            "id": "i3", "name_cn": "水分", "value_type": "number",
            "spec_text": None, "unit": "%", "spec_min": 4.0,
            "spec_max": 4.6, "stat_precision": 2,
            "points": [("b1", 4.3), ("b2", "未检出"), ("b3", 4.5)],
        },
        {  # 无数据列：跳过
            "id": "i4", "name_cn": "空白项", "value_type": "number",
            "spec_text": None, "unit": None, "spec_min": None,
            "spec_max": None, "stat_precision": None,
            "points": [],
        },
    ]
    rows = build_report_rows(items, product="卡那霉素")
    assert [r["tpl"] for r in rows] == ["t1", "t1", "t2"]

    text_row, const_row, varying_row = rows
    assert text_row["test_name"] == "性状"
    assert text_row["const"] == "符合规定"
    assert text_row["range"] == "白色粉末"

    assert const_row["const"] == "0.1%"
    assert const_row["range"] == "≤0.3%"

    assert varying_row["range"] == "4.00%~4.60%"
    assert varying_row["avg"] == "2.93%"  # (4.3+0+4.5)/3
    assert varying_row["max"] == "4.50%"
    assert varying_row["min"] == "未检出"
    assert isinstance(varying_row["cpk"], float)
    assert varying_row["cpk_level"] in {"特优", "优", "良", "一般", "差"}
