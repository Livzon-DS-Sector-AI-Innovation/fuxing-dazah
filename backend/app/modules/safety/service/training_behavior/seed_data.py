"""S6 教育培训与行为管控——建表 schema 与三违回填行构造（一期 R1 底座）。

数据事实源=docs/DESIGN-安全模块3.0四期-四新域表结构与页面口径-20261014.md
§3（蓝本 15+12 列）+ AI 参与式设计微增列（培训：学时/课件试卷/关联违章编号；
违章：证据附件/AI 判级建议）。列名是 domain_pages._analyze_training 与 D3
取数器的直读契约，禁止改名。播种脚本 scripts/seed_training_behavior.py 消费本模块。
"""

from __future__ import annotations

from typing import Any

from app.modules.safety.service.bitable_direct import fields as bd_fields

DOMAIN = "training_behavior"
KIND_TRAINING = "training"
KIND_VIOLATION = "violation"
TABLE_TRAINING = "培训计划与实施表"
TABLE_VIOLATION = "违章行为档案表"

_TRAINING_CATEGORIES = ("入厂三级教育", "年度复训", "专项培训", "转岗培训", "外来人员培训")
_TRAINING_FORMS = ("线下", "线上", "实操")
_ASSESSMENTS = ("考试", "签到", "实操评估", "无需考核")
_TRAINING_STATUSES = ("未开始", "进行中", "已完成", "已取消")
_VIOLATION_CATEGORIES = ("操作违章", "指挥违章", "防护缺失", "纪律违章")
_VIOLATION_LEVELS = ("一般", "严重", "重大")
_HANDLINGS = ("批评教育", "罚款", "停工培训", "待岗")
_VIOLATION_STATUSES = ("纠正中", "已纠正")

# 隐患表回流的读取列（hazard 直读中文列名，与 hazard_direct/bitable_repo 同源）
HAZARD_NO = "隐患编号"
HAZARD_CATEGORY_AI = "隐患类别（AI）"
HAZARD_DESC_AI = "隐患描述（AI）"
HAZARD_DESC = "隐患描述"
HAZARD_DATE = "检查日期"
VIOLATION_OPERATION = "三违作业"


def _field(name: str, ftype: int, options: tuple[str, ...] | None = None) -> dict[str, Any]:
    field: dict[str, Any] = {"field_name": name, "type": ftype}
    if options is not None:
        field["property"] = {"options": [{"name": o} for o in options]}
    return field


def table_schema_training() -> dict[str, Any]:
    """培训计划与实施表建表请求体（蓝本 §3.2 + 微增 3 列）。"""
    return {
        "table": {
            "name": TABLE_TRAINING,
            "default_view_name": "全部培训",
            "fields": [
                _field("培训名称", 1),
                _field("培训类别", 3, _TRAINING_CATEGORIES),
                _field("计划日期", 5),
                _field("实施日期", 5),
                _field("培训形式", 3, _TRAINING_FORMS),
                _field("组织部门", 4),
                _field("讲师", 11),
                _field("应到人数", 1),
                _field("实到人数", 1),
                _field("签到表", 17),
                _field("考核方式", 3, _ASSESSMENTS),
                _field("考核合格人数", 1),
                _field("状态", 3, _TRAINING_STATUSES),
                _field("下次复训日期", 5),
                _field("备注", 1),
                _field("培训学时", 2),
                _field("课件与试卷", 17),
                _field("关联违章编号", 1),
            ],
        }
    }


def table_schema_violation() -> dict[str, Any]:
    """违章行为档案表建表请求体（蓝本 §3.3 + 微增 2 列）。"""
    return {
        "table": {
            "name": TABLE_VIOLATION,
            "default_view_name": "全部违章",
            "fields": [
                _field("违章日期", 5),
                _field("违章人员", 11),
                _field("所属单位", 4),
                _field("违章类别", 3, _VIOLATION_CATEGORIES),
                _field("违章等级", 3, _VIOLATION_LEVELS),
                _field("违章描述", 1),
                _field("处理方式", 3, _HANDLINGS),
                _field("纠正措施", 1),
                _field("状态", 3, _VIOLATION_STATUSES),
                _field("关联隐患编号", 1),
                _field("定向培训", 1),
                _field("备注", 1),
                _field("证据附件", 17),
                _field("AI判级建议", 1),
            ],
        }
    }


def violation_row_from_hazard(fields: dict[str, Any]) -> dict[str, Any]:
    """隐患行 fields → 违章档案初始行 fields（违章人/类别/等级留待人工补录）。"""
    row: dict[str, Any] = {
        "状态": "纠正中",
        "关联隐患编号": bd_fields.text(fields, HAZARD_NO) or "",
        "违章描述": (
            bd_fields.text(fields, HAZARD_DESC_AI)
            or bd_fields.text(fields, HAZARD_DESC)
            or ""
        ),
        "备注": "隐患表三违回流生成，违章人与定性待补录",
    }
    if bd_fields.datetime_ms(fields, HAZARD_DATE) is not None:
        row["违章日期"] = bd_fields.to_millis(fields.get(HAZARD_DATE))
    return row


def plan_backfill(
    hazard_records: list[dict[str, Any]], existing_nos: set[str]
) -> list[dict[str, Any]]:
    """回填/回流计划：筛三违作业行，按关联隐患编号去重（含批内与存量）。"""
    seen: set[str] = set(existing_nos)
    plan: list[dict[str, Any]] = []
    for record in hazard_records:
        fields = record.get("fields") or {}
        if bd_fields.select(fields, HAZARD_CATEGORY_AI) != VIOLATION_OPERATION:
            continue
        no = bd_fields.text(fields, HAZARD_NO) or ""
        if not no or no in seen:
            continue
        seen.add(no)
        plan.append(violation_row_from_hazard(fields))
    return plan
