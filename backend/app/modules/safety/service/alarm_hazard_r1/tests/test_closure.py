"""R1 闭环分类器 —— 处理情况文本 → 五值闭环分类（§1.2 修订版口径）。

样本取自 R1 设计 §1.2 盘点真实描述：
- E 已恢复/已闭环（89.1%）→ closed
- B 屏蔽未记录恢复 → closed（2026-10-20 用户拍板：屏蔽按闭环，不计未闭环）
- C 移交处理无结果 → pending_handover
- D 明示待办 → explicit_todo
- A 处理情况为空 → empty
- F 其他描述 → other（不算未闭环）
形近字（「烣复系统」）与富文本输入是修订版复盘点名的实现要求。
"""

from __future__ import annotations

from app.modules.safety.service.alarm_hazard_r1.closure import classify_closure


def _rich(text: str) -> list[dict]:
    """Bitable 富文本形态。"""
    return [{"type": "text", "text": text}]


# ═══════════════════════════════════════════════════════════════
# E 类 + B 类（拍板口径）+ F 类闭环词 → closed
# ═══════════════════════════════════════════════════════════════


def test_closed_recovery_words() -> None:
    """恢复/复位/正常/已更换/无异常/已报备 → closed。"""
    for text in (
        "现场查看通知岗位人员注意操作后，22:50恢复系统。",
        "压料已恢复",
        "现场复位",
        "已更换探头",
        "无异常",
        "已报备",
    ):
        assert classify_closure(text) == "closed", text


def test_closed_shielding_counts_closed() -> None:
    """屏蔽按闭环（用户拍板），含「无此点位已屏蔽」配置问题形态。"""
    assert classify_closure("暂时屏蔽") == "closed"
    assert classify_closure("无此点位已屏蔽") == "closed"
    assert classify_closure("申请飞书屏蔽") == "closed"


def test_closed_misc_closed_words() -> None:
    """误报 / 点位已拆除（F 类多数实为闭环的列举项）。"""
    assert classify_closure("误报") == "closed"
    assert classify_closure("点位已拆除") == "closed"


def test_closed_typo_recovery() -> None:
    """形近字规范化：『烣复系统』错别字（修订版复盘点名的假阳性根因）。"""
    assert classify_closure("22:50烣复系统") == "closed"


def test_recovery_wins_over_notice() -> None:
    """恢复词优先于通知词：通知+恢复并存 → closed。"""
    assert classify_closure("已通知仪表更换探头，22:50恢复系统") == "closed"


# ═══════════════════════════════════════════════════════════════
# D 类 → explicit_todo
# ═══════════════════════════════════════════════════════════════


def test_explicit_todo_words() -> None:
    """明示待办：待…更换/维修/处理/校准、未处理、跟进处理、采购中。"""
    for text in (
        "待仪表更换",
        "待白班仪表维修",
        "降温失效待处理",
        "未处理",
        "跟进处理",
        "仪表采购中",
    ):
        assert classify_closure(text) == "explicit_todo", text


def test_todo_without_recovery_beats_handover() -> None:
    """待办词优先于移交词：已通知但明示待办 → explicit_todo。"""
    assert classify_closure("已通知仪表，待更换探头") == "explicit_todo"


# ═══════════════════════════════════════════════════════════════
# C 类 → pending_handover
# ═══════════════════════════════════════════════════════════════


def test_pending_handover_words() -> None:
    """移交无回执：已通知仪表/安全员/维保、移交，且无恢复/待办词。"""
    for text in (
        "已通知仪表",
        "已通知仪表处理",
        "已通知安全员查看",
        "已通知维保处理",
        "移交仪表处理",
    ):
        assert classify_closure(text) == "pending_handover", text


# ═══════════════════════════════════════════════════════════════
# A 类 / F 类
# ═══════════════════════════════════════════════════════════════


def test_empty_inputs() -> None:
    """空值（None/空串/空列表/纯空白/空富文本）→ empty。"""
    assert classify_closure(None) == "empty"
    assert classify_closure("") == "empty"
    assert classify_closure([]) == "empty"
    assert classify_closure("   ") == "empty"
    assert classify_closure([{"type": "text", "text": ""}]) == "empty"


def test_other_descriptions() -> None:
    """F 类模糊收尾不算未闭环：电话询问 / 通知现场处置（无「已通知」）。"""
    assert classify_closure("电话询问") == "other"
    assert classify_closure("通知现场处置") == "other"


# ═══════════════════════════════════════════════════════════════
# 输入形态
# ═══════════════════════════════════════════════════════════════


def test_rich_text_input() -> None:
    """Bitable 富文本 list 输入与纯文本同判。"""
    assert classify_closure(_rich("22:50恢复系统。")) == "closed"
    assert classify_closure(_rich("待仪表更换")) == "explicit_todo"


def test_fullwidth_and_whitespace_normalization() -> None:
    """全角标点/空白不影响命中。"""
    assert classify_closure("２２:５0恢复系统") == "closed"
    assert classify_closure("  已通知仪表  ") == "pending_handover"
