"""labor_supply 直读 reader 单测（fake page client 注入，不真调飞书）。

数据形态锚定 2026-11-09 实测导出（tmp/labor-products.ndjson 102 行 /
tmp/labor-positions.ndjson 969 行）：
- 劳保用品汇总：select 字段 API 返回 ``["值"]`` 列表，附件 ``[{file_token,name,size}]``，
  有效期/年为 number；
- 岗位对应劳保用品：部门/类别等 select 列表，防护类型为 lookup 直接回字符串，
  岗位/工种/检测项目为 text，配备行=有劳保用品名称的行（969 中 254）。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.safety.service.labor_supply import reader as ls_reader
from app.modules.safety.service.labor_supply.reader import (
    LaborProductView,
    PositionStandardView,
    coverage_stats,
    to_standard_view,
    to_view,
)


def _product_record(**overrides: Any) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "record_id": "recA1",
        "fields": {
            "劳保用品名称": ["防尘口罩"],
            "型号": ["3M 9502+基础款"],
            "类别": ["口罩"],
            "防护类型": ["呼吸防护"],
            "单位": "个",
            "厂家": "3M",
            "有效期/年": 2.5,
            "检测报告": [{"file_token": "ftk1", "name": "report.pdf", "size": 100}],
            "说明书/产品介绍": [{"file_token": "ftk2", "name": "manual.pdf", "size": 200}],
        },
    }
    rec["fields"].update(overrides.pop("fields", {}))
    rec.update(overrides)
    return rec


# ── to_view ──────────────────────────────────────────────────────

def test_to_view_full_row() -> None:
    view = to_view(_product_record())
    assert view == LaborProductView(
        record_id="recA1",
        name="防尘口罩",
        model="3M 9502+基础款",
        category="口罩",
        protection_type="呼吸防护",
        unit="个",
        vendor="3M",
        lifespan_years=2.5,
        report_attachments=[{"file_token": "ftk1", "name": "report.pdf", "size": 100}],
        manual_attachments=[{"file_token": "ftk2", "name": "manual.pdf", "size": 200}],
    )
    assert view.has_report is True
    assert view.has_manual is True


def test_to_view_empty_values_tolerated() -> None:
    view = to_view(
        _product_record(
            fields={
                "劳保用品名称": ["劳保安全鞋"],
                "厂家": None,
                "有效期/年": None,
                "检测报告": [],
                "说明书/产品介绍": None,
            },
        )
    )
    assert view.name == "劳保安全鞋"
    assert view.vendor == ""
    assert view.lifespan_years is None
    assert view.has_report is False
    assert view.has_manual is False


def test_to_view_nameless_row_skipped() -> None:
    assert to_view(_product_record(fields={"劳保用品名称": []})) is None
    assert to_view({"record_id": "recX", "fields": {}}) is None


# ── coverage_stats ───────────────────────────────────────────────

def test_coverage_stats_counts_and_percentages() -> None:
    views = [
        to_view(_product_record()),  # 全填
        to_view(_product_record(record_id="recA2", fields={"厂家": None})),
        to_view(
            _product_record(
                record_id="recA3",
                fields={
                    "劳保用品名称": ["防化手套"],
                    "防护类型": ["手部防护"],
                    "检测报告": [],
                    "说明书/产品介绍": [],
                    "有效期/年": None,
                },
            )
        ),
    ]
    stats = coverage_stats(views)
    assert stats["total"] == 3
    assert stats["protection_types"] == {"呼吸防护": 2, "手部防护": 1}
    # 厂家 2/3（rec2 置空）、检测报告 2/3、说明书 2/3、有效期 2/3
    assert stats["vendor_filled"] == 2
    assert stats["report_filled"] == 2
    assert stats["manual_filled"] == 2
    assert stats["lifespan_filled"] == 2
    assert stats["report_coverage"] == pytest.approx(2 / 3, abs=1e-3)


def test_coverage_stats_empty_list_safe() -> None:
    stats = coverage_stats([])
    assert stats["total"] == 0
    assert stats["protection_types"] == {}
    assert stats["report_coverage"] == 0.0


# ── to_standard_view（岗位对应劳保用品配备行）────────────────────

def _position_record(**overrides: Any) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "record_id": "recP1",
        "fields": {
            "部门": ["提炼工程五部"],
            "岗位/工种": "配料工",
            "单元/车间": "发酵工程部（3#楼）",
            "劳保用品名称": ["防尘口罩"],
            "型号": ["3M 9502+基础款"],
            "类别": ["口罩"],
            "防护类型": "呼吸防护",  # lookup → 直接字符串
            "周期": ["按需"],
            "配备情况": ["个人"],
            "检测项目": "其他粉尘（总尘）",
            "采样点位/对象": "配料间1#",
            "部门安全员": [{"id": "ou_x", "name": "邓宇"}],  # user 列不消费
        },
    }
    rec["fields"].update(overrides.pop("fields", {}))
    rec.update(overrides)
    return rec


def test_to_standard_view_equipped_row() -> None:
    view = to_standard_view(_position_record())
    assert isinstance(view, PositionStandardView)
    assert view.department == "提炼工程五部"
    assert view.position == "配料工"
    assert view.name == "防尘口罩"
    assert view.protection_type == "呼吸防护"
    assert view.cycle == "按需"
    assert view.provision == "个人"
    assert view.monitor_item == "其他粉尘（总尘）"


def test_to_standard_view_pure_monitoring_row_skipped() -> None:
    """969 行里 715 行纯检测矩阵行（无劳保用品名称）→ None（只留配备行）。"""
    assert to_standard_view(_position_record(fields={"劳保用品名称": []})) is None


def test_to_standard_view_optional_fields_tolerated() -> None:
    view = to_standard_view(
        _position_record(
            fields={
                "岗位/工种": None,
                "配备情况": [],
                "周期": None,
            },
        )
    )
    assert view is not None
    assert view.position == ""
    assert view.provision == ""
    assert view.cycle == ""


# ── LaborSupplyReader（fake page client）─────────────────────────

class _FakePageClient:
    """记录 field_names 投影并回放预制记录。"""

    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = records
        self.calls: list[dict[str, Any]] = []

    async def search_records(
        self,
        *,
        table_id: str | None = None,
        field_names: list[str] | None = None,
        page_size: int = 500,
        page_token: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        self.calls.append(
            {"table_id": table_id, "field_names": field_names, "page_token": page_token}
        )
        if page_token:
            return {"items": [], "has_more": False}
        return {"items": self.records, "has_more": False}


@pytest.mark.asyncio
async def test_fetch_products_projects_requested_fields() -> None:
    client = _FakePageClient([_product_record()])
    r = ls_reader.LaborSupplyReader(product_client=client)
    views = await r.fetch_products()
    assert [v.record_id for v in views] == ["recA1"]
    assert client.calls[0]["field_names"] is not None
    assert "劳保用品名称" in client.calls[0]["field_names"]
    assert "检测报告" in client.calls[0]["field_names"]


@pytest.mark.asyncio
async def test_fetch_position_standards_filters_equipped_rows() -> None:
    client = _FakePageClient(
        [_position_record(), _position_record(fields={"劳保用品名称": []})]
    )
    r = ls_reader.LaborSupplyReader(position_client=client)
    views = await r.fetch_position_standards()
    assert len(views) == 1
    assert views[0].name == "防尘口罩"


# ── TTL 缓存包装 ────────────────────────────────────────────────

class _CountingReader:
    def __init__(self) -> None:
        self.product_calls = 0
        self.standard_calls = 0

    async def fetch_products(self) -> list[LaborProductView]:
        self.product_calls += 1
        return [to_view(_product_record())]

    async def fetch_position_standards(self) -> list[PositionStandardView]:
        self.standard_calls += 1
        return []


@pytest.mark.asyncio
async def test_cached_reader_ttl_window() -> None:
    inner = _CountingReader()
    cached = ls_reader.CachedLaborReader(inner, ttl_seconds=60)
    await cached.fetch_products()
    await cached.fetch_products()
    assert inner.product_calls == 1  # TTL 窗口内命中缓存
    await cached.fetch_position_standards()
    await cached.fetch_position_standards()
    assert inner.standard_calls == 1


@pytest.mark.asyncio
async def test_cached_reader_strict_bypasses_cache() -> None:
    inner = _CountingReader()
    cached = ls_reader.CachedLaborReader(inner, ttl_seconds=60)
    await cached.fetch_products(strict=True)
    await cached.fetch_products(strict=True)
    assert inner.product_calls == 2


@pytest.mark.asyncio
async def test_cached_reader_ttl_zero_passthrough() -> None:
    inner = _CountingReader()
    cached = ls_reader.CachedLaborReader(inner, ttl_seconds=0)
    await cached.fetch_products()
    await cached.fetch_products()
    assert inner.product_calls == 2


@pytest.mark.asyncio
async def test_fetch_failure_propagates_not_swallowed() -> None:
    """审查修复守卫：拉取失败必须上抛（不吞成空列表缓存进 TTL）。"""

    class _BoomClient:
        async def search_records(self, **_: Any) -> dict[str, Any]:
            raise RuntimeError("bitable unreachable")

    r = ls_reader.LaborSupplyReader(product_client=_BoomClient())  # type: ignore[arg-type]
    with pytest.raises(Exception):
        await r.fetch_products()


# ── 开关 ────────────────────────────────────────────────────────

def test_gate_default_on_and_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.safety.service.labor_supply import config

    monkeypatch.delenv("SAFETY_LABOR_SUPPLY_DIRECT_ENABLED", raising=False)
    assert config.direct_enabled() is True  # 无镜像回退路径，默认开（仅下线闸）
    monkeypatch.setenv("SAFETY_LABOR_SUPPLY_DIRECT_ENABLED", "0")
    assert config.direct_enabled() is False
