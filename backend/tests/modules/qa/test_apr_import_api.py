"""QA 年度产品审核（PQR）Excel 导入测试：模板下载 / merge·replace 双模式 /
全部正确才写入（任一错误零落库）。

沿用 test_apr_api 的 harness：覆盖 get_db / get_current_user 并 patch 权限
集合，用例共用一个最终回滚的会话；测试 xlsx 用 openpyxl 现场生成。
"""

from __future__ import annotations

import io
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import openpyxl
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
LOCK = MANAGE | ENTER | {"qa:apr:lock"}

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def _ensure_test_user(session: AsyncSession) -> User:
    stmt = select(User).where(User.is_deleted == False).limit(1)  # noqa: E712
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing
    user = User(name="qa-apr导入测试用户", employee_no="QA-APR-IMPORT-001")
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
    payload["name"] = f"{payload['name']}{uuid4().hex[:6]}"
    resp = await ac.post("/api/v1/qa/apr/products", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def _mk_section(ac: AsyncClient, product_id: str, **overrides: Any) -> dict:
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


async def _mk_item(ac: AsyncClient, section_id: str, **overrides: Any) -> dict:
    payload: dict[str, Any] = {
        "section_id": section_id,
        "category": "test",
        "name_cn": "酸碱度",
        "value_type": "number",
        "spec_text": "4.0-4.6",
        "spec_min": 4.0,
        "spec_max": 4.6,
    }
    payload.update(overrides)
    resp = await ac.post("/api/v1/qa/apr/items", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


async def _mk_batch(
    ac: AsyncClient, section_id: str, batch_no: str | None = None, **overrides: Any
) -> dict:
    payload: dict[str, Any] = {
        "section_id": section_id,
        "year": 2025,
        "batch_no": batch_no or _code("B"),
    }
    payload.update(overrides)
    resp = await ac.post("/api/v1/qa/apr/batches", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _xlsx(rows: list[list[Any]], sheet: str = "数据录入") -> bytes:
    """现场生成单 sheet xlsx：第一行表头，其后数据行。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = sheet
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def _import(
    ac: AsyncClient,
    section_id: str,
    content: bytes,
    *,
    year: int = 2025,
    mode: str | None = None,
    filename: str = "import.xlsx",
) -> Any:
    params: dict[str, Any] = {"year": year}
    if mode is not None:
        params["mode"] = mode
    return await ac.post(
        f"/api/v1/qa/apr/sections/{section_id}/values/import",
        params=params,
        files={"file": (filename, content, XLSX_MIME)},
    )


async def _values(ac: AsyncClient, batch_id: str) -> dict[tuple[str, int], dict]:
    resp = await ac.get(f"/api/v1/qa/apr/batches/{batch_id}/values")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    return {(v["item_id"], v["row_seq"]): v for v in data["values"]}


def _err_texts(result: dict[str, Any]) -> str:
    return "；".join(e["message"] for e in result.get("errors", []))


# ───────────────────────── 模板下载 ─────────────────────────


async def test_import_template_download_and_auth() -> None:
    """模板下载：enter 可得 xlsx（表头含批号与列名、附已登记批号 sheet）；只读 403。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        await _mk_item(ac, section["id"])
        await _mk_item(ac, section["id"], name_cn="低值", code="ph#min")
        await _mk_batch(ac, section["id"], batch_no="DT2501001")
        resp = await ac.get(
            f"/api/v1/qa/apr/sections/{section['id']}/import-template",
            params={"year": 2025},
        )
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        wb = openpyxl.load_workbook(io.BytesIO(resp.content))
        assert "数据录入" in wb.sheetnames
        assert "已登记批号" in wb.sheetnames
        rows = [list(r) for r in wb["数据录入"].iter_rows(values_only=True)]
        flat = [c for r in rows[:6] for c in r if c is not None]
        assert "批号" in flat
        assert "酸碱度" in flat
        assert "低值 MIN" in flat  # #min 成对列在模板里带 MIN 后缀
        ref = [list(r) for r in wb["已登记批号"].iter_rows(values_only=True)]
        assert any(cell == "DT2501001" for r in ref for cell in r if cell)
    async with _client(READ) as (ac, _):
        resp = await ac.get(
            "/api/v1/qa/apr/sections/00000000-0000-0000-0000-000000000000"
            "/import-template",
            params={"year": 2025},
        )
        assert resp.status_code == 403


# ───────────────────────── merge 模式 ─────────────────────────


async def test_import_merge_overwrites_nonblank_keeps_blank() -> None:
    """merge：非空格写入、空白格保留系统已有值；多批一次导入。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        ph = await _mk_item(ac, section["id"])
        chars = await _mk_item(
            ac, section["id"], name_cn="性状", value_type="text", spec_text="白色粉末"
        )
        b1 = await _mk_batch(ac, section["id"], batch_no="DT2501001")
        b2 = await _mk_batch(ac, section["id"], batch_no="DT2501002")
        # 预置旧值：b1 两列都有
        resp = await ac.put(
            f"/api/v1/qa/apr/batches/{b1['id']}/values",
            json={
                "values": [
                    {"item_id": ph["id"], "value_num": 4.31},
                    {"item_id": chars["id"], "value_text": "符合规定"},
                ]
            },
        )
        assert resp.status_code == 200, resp.text
        # 导入：b1 只改酸碱度（性状留空），b2 两列都填
        content = _xlsx(
            [
                ["批号", "酸碱度", "性状"],
                ["DT2501001", 4.35, None],
                ["DT2501002", 4.10, "白色粉末"],
            ]
        )
        resp = await _import(ac, section["id"], content)  # 默认 merge
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["ok"] is True, _err_texts(data)
        assert data["mode"] == "merge"
        assert data["batches"] == 2
        assert data["cells"] == 3
        vals = await _values(ac, b1["id"])
        assert vals[(ph["id"], 1)]["value_num"] == pytest.approx(4.35)
        assert vals[(chars["id"], 1)]["value_text"] == "符合规定"  # 空白格保留旧值
        vals = await _values(ac, b2["id"])
        assert vals[(ph["id"], 1)]["value_num"] == pytest.approx(4.10)
        assert vals[(chars["id"], 1)]["value_text"] == "白色粉末"


async def test_import_merge_keeps_existing_row_label() -> None:
    """merge 文件没给行标签时沿用已有标签（空白不代表清空）。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"], multi_row=True)
        ph = await _mk_item(ac, section["id"])
        batch = await _mk_batch(ac, section["id"], batch_no="DT2501001")
        resp = await ac.put(
            f"/api/v1/qa/apr/batches/{batch['id']}/values",
            json={
                "values": [
                    {
                        "item_id": ph["id"],
                        "row_seq": 1,
                        "row_label": "工序一",
                        "value_num": 1.0,
                    }
                ]
            },
        )
        assert resp.status_code == 200, resp.text
        # 文件只有批号+数值，没有行标签列
        content = _xlsx([["批号", "酸碱度"], ["DT2501001", 2.0]])
        data = (await _import(ac, section["id"], content)).json()["data"]
        assert data["ok"] is True, _err_texts(data)
        vals = await _values(ac, batch["id"])
        assert vals[(ph["id"], 1)]["row_label"] == "工序一"
        assert vals[(ph["id"], 1)]["value_num"] == pytest.approx(2.0)


# ───────────────────────── replace 模式 ─────────────────────────


async def test_import_replace_wipes_blank_and_guards_required() -> None:
    """replace：整批覆盖、空白=删除；必填列空白整单拒绝且旧值不动。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        assay = await _mk_item(
            ac, section["id"], name_cn="含量", required=True, spec_text="≥90%"
        )
        water = await _mk_item(ac, section["id"], name_cn="水分")
        batch = await _mk_batch(ac, section["id"], batch_no="DT2501001")
        # 预置两列旧值
        resp = await ac.put(
            f"/api/v1/qa/apr/batches/{batch['id']}/values",
            json={
                "values": [
                    {"item_id": assay["id"], "value_num": 99.1},
                    {"item_id": water["id"], "value_num": 1.0},
                ]
            },
        )
        assert resp.status_code == 200, resp.text
        # replace：含量=99.5，水分空白 → 水分被删
        content = _xlsx([["批号", "含量", "水分"], ["DT2501001", 99.5, None]])
        resp = await _import(ac, section["id"], content, mode="replace")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["ok"] is True, _err_texts(data)
        vals = await _values(ac, batch["id"])
        assert len(vals) == 1
        assert vals[(assay["id"], 1)]["value_num"] == pytest.approx(99.5)
        # replace：必填列空白 → 整单拒绝，旧值保留
        content = _xlsx([["批号", "含量", "水分"], ["DT2501001", None, 0.9]])
        resp = await _import(ac, section["id"], content, mode="replace")
        data = resp.json()["data"]
        assert data["ok"] is False
        assert "含量" in _err_texts(data)
        vals = await _values(ac, batch["id"])
        assert vals[(assay["id"], 1)]["value_num"] == pytest.approx(99.5)


# ───────────────────────── 校验与原子性 ─────────────────────────


async def test_import_auto_registers_unknown_batches() -> None:
    """未知批号自动登记为新批次再录值；结果报告新登记数；已登记批次照常更新。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        ph = await _mk_item(ac, section["id"])
        batch = await _mk_batch(ac, section["id"], batch_no="DT2501001")
        resp = await ac.put(
            f"/api/v1/qa/apr/batches/{batch['id']}/values",
            json={"values": [{"item_id": ph["id"], "value_num": 4.31}]},
        )
        assert resp.status_code == 200, resp.text
        content = _xlsx([["批号", "酸碱度"], ["DT2501001", 4.4], ["DT2509999", 4.5]])
        resp = await _import(ac, section["id"], content)
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["ok"] is True, _err_texts(data)
        assert data["batches"] == 2
        assert data["cells"] == 2
        assert data["registered"] == 1  # 结果里透明报告新登记了几批
        # 已登记批次：merge 更新
        vals = await _values(ac, batch["id"])
        assert vals[(ph["id"], 1)]["value_num"] == pytest.approx(4.4)
        # 新批次：落库到该段该年度，值已写入
        resp = await ac.get(
            f"/api/v1/qa/apr/batches?section_id={section['id']}&year=2025"
            "&keyword=DT2509999"
        )
        rows = resp.json()["data"]
        assert len(rows) == 1
        assert rows[0]["batch_no"] == "DT2509999"
        vals = await _values(ac, rows[0]["id"])
        assert vals[(ph["id"], 1)]["value_num"] == pytest.approx(4.5)


async def test_import_rejects_duplicate_batch_and_unknown_column() -> None:
    """单行段批号重复、未知列名均整单拒绝并给出定位。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        await _mk_item(ac, section["id"])
        await _mk_batch(ac, section["id"], batch_no="DT2501001")
        # 同一批号两行（单行段）
        content = _xlsx([["批号", "酸碱度"], ["DT2501001", 4.1], ["DT2501001", 4.2]])
        resp = await _import(ac, section["id"], content)
        data = resp.json()["data"]
        assert data["ok"] is False
        assert "重复" in _err_texts(data)
        # 未知列
        content = _xlsx([["批号", "酸碱度", "不存在的列"], ["DT2501001", 4.1, 1]])
        resp = await _import(ac, section["id"], content)
        data = resp.json()["data"]
        assert data["ok"] is False
        assert "不存在的列" in _err_texts(data)


async def test_import_failure_writes_nothing() -> None:
    """任一格错误 → 整单拒绝：文件里的新批号也不得登记（失败零落库）。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        await _mk_item(ac, section["id"])
        content = _xlsx([["批号", "酸碱度"], ["DT2507777", "不合规文字"]])
        data = (await _import(ac, section["id"], content)).json()["data"]
        assert data["ok"] is False
        resp = await ac.get(
            f"/api/v1/qa/apr/batches?section_id={section['id']}&year=2025"
            "&keyword=DT2507777"
        )
        assert resp.json()["data"] == []


async def test_import_number_text_rules() -> None:
    """数值列：白名单文字（含全角 NFKC）落文字槽；白名单外/日期格拒绝；数字串可解析。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        ph = await _mk_item(ac, section["id"])  # quick_values 默认 ["未检出", "<1"]
        batch = await _mk_batch(ac, section["id"], batch_no="DT2501001")

        async def _try(rows: list[list[Any]]) -> dict[str, Any]:
            resp = await _import(ac, section["id"], _xlsx([["批号", "酸碱度"], *rows]))
            assert resp.status_code == 200, resp.text
            return resp.json()["data"]

        # 白名单文字 → 文字槽
        data = await _try([["DT2501001", "未检出"]])
        assert data["ok"] is True, _err_texts(data)
        vals = await _values(ac, batch["id"])
        assert vals[(ph["id"], 1)]["value_text"] == "未检出"
        assert vals[(ph["id"], 1)]["value_num"] is None
        # 全角 ＜１（NFKC → <1）同样放行
        data = await _try([["DT2501001", "＜１"]])
        assert data["ok"] is True, _err_texts(data)
        # 白名单外文字 → 拒绝并提示可选值
        data = await _try([["DT2501001", "大概 maybe"]])
        assert data["ok"] is False
        assert "未检出" in _err_texts(data)
        # 日期格 → 类型不符
        data = await _try([["DT2501001", datetime(2025, 1, 1)]])
        assert data["ok"] is False
        assert "类型" in _err_texts(data)
        # 数字字符串 → 解析为数值
        data = await _try([["DT2501001", "4.32"]])
        assert data["ok"] is True, _err_texts(data)
        vals = await _values(ac, batch["id"])
        assert vals[(ph["id"], 1)]["value_num"] == pytest.approx(4.32)


async def test_import_multi_row_rows_labels_and_continuity() -> None:
    """多行段：连续行展开 row_seq 1..N 并落行标签；同批行不连续拒绝。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"], multi_row=True)
        ph = await _mk_item(ac, section["id"])
        await _mk_batch(ac, section["id"], batch_no="DT2501001")
        await _mk_batch(ac, section["id"], batch_no="DT2501002")
        header = ["批号", "行标签", "酸碱度"]
        content = _xlsx(
            [
                header,
                ["DT2501001", "工序一", 1.1],
                ["DT2501001", "工序二", 1.2],
                ["DT2501002", "工序一", 2.1],
            ]
        )
        resp = await _import(ac, section["id"], content)
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["ok"] is True, _err_texts(data)
        assert data["cells"] == 3
        resp = await ac.get(
            f"/api/v1/qa/apr/batches?section_id={section['id']}&year=2025"
        )
        batches = {b["batch_no"]: b["id"] for b in resp.json()["data"]}
        vals = await _values(ac, batches["DT2501001"])
        assert vals[(ph["id"], 1)]["row_label"] == "工序一"
        assert vals[(ph["id"], 1)]["value_num"] == pytest.approx(1.1)
        assert vals[(ph["id"], 2)]["row_label"] == "工序二"
        assert vals[(ph["id"], 2)]["value_num"] == pytest.approx(1.2)
        # 同批行被其他批隔开 → 拒绝
        content = _xlsx(
            [
                header,
                ["DT2501001", "工序一", 1.1],
                ["DT2501002", "工序一", 2.1],
                ["DT2501001", "工序二", 1.2],
            ]
        )
        resp = await _import(ac, section["id"], content)
        data = resp.json()["data"]
        assert data["ok"] is False
        assert "连续" in _err_texts(data)


# ───────────────────────── 锁定与鉴权 ─────────────────────────


async def test_import_blocked_by_annual_lock() -> None:
    """年度锁定后导入被拒（422 提示解锁）。"""
    async with _client(LOCK) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        await _mk_item(ac, section["id"])
        await _mk_batch(ac, section["id"], batch_no="DT2501001")
        resp = await ac.post(f"/api/v1/qa/apr/annual-reviews/{product['id']}/2025/lock")
        assert resp.status_code == 200, resp.text
        content = _xlsx([["批号", "酸碱度"], ["DT2501001", 4.3]])
        resp = await _import(ac, section["id"], content)
        assert resp.status_code == 422
        assert "锁定" in resp.json()["message"]


async def test_import_requires_enter_permission() -> None:
    """模板下载与导入都需要 enter 权限；只读用户 403。"""
    section_id = "00000000-0000-0000-0000-000000000000"
    async with _client(READ) as (ac, _):
        resp = await ac.get(
            f"/api/v1/qa/apr/sections/{section_id}/import-template",
            params={"year": 2025},
        )
        assert resp.status_code == 403
        resp = await _import(ac, section_id, _xlsx([["批号"], ["B"]]), year=2025)
        assert resp.status_code == 403


# ───────────────────────── 文件级错误 ─────────────────────────


async def test_import_roundtrip_with_downloaded_template() -> None:
    """下载的模板填一行数据原样回传可导入：列名含全角字符（如（））时
    表头匹配两侧必须同样 NFKC 归一，否则模板自产的表头也认不出来。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(
            ac, product["id"], data_kind="production", market=None
        )
        # 复现真实模板的全角括号列名（发酵培养段的「培养温度（最低）」）
        temp_lo = await _mk_item(
            ac, section["id"], name_cn="培养温度（最低）", spec_text="26-28℃"
        )
        batch = await _mk_batch(ac, section["id"], batch_no="KA2601001")
        resp = await ac.get(
            f"/api/v1/qa/apr/sections/{section['id']}/import-template",
            params={"year": 2025},
        )
        assert resp.status_code == 200, resp.text
        wb = openpyxl.load_workbook(io.BytesIO(resp.content))
        ws = wb["数据录入"]
        ws.append(["KA2601001", 27.5])  # 表头之下第一行数据
        buf = io.BytesIO()
        wb.save(buf)
        resp = await _import(ac, section["id"], buf.getvalue())
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["ok"] is True, _err_texts(data)
        vals = await _values(ac, batch["id"])
        assert vals[(temp_lo["id"], 1)]["value_num"] == pytest.approx(27.5)


async def test_import_bad_file_and_extension() -> None:
    """打不开的文件 ok=false 提示原因；非 .xlsx 扩展名 400。"""
    async with _client(MANAGE | ENTER) as (ac, _):
        product = await _mk_product(ac)
        section = await _mk_section(ac, product["id"])
        resp = await _import(ac, section["id"], b"this is not an excel file")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["ok"] is False
        assert "无法打开文件" in _err_texts(data)
        resp = await _import(ac, section["id"], b"x", filename="data.csv")
        assert resp.status_code == 400
        assert "xlsx" in resp.json()["message"]
