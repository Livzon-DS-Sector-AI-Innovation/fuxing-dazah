"""部门责任人覆盖映射表（专门的映射表）。

将某些部门的隐患责任人统一归口到一人（如 QC 部门统一为陈雅芬），
用于督办通报、催办卡、通知等所有责任人呈现/通知点。
以「部门」为键，命中即覆盖隐患记录中的个人责任人，不修改底层数据。

新增映射：在此追加 {部门名: 责任人姓名}，全模块各呈现点自动生效。
部门名使用 identity.departments 标准名（平台隐患 department 已归一化对齐）。
"""
from __future__ import annotations

# 部门 → 责任人姓名（命中部门即用此人，与记录中的个人责任人无关）
DEPARTMENT_RESPONSIBLE_OVERRIDE: dict[str, str] = {
    "质量控制部（QC部）": "陈雅芬",
}


def effective_responsible_person(department: str | None, original_name: str | None) -> str:
    """返回有效责任人姓名。

    - 部门命中映射表 → 返回覆盖人（陈雅芳等）
    - 未命中 → 返回原责任人
    - 两者皆空 → 返回空串（调用方自行兜底 '-'）

    Args:
        department: 责任部门（标准名，如 "质量控制部（QC部）"）
        original_name: 隐患记录中的个人责任人姓名
    """
    if department:
        override = DEPARTMENT_RESPONSIBLE_OVERRIDE.get(department)
        if override:
            return override
    return original_name or ""
