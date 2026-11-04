"""灭火器台账（消防器材首张真实表）列映射校准回归（2026-10-20，10-29 修订）。

真实表：base Ngd7bJRxMaf6DpsqwlIcZtvpnce / tblcnSMMA8vs5p33，12 列（见
REAL_FIRE_HEADERS）。锁定校准口径：
1. 两段式映射自动命中：到期日期（公式自动生成）→主锚点（2026-10-29 拍板，
   公式列=生产日期+5年；人工「到期日期」两列并存时退役）、
   到期提醒人员.部门→责任部门、灭火器类型→类别、位置；owner 候选补「到期提醒人员」；
2. person 责任人列同取 name+open_id（派发 @mention 免解析直取）；
3. 无编号/名称列 → 合成（类别·位置 / 类别），不进信息不全清单。
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.modules.safety.facilities.engine import select_due
from app.modules.safety.facilities.ledger import (
    BIZ_FIRE,
    LEAD_DAYS,
    resolve_columns,
    to_view,
    to_views,
)

REAL_FIRE_HEADERS = [
    "数量", "灭火器类型", "生产日期", "到期日期", "到期提醒人员", "岗位",
    "到期日期（公式自动生成）", "到期提醒人员.部门", "型号", "位置", "到期提醒", "车间",
]


def _ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1000)


def _rec(record_id: str, fields: dict) -> dict:
    return {"record_id": record_id, "fields": fields}


def _fire_row(
    *,
    typ: str = "手提式干粉灭火器",
    model: str = "MFZ/ABC4",
    dept: str = "提炼工程一部",
    owner_name: str = "郑雅杰",
    owner_id: str = "ou_zheng",
    post: str = "仪表仓库",
    location: str = "仪表仓库门边",
    qty: int = 2,
    produced: date = date(2025, 7, 1),
    expires: date = date(2030, 7, 1),
) -> dict:
    return _rec(
        "rec_test",
        {
            "数量": qty,
            "灭火器类型": typ,
            "生产日期": _ms(produced),
            "到期日期": _ms(expires),
            "到期提醒人员": [{"id": owner_id, "name": owner_name}],
            "岗位": post,
            "到期提醒人员.部门": [dept],
            "型号": [model],
            "位置": location,
            "车间": None,
        },
    )


def test_real_headers_column_resolution():
    cols = resolve_columns(REAL_FIRE_HEADERS)
    # 2026-10-29 拍板：公式自动生成列（=生产日期+5年）为主锚点，人工「到期日期」退役
    assert cols["next_date"] == "到期日期（公式自动生成）"
    assert cols["department"] == "到期提醒人员.部门"
    assert cols["category"] == "灭火器类型"
    assert cols["location"] == "位置"
    assert cols["owner"] == "到期提醒人员"
    # 人工「到期日期」两列并存时不再被任何标准字段认领（精确段已被公式列占位）
    assert "到期日期" not in cols.values()
    assert cols.get("last_date") is None
    assert cols.get("cycle_months") is None


def test_formula_column_envelope_parsed_and_wins():
    """公式列 {'type':5,'value':[ms]} 解包取锚点；人工到期列同存时不参与。"""
    row = _fire_row(expires=date(2026, 10, 1))
    row["fields"]["到期日期（公式自动生成）"] = {"type": 5, "value": [_ms(date(2028, 6, 1))]}
    v = to_view(row, BIZ_FIRE)  # 单行现解析：表头含两列
    assert v.anchor == date(2028, 6, 1)
    assert v.anchor_source == "next_date"


def test_formula_column_missing_value_falls_to_incomplete():
    """全表头含公式列但某行公式值缺（key 缺失）→ 该行主锚点不可得进信息不全。"""
    row_a = _fire_row(expires=date(2030, 7, 1))
    row_a["fields"]["到期日期（公式自动生成）"] = {"type": 5, "value": [_ms(date(2030, 7, 1))]}
    row_b = _fire_row(expires=date(2030, 7, 1))  # 无公式值：人工列不被认领 → 无锚点
    row_b["record_id"] = "rec_no_formula"
    views = to_views([row_a, row_b], BIZ_FIRE)
    anchors = {v.record_id: v.anchor for v in views}
    assert anchors["rec_test"] == date(2030, 7, 1)
    assert anchors["rec_no_formula"] is None
    incomplete = {v.record_id: v.incomplete_reason for v in views}
    assert incomplete["rec_no_formula"]


def test_real_row_view_owner_open_id_and_synthesis():
    views = to_views([_fire_row()], BIZ_FIRE)
    v = views[0]
    assert v.owner == "郑雅杰"
    assert v.owner_open_id == "ou_zheng"
    assert v.department == "提炼工程一部"
    assert v.anchor == date(2030, 7, 1)
    assert v.anchor_source == "next_date"
    # 无编号/名称列：合成「类别·位置」与「类别」
    assert v.equipment_no == "手提式干粉灭火器·仪表仓库门边"
    assert v.name == "手提式干粉灭火器"
    assert v.incomplete_reason is None
    assert v.active  # 无状态列 → 视为在用


def test_owner_text_column_has_no_open_id():
    row = _fire_row()
    row["fields"]["到期提醒人员"] = "王五"
    v = to_view(row, BIZ_FIRE)
    assert v.owner == "王五"
    assert v.owner_open_id is None


def test_select_due_sixty_day_window_hits_overdue_and_soon():
    rows = [
        _fire_row(location="陶瓷膜旁立柱", expires=date(2026, 10, 1)),   # 已过期
        _fire_row(location="2#冻干机房", typ="手提式二氧化碳灭火器",
                  model="MT/2", expires=date(2026, 11, 1)),               # 60 天窗内
        _fire_row(location="博士室", expires=date(2026, 12, 25)),         # 窗外（60 天=12-19）
        _fire_row(),                                                     # 2030 远期
    ]
    for r, rid in zip(rows, ["r1", "r2", "r3", "r4"]):
        r["record_id"] = rid
    views = to_views(rows, BIZ_FIRE)
    out = select_due(views, today=date(2026, 10, 20), lead_days=LEAD_DAYS[BIZ_FIRE])
    assert sorted(c.view.record_id for c in out) == ["r1", "r2"]
    by_rid = {c.view.record_id: c for c in out}
    assert by_rid["r1"].due_date == date(2026, 10, 1)   # 已过期照派（补派口径）
    assert by_rid["r2"].due_date == date(2026, 11, 1)
    assert by_rid["r1"].task_subtype == "检查"          # 消防主锚点文案


async def test_resolve_assignee_prefers_owner_open_id():
    from app.modules.safety.facilities.dispatch import _resolve_assignee

    class _BoomResolver:
        async def resolve_by_name(self, name, department_hint=None):
            raise AssertionError("owner_open_id 直取时不应走解析链")

        async def resolve_department_leader(self, department_name):
            raise AssertionError("owner_open_id 直取时不应走部门负责人兜底")

    v = to_view(_fire_row(), BIZ_FIRE)
    open_id, name = await _resolve_assignee(_BoomResolver(), v)
    assert (open_id, name) == ("ou_zheng", "郑雅杰")
