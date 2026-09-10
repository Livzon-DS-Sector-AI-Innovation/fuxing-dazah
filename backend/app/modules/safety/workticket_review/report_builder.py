"""作业票审核报告构建器（WorkTicketReviewReportBuilder）——固定模板 Markdown。

输出四板块：
  ① 审核概要（日期/今日票数/类型分布/已审/违规/合格/数据不足）
  ② 违规明细（真实违规 + 数据不足/待跟进，按票逐条）
  ③ 合格摘要（全部规则通过/不适用的票）
  ④ 措施建议（按规则固化中文文案，非 AI 生成）

规则引擎把「缺失时间」记作 not_applicable=False 且 detail 以“数据不足：”开头，
本构建器将其归入「数据不足/待跟进」，不混入「违规」；not_applicable=True 一律不列为违规。
"""

from __future__ import annotations

from datetime import date as date_cls
from typing import Any

from app.modules.safety.workticket_review.parser import WorkTicket
from app.modules.safety.workticket_review.rule_engine import RuleNo, Violation

# 8 类标准作业票英文枚举 → 中文名称
TICKET_TYPE_NAMES: dict[str, str] = {
    "hot_work": "动火作业",
    "confined_space": "受限空间作业",
    "height_work": "高处作业",
    "lifting": "吊装作业",
    "temporary_electricity": "临时用电作业",
    "excavation": "动土作业",
    "road_breaking": "断路作业",
    "blind_plate": "盲板抽堵作业",
}

# 英文内部字段名 → 中文展示
_FIELD_CN: dict[str, str] = {
    "start_time": "开始时间",
    "end_time": "结束时间",
    "finish_time": "完工验收时间",
    "apply_time": "申请时间",
    "approve_time": "审批时间",
    "gas_analysis": "气体分析",
    "work_site": "作业地点",
    "work_content": "作业内容",
}


def _cn_detail(text: str) -> str:
    """把 violation.detail 中的英文字段名替换为中文（如 start_time→开始时间）。"""
    for eng, cn in _FIELD_CN.items():
        text = text.replace(eng, cn)
    return text

# 规则编号 → 固化中文建议（按 Issue 05 / spec 5 小节文案）
MEASURE_ADVICE: dict[str, str] = {
    RuleNo.TIME_ORDER: "规范票面各时间节点顺序，避免倒签/补签（申请≤气体分析≤审批≤开始<结束≤验收）。",
    RuleNo.GAS_VALIDITY: "作业开始前 30 分钟内完成气体复测，确保最近一次分析时间距开始不超过 30 分钟。",
    RuleNo.DURATION: "作业时长超限，严格按 GB30871 时限安排/办延期。",
    RuleNo.GAS_INTERVAL: "受限空间每 2h 记录气体，动火午后须补测（覆盖 12:00 后）。",
    RuleNo.PERSONNEL_CERT: "涉及焊接切割类动火须由持证特种作业人员实施，无证人员立即撤场并补办人员登记。",
}


def _ticket_type_name(ticket_type: str) -> str:
    return TICKET_TYPE_NAMES.get(ticket_type, ticket_type)


def _is_data_insufficient(violation: Violation) -> bool:
    """判断 Violation 是否属于「数据不足/待跟进」而非真实违规。

    规则引擎对缺失时间统一用 not_applicable=False 且 detail 以“数据不足：”开头标记。
    """
    return (
        not violation.not_applicable
        and violation.detail.strip().startswith("数据不足")
    )


def _fmt_key_times(key_times: list[str] | None) -> list[str]:
    return list(key_times or [])


def _fmt_site_content(ticket: WorkTicket) -> str:
    """拼装票的「部门 / 作业地点 / 作业内容」行；三者均空时返回空串。

    部门取申请单位（apply_unit 的 $ 显示值，如「提炼工程一部」）。
    """
    parts: list[str] = []
    if ticket.apply_unit:
        parts.append(f"部门：{ticket.apply_unit}")
    if ticket.work_site:
        parts.append(f"地点：{ticket.work_site}")
    if ticket.work_content:
        parts.append(f"内容：{ticket.work_content}")
    return " ｜ ".join(parts)


