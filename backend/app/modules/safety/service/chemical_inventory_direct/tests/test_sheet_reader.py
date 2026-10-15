"""《危险品日报表》电子表格直读读取器单测（chemical-inventory-sheet-source P1-T1）。

fixture 为 2026-10-15 实读数据固化（revision 364，9 活表 169 数据行 + 4 空表），
替身 FakeSheetClient 只实现 read_sheet / read_sheet_metainfo 两方法，零真机依赖。
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.modules.safety.feishu.office_client._base import OfficeResult
from app.modules.safety.service.chemical_inventory_direct.sheet_reader import (
    SheetsInventoryReader,
)

_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "danger_goods_daily_20261015.json"
)

# 子表标题 → 部门 slug（全拼音口径，与 enum_maps._DEPT_LABEL_TO_ENUM 新增段一致）
_SHEET_DEPT = {
    "替考": "tikao", "氟雷": "fulei", "米尔贝": "mierbei", "溶媒回收": "rongmei_huishou",
    "达托": "datuo", "达巴": "daba", "艾默": "aimo", "雷帕": "leipa", "危废库": "weifeiku",
}

# 子表标题 → 数据行数（2026-10-15 实读盘点口径，9 活表合计 169）
_SHEET_DATA_ROWS = {
    "替考": 11, "氟雷": 6, "米尔贝": 18, "溶媒回收": 39, "达托": 30,
    "达巴": 33, "艾默": 15, "雷帕": 6, "危废库": 11,
}
_EMPTY_SHEETS = ("GHtO9Q", "5ct1sn", "m3mr01", "GgfZuX")


def _load_fixture() -> dict[str, Any]:
    return json.loads(_FIXTURE_PATH.read_text())


class FakeSheetClient:
    """office_client 替身：metainfo + 按 sheet_id 回放 fixture 行；可注入失败。"""

    def __init__(
        self,
        fixture: dict[str, Any],
        *,
        metainfo_error: str | None = None,
        sheet_errors: dict[str, str] | None = None,
    ) -> None:
        self._fixture = fixture
        self._metainfo_error = metainfo_error
        self._sheet_errors = sheet_errors or {}
        self.read_ranges: list[str] = []

    async def read_sheet_metainfo(self, spreadsheet_token: str) -> OfficeResult:
        if self._metainfo_error:
            return OfficeResult.failure(self._metainfo_error)
        return OfficeResult.data(self._fixture["metainfo"])

    async def read_sheet(
        self,
        spreadsheet_token: str,
        sheet_range: str,
        *,
        max_rows: int = 500,
        max_cols: int = 50,
    ) -> OfficeResult:
        self.read_ranges.append(sheet_range)
        sid = sheet_range.split("!")[0]
        if sid in self._sheet_errors:
            return OfficeResult.failure(self._sheet_errors[sid])
        rows = self._fixture["sheets"].get(sid)
        if rows is None:
            return OfficeResult.failure(f"子表不存在: {sid}")
        return OfficeResult.data(rows)


@pytest.fixture
def fixture() -> dict[str, Any]:
    return _load_fixture()


def _reader(client: FakeSheetClient) -> SheetsInventoryReader:
    return SheetsInventoryReader(client, "H0YWsAf52hBAIDtmJlxcqThZn2c")


async def test_real_fixture_row_counts_and_departments(fixture: dict[str, Any]) -> None:
    """9 活表全量成行、4 空表跳过；部门按子表标题映射新枚举。"""
    reader = _reader(FakeSheetClient(fixture))
    views = await reader.fetch_all()

    assert len(views) == sum(_SHEET_DATA_ROWS.values()) == 169
    by_dept: dict[str, int] = {}
    for v in views:
        by_dept[v.department] = by_dept.get(v.department, 0) + 1
    expected = {_SHEET_DEPT[t]: n for t, n in _SHEET_DATA_ROWS.items()}
    # 部门枚举与 enum_maps 注册段一致性（标题→slug 单一来源断言）
    from app.modules.safety.chemical_inventory.enum_maps import _DEPT_LABEL_TO_ENUM

    for title, slug in _SHEET_DEPT.items():
        assert _DEPT_LABEL_TO_ENUM.get(title) == slug
    assert by_dept == expected
    # 空表不产生任何视图
    for sid in _EMPTY_SHEETS:
        assert not any(v.feishu_record_id.startswith(f"{sid}:") for v in views)


async def test_full_field_mapping_aimo_first_row(fixture: dict[str, Any]) -> None:
    """艾默 row3 全字段：kg÷1000 归一、上限 T、行标识 {sheet_id}:{行号}。"""
    views = await _reader(FakeSheetClient(fixture)).fetch_all()
    v = next(x for x in views if x.feishu_record_id == "2RRpSr:3")

    assert v.department == "aimo"
    assert v.storage_location == "车间二提取岗位"
    assert v.material_name == "乙醇"
    assert v.package_spec == "0.85"          # 数值单元格 ToString 透传
    assert v.quantity == Decimal("90000")
    assert v.unit == "kg"
    assert v.total_quantity_t == Decimal("90")
    assert v.daily_usage_kg is None           # 该行一昼夜使用量为空
    assert v.max_limit == Decimal("150")      # 150000kg ÷ 1000
    assert v.max_limit_unit == "T"
    assert v.hazard_classes == ["flammable"]  # 「易燃易爆」→ 仅 flammable
    assert v.id == "2RRpSr:3"
    assert v.updated_at is not None           # 读取时刻
    assert v.created_at is None


async def test_hazwaste_missing_daily_usage_column(fixture: dict[str, Any]) -> None:
    """危废库缺「一昼夜使用量」列：daily_usage_kg 全 None，其余列按关键词自适应。"""
    views = await _reader(FakeSheetClient(fixture)).fetch_all()
    hazwaste = [v for v in views if v.department == "weifeiku"]
    assert len(hazwaste) == _SHEET_DATA_ROWS["危废库"]
    assert all(v.daily_usage_kg is None for v in hazwaste)
    # 危废库 row3：米尔贝水层废液 数量空、上限 20000kg → 20T
    v = next(x for x in hazwaste if x.feishu_record_id == "H8wjnP:3")
    assert v.material_name == "米尔贝水层废液"
    assert v.quantity is None
    assert v.total_quantity_t is None
    assert v.unit is None
    assert v.max_limit == Decimal("20")
    assert v.max_limit_unit == "T"


async def test_empty_quantity_rows(fixture: dict[str, Any]) -> None:
    """雷帕当前数量整列为空：quantity/total_quantity_t/unit 均 None，上限照常归一。"""
    views = await _reader(FakeSheetClient(fixture)).fetch_all()
    leipa = [v for v in views if v.department == "leipa"]
    assert leipa
    assert all(v.quantity is None for v in leipa)
    v = next(x for x in leipa if x.feishu_record_id == "AOx7uW:3")
    assert v.max_limit == Decimal("60")       # 60000kg → 60T


async def test_storage_location_newline_stripped(fixture: dict[str, Any]) -> None:
    """达巴 row29 存放部位尾部换行被清理。"""
    views = await _reader(FakeSheetClient(fixture)).fetch_all()
    v = next(x for x in views if x.feishu_record_id == "BFIDM:29" or x.feishu_record_id == "BFICDM:29")
    assert v.storage_location == "车间一达巴制备"


async def test_spec_passthrough_mixed_values(fixture: dict[str, Any]) -> None:
    """规格列混杂（数值/不定/kg每瓶）一律透传字符串，不解析。"""
    views = await _reader(FakeSheetClient(fixture)).fetch_all()
    specs = {v.package_spec for v in views if v.department == "tikao"}
    assert "不定" in specs
    assert "0.45" in specs            # 数值 0.45（45%）透传
    assert "0.5kg/瓶" in specs


async def test_unknown_sheet_title_passthrough_with_warning(
    fixture: dict[str, Any], caplog: pytest.LogCaptureFixture,
) -> None:
    """未映射子表标题：department 原样透传 + 告警日志。"""
    fixture["metainfo"]["sheets"].append({
        "sheetId": "XXnew1", "title": "新车间X", "rowCount": 10, "columnCount": 20,
    })
    fixture["sheets"]["XXnew1"] = [
        ["新车间X危险化学品库存"],
        ["序号", "存放部位", "危险品名称", "规格", "管理类别", "当前数量/kg",
         "一昼夜使用量/kg", "库存上限/kg", "危险性"],
        [1, "甲岗位", "乙醇", 1, "车间储罐", 100, 5, 200, "易燃"],
    ]
    with caplog.at_level(logging.WARNING):
        views = await _reader(FakeSheetClient(fixture)).fetch_all()
    assert any(v.department == "新车间X" for v in views)
    assert any("新车间X" in r.message for r in caplog.records)


async def test_no_header_anchor_skips_sheet(
    fixture: dict[str, Any], caplog: pytest.LogCaptureFixture,
) -> None:
    """前 5 行找不到「危险品名称」表头锚点：跳过该子表 + 告警。"""
    fixture["sheets"]["2158cd"] = [
        ["替考危险化学品库存"],
        ["备注行", "没有表头"],
        [1, "车间二替考层析", "浓缩乙醇"],
    ]
    with caplog.at_level(logging.WARNING):
        views = await _reader(FakeSheetClient(fixture)).fetch_all()
    assert not any(v.department == "tikao" for v in views)
    assert any("2158cd" in r.message for r in caplog.records)


async def test_unknown_columns_ignored(fixture: dict[str, Any]) -> None:
    """未知列（替考备注列）被忽略，不影响映射。"""
    views = await _reader(FakeSheetClient(fixture)).fetch_all()
    v = next(x for x in views if x.feishu_record_id == "2158cd:3")
    assert v.material_name == "浓缩乙醇"
    assert v.remark is None                 # 备注列不在映射关键词内，不落 remark


async def test_strict_raises_on_metainfo_failure(fixture: dict[str, Any]) -> None:
    reader = _reader(FakeSheetClient(fixture, metainfo_error="code=99991672 无权限"))
    with pytest.raises(RuntimeError, match="metainfo"):
        await reader.fetch_all(strict=True)


async def test_non_strict_metainfo_failure_returns_empty(fixture: dict[str, Any]) -> None:
    reader = _reader(FakeSheetClient(fixture, metainfo_error="code=99991672 无权限"))
    assert await reader.fetch_all() == []


async def test_strict_raises_on_sheet_read_failure(fixture: dict[str, Any]) -> None:
    reader = _reader(FakeSheetClient(fixture, sheet_errors={"uVm5xu": "读取失败"}))
    with pytest.raises(RuntimeError, match="uVm5xu"):
        await reader.fetch_all(strict=True)


async def test_non_strict_tolerates_sheet_read_failure(fixture: dict[str, Any]) -> None:
    """容错模式：单子表读失败跳过，其余子表照常返回。"""
    reader = _reader(FakeSheetClient(fixture, sheet_errors={"uVm5xu": "读取失败"}))
    views = await reader.fetch_all()
    expected = sum(_SHEET_DATA_ROWS.values()) - _SHEET_DATA_ROWS["溶媒回收"]
    assert len(views) == expected


async def test_sorted_like_inventory(fixture: dict[str, Any]) -> None:
    views = await _reader(FakeSheetClient(fixture)).fetch_all()
    keys = [(v.department, v.material_name) for v in views]
    assert keys == sorted(keys)


async def test_revision_and_read_time_exposed(fixture: dict[str, Any]) -> None:
    """D6：读取后暴露当日 revision 与读取时刻。"""
    reader = _reader(FakeSheetClient(fixture))
    assert reader.last_revision is None
    await reader.fetch_all()
    assert reader.last_revision == fixture["metainfo"]["revision"]
    assert reader.last_read_at is not None


async def test_read_range_covers_metainfo_dimensions(fixture: dict[str, Any]) -> None:
    """读取窗口由 metainfo 维度驱动（rowCount/columnCount）。"""
    client = FakeSheetClient(fixture)
    await _reader(client).fetch_all()
    assert f"2158cd!A1:T{fixture['metainfo']['sheets'][0]['rowCount']}" in client.read_ranges
    # 危废库 19 列
    hazwaste_meta = next(s for s in fixture["metainfo"]["sheets"] if s["sheetId"] == "H8wjnP")
    assert f"H8wjnP!A1:S{hazwaste_meta['rowCount']}" in client.read_ranges


class TestReviewHardening:
    """审查修复项：行数超限 strict 上抛、anomalies 每次读取重置。"""

    async def test_rowcount_over_limit_strict_raises(
        self, fixture: dict[str, Any],
    ) -> None:
        fixture["metainfo"]["sheets"][0]["rowCount"] = 501
        reader = _reader(FakeSheetClient(fixture))
        with pytest.raises(RuntimeError, match="超过读取上限"):
            await reader.fetch_all(strict=True)

    async def test_rowcount_over_limit_non_strict_reads_capped(
        self, fixture: dict[str, Any],
    ) -> None:
        fixture["metainfo"]["sheets"][0]["rowCount"] = 501
        reader = _reader(FakeSheetClient(fixture))
        views = await reader.fetch_all()  # 容错：跳过/截断不炸
        assert isinstance(views, list)

    async def test_anomalies_reset_per_fetch(
        self, fixture: dict[str, Any],
    ) -> None:
        """单例复用下 anomalies 每次读取重置，不跨调用累积。

        基线：4 张全空预留表（发酵等）静默跳过不产异常，基线为 0。
        """
        fixture["metainfo"]["sheets"].append({
            "sheetId": "XXold", "title": "一次性异常表", "rowCount": 5, "columnCount": 20,
        })
        fixture["sheets"]["XXold"] = [["无表头行"]]
        reader = _reader(FakeSheetClient(fixture))
        await reader.fetch_all()
        base = len(reader.anomalies)
        assert base == 1  # 仅一次性异常表（有内容无表头）；4 空表静默
        assert any("一次性异常表" in a for a in reader.anomalies)
        fixture["sheets"].pop("XXold")
        fixture["metainfo"]["sheets"].pop()
        await reader.fetch_all()
        assert reader.anomalies == []  # 消失且不累积


def test_department_slug_three_mirror_consistency() -> None:
    """9 个 sheet 源部门 slug 在三处镜像一致（enum_maps / schemas / bitable_config registry）。"""
    from app.modules.safety.bitable_config import registry as bc_registry
    from app.modules.safety.chemical_inventory.enum_maps import _DEPT_LABEL_TO_ENUM
    from app.modules.safety.schemas.chemical_inventory import (
        CHEMICAL_DEPARTMENT_LABELS,
    )

    expect = {
        "替考": "tikao", "氟雷": "fulei", "米尔贝": "mierbei",
        "溶媒回收": "rongmei_huishou", "达托": "datuo", "达巴": "daba",
        "艾默": "aimo", "雷帕": "leipa", "危废库": "weifeiku",
    }
    for label, slug in expect.items():
        assert _DEPT_LABEL_TO_ENUM.get(label) == slug
        assert CHEMICAL_DEPARTMENT_LABELS.get(slug) == label
    domain = bc_registry.get_domain("chemical_inventory")
    dept_map = None
    for m in domain.get_kind("inventory").default_mappings:
        if m.get("target_field") == "department":
            dept_map = m.get("value_map") or {}
    assert dept_map is not None
    for label, slug in expect.items():
        assert dept_map.get(label) == slug
