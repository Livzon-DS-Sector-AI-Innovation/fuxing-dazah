"""facilities-p1 票 01：三台账列映射/锚点推算/三态信封测试。

接缝（照 test_domain_pages 手法）：
- 列映射/锚点推算/信息全不全 = ledger.py 纯函数直测；
- 三态信封 = FacilitiesLedgerReader 注入 FakePageClient（page 级协议替身）；
- not_connected 走真 store 路径（registry 默认连接=None → BitableConfigError）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.modules.safety.facilities import ledger, page
from app.modules.safety.facilities.ledger import (
    BIZ_ACCESSORY,
    BIZ_FIRE,
    BIZ_SPECIAL,
    LedgerSummary,
    anchors_of_biz,
    is_active_status,
    resolve_columns,
    to_view,
    to_views,
)
from app.modules.safety.facilities.reader import FacilitiesLedgerReader
from app.modules.safety.service.bitable_direct.errors import BitableQueryError


def _bj_today() -> date:
    return (datetime.now(UTC) + timedelta(hours=8)).date()


def _ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)


def _rec(record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    return {"record_id": record_id, "fields": fields}


class FakePageClient:
    """BitablePageClient 协议替身：预置记录一次性返回。"""

    def __init__(self, items: list[dict[str, Any]], *, boom: bool = False) -> None:
        self._items = items
        self._boom = boom

    async def search_records(self, **kwargs: Any) -> dict[str, Any]:
        if self._boom:
            raise BitableQueryError("Bitable 查询失败: code=1254043")
        return {"items": self._items, "has_more": False, "page_token": None}


# ── 列映射解析 ──────────────────────────────────────────────────────


def test_resolve_columns_exact_match_priority():
    cols = resolve_columns(
        ["设备编号", "设备名称", "责任部门", "责任人", "上次校验日期",
         "校验周期（月）", "下次校验日期", "设备状态"]
    )
    assert cols["equipment_no"] == "设备编号"
    assert cols["name"] == "设备名称"
    assert cols["department"] == "责任部门"
    assert cols["owner"] == "责任人"
    assert cols["last_date"] == "上次校验日期"
    assert cols["cycle_months"] == "校验周期（月）"
    assert cols["next_date"] == "下次校验日期"
    assert cols["status"] == "设备状态"


def test_resolve_columns_fuzzy_match_variant_names():
    """列名变体（精确未命中）走关键词模糊：一个列只归一个标准字段。"""
    cols = resolve_columns(
        ["附件编号", "名称", "所在部门", "最近检验日期", "检验周期", "下次检验日期", "使用状态"]
    )
    assert cols["equipment_no"] == "附件编号"
    assert cols["name"] == "名称"
    assert cols["department"] == "所在部门"
    assert cols["last_date"] == "最近检验日期"
    assert cols["cycle_months"] == "检验周期"
    assert cols["next_date"] == "下次检验日期"
    assert cols["status"] == "使用状态"


def test_resolve_columns_fire_refill_not_claimed_by_next():
    """「下次换药日期」应归 refill_due，不能被 next_date 的模糊规则认领。"""
    cols = resolve_columns(["器材编号", "下次换药日期", "报废到期", "下次检查日期"])
    assert cols["refill_due"] == "下次换药日期"
    assert cols["scrap_due"] == "报废到期"
    assert cols["next_date"] == "下次检查日期"


def test_resolve_columns_missing_columns_absent():
    cols = resolve_columns(["编号", "名称"])
    assert "next_date" not in cols
    assert "department" not in cols


# ── 视图与锚点 ──────────────────────────────────────────────────────


def test_to_view_anchor_from_next_date():
    today = _bj_today()
    v = to_view(
        _rec("r1", {
            "设备编号": "AQ-001", "设备名称": "安全阀", "责任部门": "提炼一部",
            "下次校验日期": _ms(today + timedelta(days=10)),
            "设备状态": "在用",
        }),
        BIZ_ACCESSORY,
    )
    assert v.anchor == today + timedelta(days=10)
    assert v.anchor_source == "next_date"
    assert v.active
    assert v.incomplete_reason is None


def test_to_view_anchor_derived_from_last_plus_cycle():
    last = date(2026, 1, 31)
    v = to_view(
        _rec("r2", {
            "设备编号": "AQ-002",
            "上次校验日期": _ms(last), "校验周期（月）": "12",
        }),
        BIZ_ACCESSORY,
    )
    # 1-31 + 12 月 → 次年 1-31（自然月，不跨月夹日）
    assert v.anchor == date(2027, 1, 31)
    assert v.anchor_source == "derived"


def test_to_view_anchor_derived_month_end_clamp():
    last = date(2026, 1, 31)
    v = to_view(
        _rec("r3", {"编号": "X1", "上次校验日期": _ms(last), "周期": "1"}),
        BIZ_ACCESSORY,
    )
    assert v.anchor == date(2026, 2, 28)  # 日溢出夹到月末


def test_to_view_incomplete_when_no_anchor():
    v = to_view(_rec("r4", {"设备编号": "AQ-003", "名称": "压力表"}), BIZ_ACCESSORY)
    assert v.anchor is None
    assert v.anchor_source == "none"
    assert v.incomplete_reason and "推算" in v.incomplete_reason


def test_to_view_equipment_no_synthesized_when_missing():
    """2026-10-20 灭火器台账拍板：无编号列→合成展示编号，不再进信息不全清单。"""
    today = _bj_today()
    v = to_view(
        _rec("r5", {"设备名称": "灭火器", "下次检查日期": _ms(today)}),
        BIZ_FIRE,
    )
    # 类别/位置都缺 → 回退名称「灭火器」
    assert v.equipment_no == "灭火器"
    assert v.incomplete_reason is None  # 锚点在，编号已合成，不再「缺编号」
    assert v.equipment_label == "灭火器"


def test_to_view_status_missing_means_active():
    v = to_view(_rec("r6", {"设备编号": "AQ-004", "下次校验日期": _ms(_bj_today())}), BIZ_ACCESSORY)
    assert v.status == ""
    assert v.active


def test_to_view_status_inactive_keywords():
    v = to_view(
        _rec("r7", {"设备编号": "AQ-005", "设备状态": "已报废",
                     "下次校验日期": _ms(_bj_today())}),
        BIZ_ACCESSORY,
    )
    assert not v.active
    assert not is_active_status("停用")
    assert is_active_status("在用")
    assert is_active_status("未知值")


def test_to_views_shared_columns_across_rows():
    """全表并集表头解析一次，空值行共享列映射（缺日期行仍能走推算降级）。"""
    views = to_views(
        [
            _rec("a", {"设备编号": "A", "下次校验日期": _ms(date(2026, 6, 1))}),
            _rec("b", {"设备编号": "B", "上次校验日期": _ms(date(2026, 1, 1)), "周期": "6"}),
        ],
        BIZ_ACCESSORY,
    )
    assert views[0].anchor == date(2026, 6, 1)
    assert views[1].anchor == date(2026, 7, 1)
    assert views[1].anchor_source == "derived"


def test_fire_anchors_include_refill_and_scrap():
    specs = anchors_of_biz(BIZ_FIRE)
    assert [s.field for s in specs] == ["next_date", "refill_due", "scrap_due"]
    assert [s.subtype for s in specs] == ["检查", "换药", "报废更换"]
    assert [s.field for s in anchors_of_biz(BIZ_SPECIAL)] == ["next_date"]
    assert anchors_of_biz(BIZ_SPECIAL)[0].subtype == "定期检验"


def test_special_fields_mapped():
    v = to_view(
        _rec("s1", {
            "设备编号": "TE-01", "注册代码": "3010123456", "检验类别": "定期检验",
            "检验机构": "省特检院", "接入监控": "是",
            "下次检验日期": _ms(date(2026, 12, 1)),
        }),
        BIZ_SPECIAL,
    )
    assert v.register_code == "3010123456"
    assert v.inspection_category == "定期检验"
    assert v.agency == "省特检院"
    assert v.monitor_flag is True


def test_summary_buckets():
    today = date(2026, 10, 20)
    mk = lambda rid, anchor, status="": to_view(  # noqa: E731
        _rec(rid, {
            "设备编号": rid,
            **({"下次校验日期": _ms(anchor)} if anchor else {}),
            **({"设备状态": status} if status else {}),
        }),
        BIZ_ACCESSORY,
    )
    views = [
        mk("a", today - timedelta(days=5)),          # 逾期
        mk("b", today + timedelta(days=10)),         # 30 天内
        mk("c", today + timedelta(days=60)),         # 未到期
        mk("d", None),                               # 信息不全（无锚点）
        mk("e", today - timedelta(days=1), "已报废"),  # 非在用不计逾期
    ]
    s = LedgerSummary.build(views, today)
    assert (s.total, s.active, s.overdue, s.due_30d, s.incomplete) == (5, 4, 1, 1, 1)


# ── 三态信封（reader 注入替身）───────────────────────────────────────


async def test_ledger_page_live_with_fake_client():
    today = _bj_today()
    items = [
        _rec("r1", {"设备编号": "AQ-1", "下次校验日期": _ms(today + timedelta(days=3))}),
        _rec("r2", {"设备编号": "AQ-2"}),
    ]
    reader = FacilitiesLedgerReader({BIZ_ACCESSORY: FakePageClient(items)})
    out = await page.build_ledger_page(
        "accessories", reader=reader, today=today,
    )
    assert out["status"] == "live"
    assert out["summary"]["total"] == 2
    assert out["summary"]["overdue"] == 0
    assert out["summary"]["due_30d"] == 1
    assert out["summary"]["incomplete"] == 1
    assert out["ledger"]["meta"]["total"] == 2
    # 锚点升序：有锚点的行在前
    assert out["ledger"]["data"][0]["equipment_no"] == "AQ-1"
    assert out["ledger"]["data"][0]["remaining_days"] == 3


async def test_ledger_page_pagination():
    today = _bj_today()
    items = [
        _rec(f"r{i}", {"设备编号": f"N{i}", "下次校验日期": _ms(today + timedelta(days=i))})
        for i in range(1, 6)
    ]
    reader = FacilitiesLedgerReader({BIZ_FIRE: FakePageClient(items)})
    out = await page.build_ledger_page(
        "fire-equipment", page=2, page_size=2, reader=reader, today=today,
    )
    assert out["ledger"]["meta"]["total"] == 5
    assert [r["equipment_no"] for r in out["ledger"]["data"]] == ["N3", "N4"]


async def test_ledger_page_degraded_on_query_error():
    reader = FacilitiesLedgerReader({BIZ_SPECIAL: FakePageClient([], boom=True)})
    out = await page.build_ledger_page("special-equipment", reader=reader)
    assert out["status"] == "degraded"
    assert out["errors"]


async def test_ledger_page_not_connected_without_client():
    """未注入替身 → 真 store 路径：facilities 三 kind 连接位空 → not_connected。"""
    out = await page.build_ledger_page(
        "accessories", reader=FacilitiesLedgerReader(None),
    )
    assert out["status"] == "not_connected"
    assert out["summary"] is None
    assert out["ledger"]["data"] == []


async def test_ledger_page_unknown_url_key():
    import pytest

    with pytest.raises(ValueError):
        await page.build_ledger_page("nope", reader=FacilitiesLedgerReader(None))


def test_registry_facilities_kinds_registered():
    from app.modules.safety.bitable_config.registry import REGISTRY

    kinds = {k.kind for k in REGISTRY["facilities"].kinds}
    assert {
        "equipment_ledger", "inspection_record",
        "accessory_ledger", "fire_equipment_ledger", "special_equipment_ledger",
    } <= kinds
    # 连接位留空（不播种、无默认连接）
    for kind in REGISTRY["facilities"].kinds:
        if kind.kind in {"accessory_ledger", "fire_equipment_ledger", "special_equipment_ledger"}:
            assert kind.default_connection is None


def test_url_key_biz_mapping_roundtrip():
    assert ledger.URL_TO_BIZ["accessories"] == BIZ_ACCESSORY
    assert ledger.URL_TO_BIZ["fire-equipment"] == BIZ_FIRE
    assert ledger.URL_TO_BIZ["special-equipment"] == BIZ_SPECIAL
    assert ledger.LEAD_DAYS[BIZ_SPECIAL] == 45
    assert ledger.LEAD_DAYS[BIZ_ACCESSORY] == 30
    # 消防 60 天：灭火器换新含采购周期约 2 个月（2026-10-20 拍板）
    assert ledger.LEAD_DAYS[BIZ_FIRE] == 60


# ── 行输出 record_url（facilities-frontend：连接已配/未配两态）───────


async def test_ledger_page_record_url_configured_and_missing(monkeypatch):
    """live 行带飞书直达链接；连接未配 → null。

    monkeypatch 替换 store.get_connection 方法本身：绕开 TTL 缓存与
    dev 库已登记的 fire 真实连接，两态均确定性复现。
    """
    from app.modules.safety.bitable_config import store as store_mod

    class _Conn:
        app_token = "TokLedger"
        table_id = "TblLedger"

    items = [
        _rec("r1", {"设备编号": "AQ-9", "下次校验日期": _ms(_bj_today())}),
        _rec("r2", {"设备编号": "AQ-8"}),
    ]
    reader = FacilitiesLedgerReader({BIZ_ACCESSORY: FakePageClient(items)})

    monkeypatch.setattr(
        store_mod.store, "get_connection",
        lambda domain, kind: _Conn() if kind == "accessory_ledger" else None,
    )
    out = await page.build_ledger_page("accessories", reader=reader)
    assert out["status"] == "live"
    assert [r["record_url"] for r in out["ledger"]["data"]] == [
        "https://j0eukrlohu.feishu.cn/base/TokLedger?table=TblLedger&record=r1",
        "https://j0eukrlohu.feishu.cn/base/TokLedger?table=TblLedger&record=r2",
    ]

    monkeypatch.setattr(store_mod.store, "get_connection", lambda domain, kind: None)
    out = await page.build_ledger_page("accessories", reader=reader)
    assert out["status"] == "live"
    assert all(r["record_url"] is None for r in out["ledger"]["data"])
