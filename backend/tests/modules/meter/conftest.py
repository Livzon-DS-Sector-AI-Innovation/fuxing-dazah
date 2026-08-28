"""meter 模块测试 fixtures 与数据工厂。

所有测试共用顶层 tests/conftest.py 的 `db_session`（真实库+回滚）与 `client`（ASGI）。
本文件额外提供：
- 记录工厂：直接 SQL/ORM 插入仪表、探测器、报告、部门数据
- xlsx 字节构造器：为台账导入测试生成 Excel 文件
- client_with_noop_commit：禁掉 commit 的 API client（供内部 commit 的端点使用）
"""

from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import date, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook

from app.core.database import get_db
from app.main import app as fastapi_app  # type: ignore[attr-defined]
from app.modules.meter.models import (
    CalibrationReport,
    Department,
    GasDetectorRecord,
    InstrumentRecord,
)
from tests.conftest import _test_session_factory

# ── 数据工厂 ──


def make_instrument_data(**overrides: Any) -> dict[str, Any]:
    """标准计量器具字段默认值（未删除、在用、30 天后到期）。"""
    suffix = uuid.uuid4().hex[:8]
    data: dict[str, Any] = {
        "asset_number": f"ASSET-{suffix}",
        "instrument_name": f"压力表-{suffix}",
        "model_spec": "YB-150",
        "measurement_range": "0-1.6MPa",
        "accuracy_grade": "1.6级",
        "serial_number": f"SN-{suffix}",
        "calibration_cycle_months": 12,
        "location": "一车间",
        "manufacturer": "红旗仪表",
        "status": "在用",
        "color_marking": "绿色",
        "calibration_date": date.today() - timedelta(days=30),
        "calibration_unit": "市计量院",
        "calibration_result": "合格",
        "next_calibration_date": date.today() + timedelta(days=30),
        "department": f"测试部门-{suffix}",
        "sort_order": 0,
    }
    data.update(overrides)
    return data


def make_gas_detector_data(**overrides: Any) -> dict[str, Any]:
    """有毒有害可燃探测器字段默认值。"""
    suffix = uuid.uuid4().hex[:8]
    data: dict[str, Any] = {
        "instrument_name": f"可燃气体探测器-{suffix}",
        "detection_model": "GT-100",
        "measurement_range": "0-100%LEL",
        "product_number": f"PN-{suffix}",
        "installation_type": "壁挂式",
        "installation_location": "一车间",
        "medium": "天然气",
        "calibration_factor": "1.0",
        "manufacturer_supplier": "海湾公司",
        "calibration_date": date.today() - timedelta(days=30),
        "calibration_result": "合格",
        "detection_unit": "市计量院",
        "next_calibration_date": date.today() + timedelta(days=30),
        "manufacturer": "海湾公司",
        "status": "在用",
        "department": f"测试部门-{suffix}",
        "sort_order": 0,
    }
    data.update(overrides)
    return data


async def create_instrument(db: Any, **overrides: Any) -> InstrumentRecord:
    """直接插入一条标准计量器具记录（绕过 service 校验）。"""
    record = InstrumentRecord(**make_instrument_data(**overrides))
    db.add(record)
    await db.flush()
    return record


async def create_gas_detector(db: Any, **overrides: Any) -> GasDetectorRecord:
    """直接插入一条探测器记录。"""
    record = GasDetectorRecord(**make_gas_detector_data(**overrides))
    db.add(record)
    await db.flush()
    return record


async def create_department(
    db: Any,
    source: str = "instrument",
    name: str | None = None,
    heads: list[dict[str, str]] | None = None,
    auto_notify_enabled: bool = False,
) -> Department:
    """直接插入一条部门记录。"""
    dept = Department(
        source=source,
        name=name or f"测试部门-{uuid.uuid4().hex[:8]}",
        heads=heads if heads is not None else [],
        auto_notify_enabled=auto_notify_enabled,
    )
    db.add(dept)
    await db.flush()
    return dept


async def create_report(
    db: Any,
    *,
    instrument_id: uuid.UUID | None = None,
    gas_detector_id: uuid.UUID | None = None,
    certificate_no: str | None = None,
    report_date: date | None = None,
    file_name: str | None = None,
) -> CalibrationReport:
    """直接插入一条检测报告元数据（满足"恰好一个父记录"约束）。"""
    assert (instrument_id is None) != (gas_detector_id is None)
    report = CalibrationReport(
        instrument_id=instrument_id,
        gas_detector_id=gas_detector_id,
        file_name=file_name or f"报告-{uuid.uuid4().hex[:8]}.pdf",
        file_path=f"reports/test/{uuid.uuid4().hex}.pdf",
        file_size=1024,
        content_type="application/pdf",
        certificate_no=certificate_no,
        report_date=report_date or date.today(),
    )
    db.add(report)
    await db.flush()
    return report


def build_xlsx(
    sheets: list[dict[str, Any]],
) -> bytes:
    """构造 Excel 字节流。

    每个 sheet dict:
        name: sheet 名
        rows: 完整行列表（含第 1 行标题行、第 2 行部门行、第 3 行表头行、数据行）
    返回 xlsx bytes，可直接交给 import_instrument_ledger 等。
    """
    wb = Workbook()
    default_sheet = wb.active
    assert default_sheet is not None
    wb.remove(default_sheet)
    for spec in sheets:
        ws = wb.create_sheet(title=spec["name"])
        for row in spec["rows"]:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── fixtures ──


@pytest.fixture(autouse=True)
def _noop_db_commit(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """meter 测试全局禁掉 db_session.commit，防止测试数据落库污染 dev 库。

    台账导入类函数内部显式调用 db.commit()（upsert 会软删全表旧记录），
    一旦某条测试漏加禁 commit 补丁，就会把 dev 库在用的全部台账记录删除。
    用 autouse fixture 在包级别统一兜底，任何测试（含未来新增）自动生效。
    """
    monkeypatch.setattr(db_session, "commit", AsyncMock())


@pytest.fixture
def instrument_factory() -> Callable[..., dict[str, Any]]:
    """字段字典工厂（用于 service 层 create 入参构造）。"""
    return make_instrument_data


@pytest.fixture
async def client_with_noop_commit() -> AsyncIterator[AsyncClient]:
    """API client，其 session.commit 被禁用，避免测试数据落库。

    用于内部显式调用 db.commit() 的端点（批量新增/台账导入/更新设置）。
    """
    async with _test_session_factory() as session:
        session.commit = AsyncMock()  # type: ignore[method-assign]

        async def _override_get_db() -> AsyncIterator[Any]:
            yield session

        fastapi_app.dependency_overrides[get_db] = _override_get_db  # type: ignore[attr-defined]
        transport = ASGITransport(app=fastapi_app)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
        fastapi_app.dependency_overrides.clear()  # type: ignore[attr-defined]
        await session.rollback()


@pytest.fixture
async def api_context() -> AsyncIterator[tuple[AsyncClient, Any]]:
    """API client 与其底层 session 配对：测试用同一 session 预置数据，请求可见。

    替代顶层 client fixture（其内部 session 不可见，预置数据无法被端点查询到）。
    """
    async with _test_session_factory() as session:
        async def _override_get_db() -> AsyncIterator[Any]:
            yield session

        fastapi_app.dependency_overrides[get_db] = _override_get_db  # type: ignore[attr-defined]
        transport = ASGITransport(app=fastapi_app)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, session
        fastapi_app.dependency_overrides.clear()  # type: ignore[attr-defined]
        await session.rollback()
