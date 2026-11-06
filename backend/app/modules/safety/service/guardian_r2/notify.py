"""R2 私信文案构建 —— 纯函数（执行器消费；单测锚定完成标准「提醒内容」）。

需求原文四要素：年度复审要求、换证要求、完成期限、逾期处理后果
（取消监护资格 + 停止发放监护人津贴）+ 第 N 次（共 3 次）标注。
"""

from __future__ import annotations

from typing import Any

_CERT_LABELS = {"guardian_a": "A证", "guardian_b": "B证"}


def _remaining_text(days: int | None) -> str:
    if days is None:
        return "—"
    if days < 0:
        return f"已逾期 {abs(days)} 天"
    return f"剩 {days} 天"


def build_remind_content(derived: dict[str, Any]) -> str:
    """复审/换证提醒私信正文（Markdown；四要素 + 第 N 次）。"""
    cert_label = _CERT_LABELS.get(str(derived.get("cert_category")), "")
    seq = derived.get("remind_seq") or 1
    node = derived.get("node_label") or "复审"
    deadline = derived.get("deadline") or "—"
    remaining = _remaining_text(derived.get("remaining_days"))
    is_renew = node == "换证"
    duty_line = (
        "本次为换证节点：请在截止日期前完成换证考核并合格，取证后进入新一轮复审周期"
        if is_renew else
        "本次为年度复审节点：须在截止日期前完成复审，考核合格后方可继续履行监护职责"
    )
    return (
        f"**监护人证件到期提醒 · 第 {seq} 次（共 3 次）**\n\n"
        f"- **姓名**：{derived.get('person_name', '—')}\n"
        f"- **证件类型**：监护人{cert_label}\n"
        f"- **当前节点**：{node}\n"
        f"- **完成期限**：{deadline}（{_remaining_text(derived.get('remaining_days'))}）\n\n"
        f"**复审要求**：年度复审须在当期截止日期前完成、考核合格后方可继续履行监护职责。\n"
        f"**换证要求**：三年期满须完成换证，换证考核合格后进入新一轮复审周期。\n"
        f"**当前待办**：{duty_line}\n\n"
        f"**逾期后果**：逾期未完成复审或考核不合格，将取消监护资格、"
        f"停止发放监护人津贴，不得继续承担特殊作业监护工作；完成复审并考核合格后，"
        f"经审核确认可恢复资格与津贴。\n\n"
        f"（本提醒每月一次，共 3 次；成绩以《理论考试分数表》录入为准。）"
    )


def build_score_event_content(
    person_name: str | None, cert_category: str | None, discriminated: str,
    passed: str | None, exam_date: str | None,
) -> str:
    """成绩映射结果私信（取证欢迎 / 复审通过 / 换证成功延期 / 考核不合格警示）。"""
    cert_label = _CERT_LABELS.get(str(cert_category), "")
    date_txt = exam_date or "—"
    if discriminated == "取证" and passed == "合格":
        return (
            f"**监护人取证成功**\n\n"
            f"- **姓名**：{person_name or '—'}\n"
            f"- **证件类型**：监护人{cert_label}\n"
            f"- **取证日期**：{date_txt}\n\n"
            f"您已进入持证人员名单；下一次复审节点将按取证日期 +1 年推算，"
            f"届时会提前三个月每月提醒。"
        )
    if discriminated == "换证" and passed == "合格":
        return (
            f"**监护人换证成功（已自动延期）**\n\n"
            f"- **姓名**：{person_name or '—'}\n"
            f"- **证件类型**：监护人{cert_label}\n"
            f"- **换证日期**：{date_txt}\n\n"
            f"已换证日期已回填，下一周期自动重算（第一次复审 = 换证日 +1 年）。"
        )
    if passed == "合格":
        return (
            f"**监护人复审通过**\n\n"
            f"- **姓名**：{person_name or '—'}\n"
            f"- **证件类型**：监护人{cert_label}\n"
            f"- **考核日期**：{date_txt}\n\n"
            f"本期复审已完成；下一节点到期前三个月会再次提醒。"
        )
    return (
        f"**监护人考核不合格警示**\n\n"
        f"- **姓名**：{person_name or '—'}\n"
        f"- **证件类型**：监护人{cert_label}\n"
        f"- **考核日期**：{date_txt}\n\n"
        f"本次考核（{discriminated}）不合格已登记。请尽快补考；逾期未通过将"
        f"取消监护资格并停止发放监护人津贴，补考合格经审核确认后可恢复。"
    )


def build_revoke_content(
    person_name: str | None, cert_category: str | None,
    reason: str, node_label: str | None, deadline: str | None,
) -> str:
    """取消资格私信（需求原文：原因+停津贴+不得监护+恢复路径）。"""
    cert_label = _CERT_LABELS.get(str(cert_category), "")
    node_txt = f"（{node_label}，截止 {deadline}）" if node_label else ""
    return (
        f"**监护人资格已取消**\n\n"
        f"- **姓名**：{person_name or '—'}\n"
        f"- **证件类型**：监护人{cert_label}\n"
        f"- **取消原因**：{reason}{node_txt}\n\n"
        f"依据监护人资格管理制度：即日起**取消监护资格、停止发放监护人津贴**，"
        f"不得继续承担特殊作业监护工作。\n\n"
        f"**恢复路径**：完成复审并考核合格后，经安全管理部门审核确认，"
        f"可恢复监护资格并按公司规定恢复津贴发放。"
    )


def build_revoke_admin_content(
    person_name: str | None, department: str | None, cert_category: str | None,
    reason: str, node_label: str | None, deadline: str | None,
    confirmed_by: str | None,
) -> str:
    """安管人员通知卡（promote 审核确认留痕）。"""
    cert_label = _CERT_LABELS.get(str(cert_category), "")
    node_txt = f"（{node_label}，截止 {deadline}）" if node_label else ""
    return (
        f"**监护人资格取消（已审核确认）**\n\n"
        f"- **姓名**：{person_name or '—'}（{department or '—'}）\n"
        f"- **证件类型**：监护人{cert_label}\n"
        f"- **取消原因**：{reason}{node_txt}\n"
        f"- **津贴联动**：当月起停发监护人津贴\n"
        f"- **审核确认**：{confirmed_by or '—'}\n\n"
        f"恢复须待本人复审合格并经再次审核确认（底座决策 promote 留痕）。"
    )


def build_restore_content(
    person_name: str | None, cert_category: str | None,
    exam_date: str | None, confirmed_by: str | None,
) -> str:
    """恢复资格私信（需求原文：复审合格+审核确认→恢复资格与津贴）。"""
    cert_label = _CERT_LABELS.get(str(cert_category), "")
    return (
        f"**监护人资格已恢复**\n\n"
        f"- **姓名**：{person_name or '—'}\n"
        f"- **证件类型**：监护人{cert_label}\n"
        f"- **合格考核日期**：{exam_date or '—'}\n"
        f"- **审核确认**：{confirmed_by or '—'}\n\n"
        f"资格已恢复，监护人津贴将按月恢复发放；下次节点到期前三个月会再次提醒。"
    )
