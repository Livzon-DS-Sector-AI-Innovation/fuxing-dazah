"""key_risk_op 直读视图接缝单测（Ticket 01）。

覆盖：视图与 ORM 字段同名契约、映射纯函数复用（多作业块/三阶段/Url 双列/
Person 取 name/时长 float）、report_no 兜底、镜像排序契约（DESC NULLS LAST）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.modules.safety.models import KeyRiskOperationReport
from app.modules.safety.service.key_risk_op_direct.views import (
    KeyRiskOpView,
    is_deleted_row,
    sort_like_mirror,
    view_from_record_id,
)

_VIEW_OMITTED_ORM_COLUMNS = {"created_by", "updated_by", "is_deleted"}


def _orm_column_names() -> set[str]:
    return {c.name for c in KeyRiskOperationReport.__table__.columns}


def _fields(**over: Any) -> dict[str, Any]:
    f: dict[str, Any] = {
        "申请编号": {"text": "202511280372", "link": "https://applink.example/x"},
        "申请状态": "已通过",
        "审批节点": [{"text": "审批", "type": "text"}],
        "当前处理人": [{"name": "王五", "avatar_url": "http://a"}],
        "发起人": [{"name": "张三", "avatar_url": "http://b"}],
        "发起人部门": "提炼六部",
        "发起时间": 1764311693600,
        "完成时间": 1764319000000,
        "部门": "提炼六部",
        "区域": "一号车间",
        "作业内容": "乙醇检修",
        "作业开始时间": 1764311580000,
        "作业结束时间": 1764318780000,
        "时长": 2,
        "备注": "周末作业",
        "现场作业监护人": "李四",
        "现场监护人": [{"name": "赵六"}],
        "SourceID": [{"text": "NzU3", "type": "text"}],
        # 多作业块 2
        "部门2": "QC",
        "区域2": "化验室",
        "作业内容2": "取样",
        "现场作业监护人2": [{"name": "钱七"}],
        # 三阶段
        "日期（作业前）": 1763518800000,
        "现场确认（作业前）": {"link": "https://preview.example/p"},
        "问题描述（作业前）": [{"text": "无", "type": "text"}],
    }
    f.update(over)
    return f


class TestViewSeam:
    def test_view_fields_cover_orm_columns(self) -> None:
        view_fields = {f.name for f in KeyRiskOpView.__dataclass_fields__.values()}
        missing = _orm_column_names() - _VIEW_OMITTED_ORM_COLUMNS - view_fields
        assert not missing, f"视图缺少 ORM 同名字段: {sorted(missing)}"

    def test_view_from_record_id_mapping(self) -> None:
        view = view_from_record_id("rec1", _fields())
        assert view.id == "rec1"
        assert view.feishu_record_id == "rec1"
        assert view.source == "bitable"
        # Url 双列
        assert view.report_no == "202511280372"
        assert view.approval_no_url == "https://applink.example/x"
        # Person 取 name / Select str / Text 富文本
        assert view.initiator_name == "张三"
        assert view.current_handler == "王五"
        assert view.site_guardian == "赵六"
        assert view.approval_node == "审批"
        assert view.initiator_department == "提炼六部"
        assert view.apply_status == "已通过"
        # 时间戳/时长
        assert view.start_time == datetime.fromtimestamp(1764311580, tz=UTC)
        assert view.duration_hours == 2.0
        # 多作业块 / 三阶段
        assert view.operations == [{
            "department": "QC", "area": "化验室", "operation_content": "取样",
            "guardian": "钱七",
        }]
        assert view.phase_before == {
            "date": datetime.fromtimestamp(1763518800, tz=UTC).isoformat(),
            "photo_url": "https://preview.example/p",
            "issue_desc": "无",
        }
        assert view.phase_ongoing is None
        assert view.source_id == "NzU3"
        assert view.created_at is None and view.updated_at is None

    def test_report_no_fallback(self) -> None:
        """申请编号空 → 兜底 BT-{record_id[-12:]}（与镜像 sync 同口径）。"""
        view = view_from_record_id("recABCDEF123456", _fields(申请编号={"link": "x"}))
        assert view.report_no == "BT-ABCDEF123456"

    def test_is_deleted_row(self) -> None:
        assert is_deleted_row(_fields(申请状态="已删除"))
        assert not is_deleted_row(_fields(申请状态="已通过"))


class TestSortLikeMirror:
    def _view(self, vid: str, start: datetime | None) -> KeyRiskOpView:
        return KeyRiskOpView(id=vid, feishu_record_id=vid, start_time=start)

    def test_desc_nulls_last(self) -> None:
        early = self._view("e", datetime(2026, 1, 1, tzinfo=UTC))
        late = self._view("l", datetime(2026, 6, 1, tzinfo=UTC))
        none_v = self._view("n", None)
        assert sort_like_mirror([none_v, early, late]) == [late, early, none_v]

    def test_tie_stable(self) -> None:
        t = datetime(2026, 3, 1, tzinfo=UTC)
        a = self._view("a", t)
        b = self._view("b", t)
        assert sort_like_mirror([b, a]) == [b, a]
