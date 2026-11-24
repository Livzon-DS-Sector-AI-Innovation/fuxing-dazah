"""EHS 变更周度督办 — 周五卡三态与两个速递格子（纯结构验证，不依赖网络）。

覆盖（DESIGN §4/§6）：form+select 结构、按钮 name/value 路由约定、
提交后撤「进展不变」按钮保表单、已反馈态撤按钮+表单、select 选项 99 上限、
周五格（排除/未发送/提示桶）与周一格（三类+已关闭计数）。
"""

from __future__ import annotations

import json

from app.modules.safety.service.ehs_change_followup import cards


def _item(**kw):
    base = dict(
        record_id="recA1",
        change_no="FX-D4-2026-0826",
        title="二期围堰改造",
        status_shown="待验收",
        acceptance_note="",
        progress="已完工待验收收集资料中",
        expected_start="2026-03-01",
        approval_url="https://applink.feishu.cn/x",
        nag_weeks=3,
    )
    base.update(kw)
    return cards.CardItemView(**base)


def _view(**kw):
    base = dict(
        officer_name="杨昆",
        departments="提炼工程四部",
        week_no=48,
        date_label="11-27 周五",
        items=(_item(), _item(record_id="recA2", change_no="FXD4-2026-0930",
                              status_shown="", progress="")),
        change_table_url="https://j0eukrlohu.feishu.cn/base/X?table=T",
    )
    base.update(kw)
    return cards.FridayCardView(**base)


def _elements(card: dict, tag: str) -> list[dict]:
    return [e for e in card["body"]["elements"] if e.get("tag") == tag]


def _form(card: dict) -> dict:
    return _elements(card, "form")[0]


# ═══════════════════════════════════════════════════════════
# 周五卡三态
# ═══════════════════════════════════════════════════════════

class TestFridayCard:
    def test_initial_state_structure(self):
        card = cards.build_friday_card(_view(), "dp-1")
        assert card["schema"] == "2.0"
        assert card["header"]["title"]["content"] == "⏰ EHS变更周度督办 · 未验收 2 项"
        assert "第 48 周（11-27 周五）" in card["header"]["subtitle"]["content"]
        # 全部变更放同一个正文块（DESIGN §4：十几项也只有一个正文元素）
        md = _elements(card, "markdown")
        items_block = md[0]["content"]
        assert "FX-D4-2026-0826" in items_block and "FXD4-2026-0930" in items_block
        assert "[审批详情](https://applink.feishu.cn/x)" in items_block
        assert "状态未填" in items_block
        assert "第 3 周督办" in items_block
        # 表单：select（值=record_id）+ input + submit 按钮（name 携带 dispatch_id）
        form = _form(card)
        select = [e for e in form["elements"] if e["tag"] == "select_static"][0]
        assert select["options"][0]["value"] == "recA1"
        submit = [e for e in form["elements"] if e["tag"] == "button"][0]
        assert submit["name"] == "ecf_submit_dp-1"
        assert submit["form_action_type"] == "submit"
        # 「进展不变」按钮：name/value 路由约定
        button_cols = _elements(card, "column_set")
        flat = [
            btn for cs in button_cols
            for column in cs["columns"] for btn in column["elements"]
        ]
        unchanged = [b for b in flat if b.get("name", "").startswith("ecf_unchanged_")]
        assert len(unchanged) == 1
        assert unchanged[0]["name"] == "ecf_unchanged_dp-1"
        assert json.loads(unchanged[0]["value"])["scope"] == cards.SCOPE
        # 打开变更表链接
        assert any("打开变更表" in e["content"] for e in md)

    def test_partial_state_keeps_form_drops_unchanged_button(self):
        """提交过进展：表单保留，「进展不变」按钮撤掉，正文出现 ✅ 提交行。"""
        view = _view(
            items=(_item(replied_progress="已进料", replied_at_short="15:02"),),
            has_replies=True,
        )
        card = cards.build_friday_card(view, "dp-2")
        md = _elements(card, "markdown")[0]["content"]
        assert "✅ FX-D4-2026-0826：已进料（15:02）" in md
        assert _form(card)  # 表单保留
        flat = [
            btn for cs in _elements(card, "column_set")
            for column in cs["columns"] for btn in column["elements"]
        ]
        assert not [b for b in flat if b.get("name", "").startswith("ecf_unchanged_")]

    def test_responded_state_drops_form_and_button(self):
        view = _view(responded_unchanged_at="14:32")
        card = cards.build_friday_card(view, "dp-3")
        assert not _elements(card, "form")
        assert not _elements(card, "column_set")
        assert any("已反馈：其余变更进展不变，无需更新（14:32）" in e["content"]
                   for e in _elements(card, "markdown"))

    def test_select_options_capped_at_99(self):
        items = tuple(
            _item(record_id=f"rec{i}", change_no=f"FX-{i:04d}") for i in range(120)
        )
        card = cards.build_friday_card(_view(items=items), "dp-4")
        select = [e for e in _form(card)["elements"] if e["tag"] == "select_static"][0]
        assert len(select["options"]) == 99


