"""R1 字段映射 —— 报警 fields → 隐患主表 fields（§5.4 映射全量继承+实测字段名）。

断言来源独立于实现：期望值按 R1 设计 §5.4 映射表逐项核对（检查类别/
关联报警/整改状态显式值、+7d 期限、部门多选、person 字段留空、编号与
AI 列绝不预写——① 轮询单一分配点口径）。
"""

from __future__ import annotations

from app.modules.safety.service.alarm_hazard_r1.field_map import (
    DEADLINE_DAYS,
    build_hazard_fields,
)

_FIELDS = {
    "报警时间": 1793630412844,  # 2026-11-03 前后（epoch ms）
    "报警类型": "火灾报警",
    "报警部门负责人.部门": ["提炼工程一部"],
    "报警楼栋": "提三",
    "报警部位": [{"type": "text", "text": "1楼洁净区干燥间15号感烟"}],
    "报警性质": "泄漏报警",
    "报警原因分类": "氨水引发",
    "具体报警原因": [{"type": "text", "text": "接浓氨操作挥发报警"}],
    "处理情况": [{"type": "text", "text": "已通知仪表"}],
}


def test_full_mapping() -> None:
    out = build_hazard_fields(_FIELDS, "recABC")
    assert out["检查日期"] == 1793630412844
    assert out["检查类别"] == ["报警联动"]
    assert out["整改状态"] == "未关闭"
    assert out["关联报警"] == "fire_alarm:recABC"
    # 期限 = 报警时间 + 7d（ms）
    assert out["整改期限"] == 1793630412844 + DEADLINE_DAYS * 86400 * 1000
    # 部门多选原样（person 字段一律留空——业务方在表里指派）
    assert out["整改责任人.部门"] == ["提炼工程一部"]
    # 描述模板：部门·楼栋部位·类型·性质：原因（富文本扁平化）
    assert out["隐患描述"] == (
        "【消防报警联动】提炼工程一部·提三"
        "1楼洁净区干燥间15号感烟·火灾报警·性质:泄漏报警：接浓氨操作挥发报警"
    )


def test_multi_department_joined() -> None:
    out = build_hazard_fields(
        {**_FIELDS, "报警部门负责人.部门": ["提炼工程一部", "四部"]}, "recX",
    )
    assert out["整改责任人.部门"] == ["提炼工程一部", "四部"]
    assert out["隐患描述"].startswith("【消防报警联动】提炼工程一部、四部·")


def test_missing_optional_fields_degrade() -> None:
    """部门/部位/原因缺失时描述降级不断链；日期缺失不写检查日期。"""
    out = build_hazard_fields({"报警性质": "故障报警"}, "recY")
    assert out["关联报警"] == "fire_alarm:recY"
    assert out["整改状态"] == "未关闭"
    assert "整改责任人.部门" not in out
    assert "检查日期" not in out
    assert "整改期限" not in out
    assert "【消防报警联动】" in out["隐患描述"]


def test_forbidden_fields_never_written() -> None:
    """编号/AI 列/督办等级/person/图片/复核列/目前进展 绝不出现。"""
    out = build_hazard_fields(_FIELDS, "recZ")
    for key in (
        "隐患编号", "隐患分类（AI）", "隐患类别（AI）", "隐患级别",
        "隐患描述（AI）", "隐患判定依据（AI）", "整改建议（AI）", "督办等级",
        "检查人员", "整改责任人", "缺陷图片", "整改后图片", "目前进展",
        "部门负责人复核", "分管领导复核", "检查人员复核",
    ):
        assert key not in out, key