class WorkTicketReviewReportBuilder:
    """按固定模板生成作业票审核日报 Markdown。"""

    def build(
        self,
        review_date: date_cls | str,
        tickets: list[WorkTicket],
        violations_by_ticket: dict[str, list[Violation]],
        stats: dict[str, Any],
    ) -> str:
        """生成固定模板 Markdown 报告。

        review_date：审核日（date 或 'YYYY-MM-DD'）。
        tickets：当日全部规整化 WorkTicket。
        violations_by_ticket：ticket_no -> list[Violation]（可为空 dict）。
        stats：审核摘要，至少含 total/reviewed/violation_count/compliant_count/
               data_insufficient；其余如 pushed 用于展示。
        """
        date_text = self._format_date(review_date)

        # ── 按票分类 ──
        real_map: dict[str, tuple[WorkTicket, list[Violation]]] = {}
        insufficient_map: dict[str, tuple[WorkTicket, list[Violation]]] = {}
        compliant: list[WorkTicket] = []

        for ticket in tickets:
            ticket_no = ticket.ticket_no or ticket.process_instance_id or ""
            violations = self._violations_for(ticket_no, violations_by_ticket)
            real_violations = [
                v
                for v in violations
                if not v.not_applicable and not _is_data_insufficient(v)
            ]
            insufficient = [
                v for v in violations if not v.not_applicable and _is_data_insufficient(v)
            ]
            if real_violations:
                real_map[ticket_no] = (ticket, real_violations)
            if insufficient:
                insufficient_map[ticket_no] = (ticket, insufficient)
            if not real_violations and not insufficient:
                compliant.append(ticket)

        sections: list[str] = []
        sections.append(self._render_title(date_text))
        sections.append(
            self._render_overview(
                date_text=date_text,
                stats=stats,
                tickets=tickets,
                real_map=real_map,
                insufficient_map=insufficient_map,
            )
        )
        sections.append(self._render_violations(real_map, insufficient_map))
        sections.append(self._render_compliant(compliant))
        return "\n\n".join(part for part in sections if part).strip() + "\n"

    # ── 工具方法 ──
    @staticmethod
    def _format_date(value: date_cls | str) -> str:
        if isinstance(value, date_cls):
            return value.isoformat()
        return str(value).strip()

    @staticmethod
    def _violations_for(
        ticket_no: str,
        violations_by_ticket: dict[str, list[Violation]],
    ) -> list[Violation]:
        if ticket_no in violations_by_ticket:
            return list(violations_by_ticket.get(ticket_no) or [])
        return []

    @staticmethod
    def _type_distribution(tickets: list[WorkTicket]) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for ticket in tickets:
            counts[ticket.ticket_type] = counts.get(ticket.ticket_type, 0) + 1
        return sorted(counts.items())

    # ── 板块渲染 ──
    def _render_title(self, date_text: str) -> str:
        return f"📋 【作业票审核日报】 {date_text}"

    def _render_overview(
        self,
        date_text: str,
        stats: dict[str, Any],
        tickets: list[WorkTicket],
        real_map: dict[str, tuple[WorkTicket, list[Violation]]],
        insufficient_map: dict[str, tuple[WorkTicket, list[Violation]]],
    ) -> str:
        total = stats.get("total", len(tickets))
        reviewed = stats.get("reviewed", self._count_reviewed(tickets))
        violation_count = stats.get("violation_count", len(real_map))
        compliant_count = stats.get(
            "compliant_count",
            len(self._all_compliant(tickets, real_map, insufficient_map)),
        )
        data_insufficient = stats.get("data_insufficient", len(insufficient_map))
        lines = [
            "📊 审核概要",
            "━━━━━━━━━━━━━━━━━━━━",
            f"• 审核日期: {date_text}",
            f"• 今日标准 8 类作业票数: {total} 项",
            f"• 已审数（已具备开始时间）: {reviewed} 项",
            f"• 违规票数: {violation_count} 项 | 合格票数: {compliant_count} 项 | 数据不足票数: {data_insufficient} 项",
        ]

        distribution = self._type_distribution(tickets)
        if distribution:
            lines.append("")
            lines.append("📌 类型分布")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            for ticket_type, count in distribution:
                lines.append(f"• {_ticket_type_name(ticket_type)}: {count} 项")
        return "\n".join(lines)

    @staticmethod
    def _count_reviewed(tickets: list[WorkTicket]) -> int:
        return sum(1 for t in tickets if t.start_time is not None)

    @staticmethod
    def _all_compliant(
        tickets: list[WorkTicket],
        real_map: dict[str, tuple[WorkTicket, list[Violation]]],
        insufficient_map: dict[str, tuple[WorkTicket, list[Violation]]],
    ) -> list[WorkTicket]:
        return [
            t
            for t in tickets
            if (t.ticket_no or t.process_instance_id or "") not in real_map
            and (t.ticket_no or t.process_instance_id or "") not in insufficient_map
        ]

    def _render_violations(
        self,
        real_map: dict[str, tuple[WorkTicket, list[Violation]]],
        insufficient_map: dict[str, tuple[WorkTicket, list[Violation]]],
    ) -> str:
        # 每张票内部用 \n 紧凑（票号/地点/违规/key_times 软换行连排），
        # 票与票之间用 \n\n 分段，飞书渲染时空行分隔不同票。
        blocks: list[str] = ["🔴 真实违规\n━━━━━━━━━━━━━━━━━━━━"]
        if not real_map:
            blocks.append("（无）")
        else:
            idx = 0
            for ticket, violations in real_map.values():
                idx += 1
                lines: list[str] = [
                    f"{idx}. 【{_ticket_type_name(ticket.ticket_type)}】"
                    f"{ticket.ticket_no or ticket.process_instance_id or '（无票号）'}"
                ]
                site_content = _fmt_site_content(ticket)
                if site_content:
                    lines.append(f"📍 {site_content}")
                for v in violations:
                    lines.append(f"🕒 {v.rule_name}: {_cn_detail(v.detail)}")
                    for kt in _fmt_key_times(v.key_times):
                        lines.append(f"  · {kt}")
                blocks.append("\n".join(lines))

        blocks.append("🟡 数据不足 / 待跟进\n━━━━━━━━━━━━━━━━━━━━")
        if not insufficient_map:
            blocks.append("（无）")
        else:
            idx = 0
            for ticket, violations in insufficient_map.values():
                idx += 1
                lines = [
                    f"{idx}. 【{_ticket_type_name(ticket.ticket_type)}】"
                    f"{ticket.ticket_no or ticket.process_instance_id or '（无票号）'}"
                ]
                site_content = _fmt_site_content(ticket)
                if site_content:
                    lines.append(f"📍 {site_content}")
                for v in violations:
                    lines.append(f"❓ {_cn_detail(v.detail)}")
                blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    def _render_compliant(self, compliant: list[WorkTicket]) -> str:
        lines = ["🟢 合格摘要", "━━━━━━━━━━━━━━━━━━━━"]
        if not compliant:
            lines.append("（无）")
        else:
            lines.append(f"以下作业票全部规则通过（含规则不适用），共 {len(compliant)} 项：")
            lines.append("")
            for ticket in compliant:
                lines.append(
                    f"• {ticket.ticket_no or ticket.process_instance_id or '（无票号）'}（{_ticket_type_name(ticket.ticket_type)}）未发现违规"
                )
        return "\n".join(lines)

    def _render_measures(
        self,
        real_map: dict[str, tuple[WorkTicket, list[Violation]]],
        insufficient_map: dict[str, tuple[WorkTicket, list[Violation]]],
    ) -> str:
        lines = ["📌 措施建议", "━━━━━━━━━━━━━━━━━━━━"]
        rule_names = {
            RuleNo.TIME_ORDER: "时间顺序链",
            RuleNo.GAS_VALIDITY: "作业前气体分析时限",
            RuleNo.DURATION: "作业时长上限",
            RuleNo.GAS_INTERVAL: "气体分析间隔/午后覆盖",
            RuleNo.PERSONNEL_CERT: "人员证件判定",
        }
        lines.append("")
        lines.append("按规则整改建议：")
        for rule_no in RuleNo:
            advice = MEASURE_ADVICE.get(rule_no)
            rule_name = rule_names.get(rule_no, rule_no)
            lines.append(f"【{rule_name}】{advice or ''}")

        if insufficient_map:
            lines.append("")
            lines.append("数据不足待跟进：")
            lines.append(
                "补齐对应时间/气体分析记录（申请、审批、开始、结束、验收、气体分析时间），再纳入规则审核。"
            )
        return "\n".join(lines)

__all__ = [
    "TICKET_TYPE_NAMES",
    "MEASURE_ADVICE",
    "WorkTicketReviewReportBuilder",
]