# ═══════════════════════════════════════════════════════════
# 速递格子
# ═══════════════════════════════════════════════════════════

class TestFridayCell:
    def test_full_buckets(self):
        view = cards.FridayDigestView(
            total_todo=86,
            terminated_count=8,
            excluded=(("FXSC-2026001", "验收单审批中"),),
            stale_accepted=("FXPD2025-008",),
            dispatched=[
                cards.DigestDispatchView(
                    officer_name="杨昆", departments="提炼工程四部",
                    change_nos=("FX-D4-2026-0826", "FXD4-2026-0930"), sent=True,
                ),
                cards.DigestDispatchView(
                    officer_name="李四", departments="设备工程部",
                    change_nos=("FX-E-1",), sent=False,
                ),
            ],
            unsent_departments=("人力资源部 1 项",),
        )
        cell = cards.build_friday_cell(view)
        assert cell.tag_text == "变更督办"
        assert "未验收 **86** 项" in cell.stats
        assert "已私发 **1** 人" in cell.stats
        assert "杨昆（提炼工程四部）：FX-D4-2026-0826、FXD4-2026-0930" in cell.detail
        assert "未送达" in cell.detail and "李四" in cell.detail
        assert "变更中止 8 项" in cell.detail
        assert "排除待确认 1 项" in cell.detail
        assert "FXSC-2026001（验收单审批中）" in cell.detail
        assert "- 人力资源部 1 项（未配置分管安全员）" in cell.detail
        assert "1 项验收已通过但状态没改" in cell.detail


class TestMondayCell:
    def test_categories_and_counts(self):
        view = cards.MondayDigestView(
            not_updated=[cards.MondayCategoryGroup(
                department="提炼工程四部", officer_name="杨昆",
                change_nos=("FX-A-1", "FX-A-2"),
            )],
            unchanged=[cards.MondayCategoryGroup(
                department="环保工程中心", officer_name="罗建华",
                change_nos=("FX-B-1",),
            )],
            updated=[cards.MondayCategoryGroup(
                department="提炼工程一部", officer_name="郑雅杰",
                change_nos=("FXD1-2026-07-13",),
                updated_lines=("FXD1-2026-07-13：纯化新工艺试生产（卡片提交 11-27）",),
            )],
            friday_total=86,
            closed_count=8,
        )
        cell = cards.build_monday_cell(view)
        assert "未更新 **2** 项" in cell.stats
        assert "进展不变 **1** 项" in cell.stats
        assert "更新 **1** 项" in cell.stats
        assert "周五督办 86 项，本周已关闭 8 项" in cell.zone
        assert "① 未更新（2 项）" in cell.detail
        assert "③ 更新（1 项）" in cell.detail
        assert "FXD1-2026-07-13：纯化新工艺试生产（卡片提交 11-27）" in cell.detail

    def test_empty_groups_render_wu(self):
        cell = cards.build_monday_cell(cards.MondayDigestView())
        assert "① 未更新（0 项）" in cell.detail
        assert cell.detail.count("- 无") == 3
