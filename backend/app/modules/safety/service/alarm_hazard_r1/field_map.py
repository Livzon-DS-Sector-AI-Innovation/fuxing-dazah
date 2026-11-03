"""R1 字段映射 —— 消防报警 fields → 隐患登记闭环主表 fields（纯函数）。

§5.4 映射表全量继承（P3/P5 拍板口径）+ 实测字段名修正：
- 显式写 整改状态=未关闭（空值不匹配 ③ 督办 COND_OPEN 的坑）
- 检查类别=报警联动（multi_select 写新值自动建选项，零结构风险）
- 关联报警=fire_alarm:<record_id>（文本列由执行器写前幂等 ensure）
- 整改期限=报警时间+7d（P5；Bitable datetime 写 timestamp ms 惯例）
- person 字段（检查人员/整改责任人）一律留空，业务方在表里指派
- 编号/AI 列/督办等级绝不预写（① HazardNoAllocator 单一分配点口径）
"""

from __future__ import annotations

from typing import Any

from app.modules.safety.service.alarm_hazard_r1.closure import plain_text

#: P5：整改期限预填天数
DEADLINE_DAYS = 7

_DAY_MS = 86400 * 1000


def _dept_joined(fields: dict[str, Any]) -> str:
    """部门多选 → 描述用顿号连接文本。"""
    depts = fields.get("报警部门负责人.部门")
    if isinstance(depts, list) and depts:
        return "、".join(str(d) for d in depts)
    return ""


def build_hazard_fields(
    fields: dict[str, Any], record_id: str, *, deadline_days: int = DEADLINE_DAYS,
) -> dict[str, Any]:
    """报警原文 fields → 隐患表 fields dict（只含要写的键；缺失字段降级跳过）。"""
    out: dict[str, Any] = {
        "检查类别": ["报警联动"],
        "整改状态": "未关闭",
        "关联报警": f"fire_alarm:{record_id}",
    }

    alarm_ms = fields.get("报警时间")
    if isinstance(alarm_ms, (int, float)):
        out["检查日期"] = int(alarm_ms)
        out["整改期限"] = int(alarm_ms) + deadline_days * _DAY_MS

    depts = fields.get("报警部门负责人.部门")
    if isinstance(depts, list) and depts:
        out["整改责任人.部门"] = list(depts)

    parts = [
        x for x in (
            _dept_joined(fields),
            "".join(filter(None, (
                plain_text(fields.get("报警楼栋")) or "",
                plain_text(fields.get("报警部位")) or "",
            ))),
            plain_text(fields.get("报警类型")) or "",
            f"性质:{plain_text(fields.get('报警性质'))}" if fields.get("报警性质") else "",
        ) if x
    ]
    cause = plain_text(fields.get("具体报警原因")) or ""
    desc = "【消防报警联动】" + "·".join(parts)
    if cause:
        desc += f"：{cause}"
    out["隐患描述"] = desc
    return out
