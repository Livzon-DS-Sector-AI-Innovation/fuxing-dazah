"""R2 成绩写回字段构建 —— 纯函数（执行器消费；黄色操作=真实 Bitable 写入）。

日期毫秒=UTC 零点（与 scan_source._ms_to_date 读回口径对称，往返稳定）。
取证分支 create_record 进名单（需求原文：成绩合格→名字自动出现在持证
人员名单）；换证分支写「已换证日期」=考核日期（成功延期换证）。
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.modules.safety.service.guardian_r2.score_parse import ScoreFacts


def date_to_ms(d: date) -> int:
    """date → UTC 零点毫秒（Bitable 日期列写入格式）。"""
    return int(
        datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000
    )


def build_writeback_fields(facts: ScoreFacts, *, discriminated: str) -> dict:
    """复审/换证/不合格通用写回：考核三列；换证额外写已换证日期。"""
    fields: dict = {
        "考核成绩": facts.passed or "",
        "考核日期": date_to_ms(facts.exam_date) if facts.exam_date else None,
        "考核类型": discriminated,
    }
    if discriminated == "换证" and facts.passed == "合格" and facts.exam_date:
        fields["已换证日期"] = date_to_ms(facts.exam_date)
    return {k: v for k, v in fields.items() if v is not None}


def build_enroll_fields(facts: ScoreFacts) -> dict:
    """取证进名单 create_record 字段（人员字段用 open_id 直写）。"""
    from app.modules.safety.service.guardian_r2.node_engine import derive_nodes

    assert facts.exam_date is not None, "取证写回须有考核日期"
    issue = facts.exam_date
    nodes = derive_nodes(issue)  # 周期 1/2/3 年单一定义点（node_engine）
    return {
        "姓名": [{"id": facts.open_id}] if facts.open_id else facts.person_name,
        "部门": facts.department or "",
        "取证日期": date_to_ms(issue),
        "第一次复审截止日期": date_to_ms(nodes["first_review"]),
        "第二次复审截止日期": date_to_ms(nodes["second_review"]),
        "应换证日期": date_to_ms(nodes["renew"]),
        "考核成绩": facts.passed or "合格",
        "考核日期": date_to_ms(issue),
        "考核类型": "取证",
    }
