"""ehs_change 直读视图对象单测（Ticket 01）——映射复用/形态/跳行。

fixture 用 search 实测形态（survey_ehs_change 2026-09-24）：Url dict /
人员 list<dict> / 单选 str / 多选 list<str> / 富文本 list<dict> / 日期毫秒
int / AI 结论 str / AI 报告富文本。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.modules.safety.service.ehs_change_direct.views import view_from_record


def _approval_fields(**override: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "申请状态": "已通过",
        "变更发起人": [{"name": "赵军元", "en_name": "", "open_id": "ou_x"}],
        "当前处理人": [],
        "申请编号": {"text": "202504070383", "link": "https://applink.feishu.cn/x"},
        "变更申请编号": [{"text": "FXQC-2025-06", "type": "text"}],
        "变更名称": [{"text": "精制车间搬迁", "type": "text"}],
        "变更分类": ["设备设施变更", "管理变更"],
        "变更级别": "重大",
        "变更时效": ["永久性变更"],
        "变更申请部门": ["精制工程一部"],
        "申请变更原因": [{"text": "现车间产能不足", "type": "text"}],
        "预计效果": [{"text": "产能提升 20%", "type": "text"}],
        "预计实施日期": 1764691200000,
        "需更新的文件资料": [{"text": "工艺规程", "type": "text"}],
        "变更计划内容": [{"text": "分三阶段实施", "type": "text"}],
        "变更风险评估及建议措施": [{"text": "落实置换隔离", "type": "text"}],
        "是否可以体现": "是",
        "GMP变更编号": [],
        "审批节点": [],
        "SourceID": [],
        "申请变更原因-AI审核结论": "需补充完善",
        "申请变更原因-AI审核报告": [
            {"text": "变更原因描述过于笼统", "type": "text"},
        ],
        "变更计划内容-AI审核结论": "",
        "AI预审意见": [
            {"text": "建议补充材料后重新提交", "type": "text"},
        ],
    }
    fields.update(override)
    return fields


def _acceptance_fields(**override: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "申请状态": "审批中",
        "发起人": [{"name": "李四", "open_id": "ou_y"}],
        "当前处理人": [],
        "申请编号": {"text": "", "link": "https://applink.feishu.cn/y"},
        "变更编号": [{"text": "FXYS-2025-11", "type": "text"}],
        "变更名称": [{"text": "精制车间搬迁验收", "type": "text"}],
        "变更级别": "一般变更",
        "发起人部门": [{"text": "精制工程一部", "type": "text"}],
        "验收意见（可另附验收报告）": [{"text": "验收通过", "type": "text"}],
        "审批流程": "EHS变更验收申请",
        "审批节点": [],
        "关联审批": [{"text": "202504070383-赵军元-EHS变更申请", "type": "text"}],
        "SourceID": [],
        "验收日期": 1752508800000,
    }
    fields.update(override)
    return fields


class TestApprovalMapping:
    def test_full_mapping(self) -> None:
        v = view_from_record(
            "approval", "recA1", _approval_fields(), created_time_ms=1776300000000,
        )
        assert v is not None
        assert v.record_id == "recA1"
        assert v.kind == "approval"
        assert v.created_time_ms == 1776300000000
        assert v.change_no == "202504070383"  # Url text 优先
        assert v.title == "精制车间搬迁"
        assert v.change_type == "equipment_facility"  # 多选取首 + 枚举映射
        assert v.change_grade == "major"
        assert v.department == "精制工程一部"
        assert v.status == "approved"
        assert v.description == "现车间产能不足"
        assert v.expected_start == datetime.fromtimestamp(
            1764691200, tz=UTC,
        )
        assert v.applicant_name == "赵军元"
        assert v.ai_review_status == "completed"  # AI 结论非空 → completed
        # 恒 None 字段（镜像映射同款）
        assert v.location_unit is None
        assert v.expected_completion is None
        assert v.actual_start is None
        assert v.actual_completion is None

    def test_change_no_fallback_to_rich_text(self) -> None:
        v = view_from_record(
            "approval", "recA2", _approval_fields(申请编号={"text": "", "link": ""}),
        )
        assert v is not None
        assert v.change_no == "FXQC-2025-06"

    def test_no_ai_columns_gives_none(self) -> None:
        v = view_from_record(
            "approval", "recA3",
            _approval_fields(**{
                "申请变更原因-AI审核结论": "",
                "申请变更原因-AI审核报告": [],
                "AI预审意见": [],
            }),
        )
        assert v is not None
        assert v.ai_review_status == "none"

    def test_deleted_status_returns_none(self) -> None:
        assert view_from_record(
            "approval", "recA4", _approval_fields(申请状态="已删除"),
        ) is None

    def test_grade_general_gm_maps_to_general(self) -> None:
        v = view_from_record(
            "approval", "recA5", _approval_fields(变更级别="一般（需总经理审批）"),
        )
        assert v is not None
        assert v.change_grade == "general"

    def test_unknown_status_defaults_draft(self) -> None:
        v = view_from_record(
            "approval", "recA6", _approval_fields(申请状态="挂起中"),
        )
        assert v is not None
        assert v.status == "draft"


class TestAcceptanceMapping:
    def test_full_mapping(self) -> None:
        v = view_from_record("acceptance", "recB1", _acceptance_fields())
        assert v is not None
        assert v.kind == "acceptance"
        assert v.change_no == "FXYS-2025-11"  # Url text 空 → 变更编号 fallback
        assert v.title == "精制车间搬迁验收"
        assert v.change_type is None  # 验收表无此列
        assert v.change_grade == "general"  # 「一般变更」映射
        assert v.department == "精制工程一部"
        assert v.status == "under_review"
        assert v.expected_start is None  # 验收表无此列
        assert v.applicant_name == "李四"
        assert v.ai_review_status == "none"  # 验收表无 AI 列

    def test_deleted_status_returns_none(self) -> None:
        assert view_from_record(
            "acceptance", "recB2", _acceptance_fields(申请状态="已删除"),
        ) is None


class TestKnownQuirk:
    def test_missing_bt_change_status_not_in_view(self) -> None:
        """「变更状态」列在审批表根本不存在——视图无该字段（工具不输出）。"""
        v = view_from_record("approval", "recA7", _approval_fields())
        assert v is not None
        assert not hasattr(v, "bt_change_status")
