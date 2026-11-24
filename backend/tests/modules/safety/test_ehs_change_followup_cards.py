"""EHS 变更周度督办 — 周五卡（逐项反馈版）与两个速递格子（纯结构验证）。

覆盖（DESIGN §4 改版 2026-11-24）：逐项「input+checkbox」表单、一个提交
按钮（无全局按钮/select）、input/checkbox name 携带 record_id、已反馈状态行
（✅ 填写 / ☑ 标记）、周五格（排除/未发送/提示桶）与周一格（三类+已关闭）。
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
# 周五卡（逐项反馈）
# ═══════════════════════════════════════════════════════════

class TestFridayCard:
    def test_initial_state_structure(self):
        card = cards.build_friday_card(_view(), "dp-1")
        assert card["schema"] == "2.0"
        assert card["header"]["title"]["content"] == "⏰ EHS变更周度督办 · 未验收 2 项"
        assert "第 48 周（11-27 周五）" in card["header"]["subtitle"]["content"]
        # 变更信息只在表单内出现一次（顶部不再有清单，2026-11-24 实机反馈）
        form = _form(card)
        blocks = [e for e in form["elements"] if e["tag"] == "markdown"]
        assert len(blocks) == 2                       # 每项一个信息块
        joined = "\n".join(e["content"] for e in blocks)
        assert "FX-D4-2026-0826" in joined and "FXD4-2026-0930" in joined
        assert "[审批详情](https://applink.feishu.cn/x)" in joined
        assert "状态未填" in joined
        assert "第 3 周督办" in joined
        # 顶部正文只有问候语（不含任何变更编号）
        top_md = _elements(card, "markdown")[0]["content"]
        assert "FX-D4-2026-0826" not in top_md and "FXD4-2026-0930" not in top_md
        # 每项：信息块 + input + checker
        inputs = [e for e in form["elements"] if e["tag"] == "input"]
        checks = [e for e in form["elements"] if e["tag"] == "checker"]
        buttons = [e for e in form["elements"] if e["tag"] == "button"]
        assert len(inputs) == 2 and len(checks) == 2 and len(buttons) == 1
        assert inputs[0]["name"] == "ecf_prog_recA1"
        assert "label" not in inputs[0]               # 编号已在上方信息块，不重复
        assert checks[0]["name"] == "ecf_unchk_recA1"
        assert "进展不变" in checks[0]["text"]["content"]
        assert buttons[0]["name"] == "ecf_submit_dp-1"
        assert buttons[0]["form_action_type"] == "submit"
        assert json.loads(buttons[0]["value"])["scope"] == cards.SCOPE
        # 无全局按钮（无 column_set）、无 select
        assert not _elements(card, "column_set")
        assert not [e for e in form["elements"] if e["tag"] == "select_static"]
        # 打开变更表链接
        assert any("打开变更表" in e["content"] for e in _elements(card, "markdown"))

    def test_replied_and_marked_state_lines(self):
        """已反馈回显：✅ 填写行 / ☑ 标记行；表单保留可继续提交。"""
        view = _view(items=(
            _item(replied_progress="已进料", replied_at_short="15:02"),
            _item(record_id="recA2", change_no="FXD4-2026-0930",
                  status_shown="", progress="", marked_unchanged=True,
                  marked_at_short="16:40"),
        ))
        card = cards.build_friday_card(view, "dp-2")
        form = _form(card)
        items_block = "\n".join(
            e["content"] for e in form["elements"] if e["tag"] == "markdown"
        )
        assert "✅ FX-D4-2026-0826：已进料（15:02）" in items_block
        assert "☑ FXD4-2026-0930：进展不变，无需更新（16:40）" in items_block
        # 表单保留（每项仍可继续填写/勾选）
        form = _form(card)
        assert len([e for e in form["elements"] if e["tag"] == "input"]) == 2

    def test_form_element_count_scales(self):
        """元素数 = 3×项数+1（13 项=40，远低于单卡 200 上限）。"""
        items = tuple(
            _item(record_id=f"rec{i}", change_no=f"FX-{i:04d}") for i in range(13)
        )
        card = cards.build_friday_card(_view(items=items), "dp-3")
        assert len(_form(card)["elements"]) == 40


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
