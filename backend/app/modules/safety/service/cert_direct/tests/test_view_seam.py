"""cert 直读视图接缝单测（cert-direct Ticket 01）。

覆盖：视图对象与 ORM 字段同名契约、映射纯函数复用（含无姓名跳过、
guardian_b 缺「已换证日期」）、CertWarningEngine 吃视图对象零改动、
镜像口径排序等价（含 None 边界）。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.modules.safety.models import PersonCertificate
from app.modules.safety.service.cert_direct.reader import (
    CertWarningView,
    sort_like_mirror,
    view_from_mapped,
)
from app.modules.safety.service.cert_warning import CertWarningEngine

# 直读视图不承载的 ORM 列：审计列与软删标记（镜像查询恒过滤 is_deleted，
# created_by/updated_by 由平台写入，Bitable 侧无对应字段）
_VIEW_OMITTED_ORM_COLUMNS = {"created_by", "updated_by", "is_deleted"}


def _orm_column_names() -> set[str]:
    return {c.name for c in PersonCertificate.__table__.columns}


def _make_special_op_fields() -> dict[str, object]:
    return {
        "姓名 (人员 )": [{"name": "张三"}],
        "部门": "生产部",
        "作业类别": "电工",
        "项目": "低压电工作业",
        "证件编号": "T5325011980001",
        "取证日期": 1700000000000,
        "再复审时间": 1800000000000,
        "复审频次": "3年",
    }


def _make_guardian_fields() -> dict[str, object]:
    return {
        "姓名": [{"name": "李四"}],
        "部门": ["质检部"],
        "证件类型": "A证",
        "取证日期": 1700000000000,
        "第一次复审截止日期": 1790000000000,
        "第二次复审截止日期": 1890000000000,
        "应换证日期": 1990000000000,
        "已换证日期": 1750000000000,
    }


class TestViewSeam:
    def test_view_fields_cover_orm_columns(self) -> None:
        """视图字段与 ORM 列同名（除显式省略的审计/软删列）。"""
        view_fields = {f.name for f in CertWarningView.__dataclass_fields__.values()}
        missing = _orm_column_names() - _VIEW_OMITTED_ORM_COLUMNS - view_fields
        assert not missing, f"视图缺少 ORM 同名字段: {sorted(missing)}"

    def test_engine_calculates_on_view(self) -> None:
        """CertWarningEngine 纯函数直接吃视图对象（零改动实证）。"""
        view = CertWarningView(
            id="recX",
            cert_category="special_op",
            person_name="张三",
            next_review_date=date.today() + timedelta(days=5),
            review_frequency="3年",
        )
        res = CertWarningEngine.calculate(view)
        assert res.status == "urgent"
        assert res.current_node == "复审"

    def test_view_from_mapped_special_op(self) -> None:
        from app.modules.safety.feishu.cert_bitable import (
            map_special_op_cert_fields,
        )

        mapped = map_special_op_cert_fields(_make_special_op_fields())
        assert mapped is not None
        view = view_from_mapped("rec1", mapped)
        assert view is not None
        assert view.id == "rec1"
        assert view.feishu_record_id == "rec1"
        assert view.source == "bitable"
        assert view.cert_category == "special_op"
        assert view.person_name == "张三"
        assert view.department == "生产部"
        assert view.operation_type == "电工"
        assert view.certificate_no == "T5325011980001"
        assert view.next_review_date is not None
        # 监护人专用字段特种作业证视图恒 None
        assert view.renewed_date is None
        assert view.first_review_deadline is None

    def test_view_from_mapped_guardian(self) -> None:
        from app.modules.safety.feishu.cert_bitable import (
            map_guardian_cert_fields,
        )

        mapped = map_guardian_cert_fields(_make_guardian_fields(), "guardian_a")
        assert mapped is not None
        view = view_from_mapped("rec2", mapped)
        assert view is not None
        assert view.cert_category == "guardian_a"
        assert view.person_name == "李四"
        assert view.department == "质检部"
        assert view.renewed_date is not None
        assert view.first_review_deadline is not None
        # 特种作业证专用字段监护人视图恒 None
        assert view.next_review_date is None
        assert view.review_frequency is None

    def test_view_from_mapped_guardian_b_missing_renewed_column(self) -> None:
        """guardian_b 表无「已换证日期」列 → renewed_date 恒 None（与镜像同口径）。"""
        from app.modules.safety.feishu.cert_bitable import (
            map_guardian_cert_fields,
        )

        fields = _make_guardian_fields()
        fields.pop("已换证日期")
        mapped = map_guardian_cert_fields(fields, "guardian_b")
        assert mapped is not None
        view = view_from_mapped("rec3", mapped)
        assert view is not None
        assert view.cert_category == "guardian_b"
        assert view.renewed_date is None

    def test_view_from_mapped_none_passthrough(self) -> None:
        """映射函数返回 None（无姓名脏数据）→ 视图同样跳过。"""
        assert view_from_mapped("rec4", None) is None


class TestSortLikeMirror:
    def _view(
        self,
        vid: str,
        category: str,
        next_review: date | None = None,
        should_renew: date | None = None,
        created_at: datetime | None = None,
    ) -> CertWarningView:
        return CertWarningView(
            id=vid,
            cert_category=category,
            person_name=vid,
            next_review_date=next_review,
            should_renew_date=should_renew,
            created_at=created_at,
        )

    def test_category_grouping(self) -> None:
        a = self._view("a", "special_op")
        g = self._view("g", "guardian_a")
        assert sort_like_mirror([a, g]) == [g, a]

    def test_next_review_asc_nulls_last(self) -> None:
        early = self._view("early", "special_op", next_review=date(2026, 1, 1))
        late = self._view("late", "special_op", next_review=date(2027, 1, 1))
        none_v = self._view("none", "special_op")
        assert sort_like_mirror([none_v, late, early]) == [early, late, none_v]

    def test_should_renew_tie_stable(self) -> None:
        """三键同值组内保持输入顺序（稳定排序）。created_at 不参与排序：
        Bitable 无时间戳字段，镜像 get_all_active 亦无第四键（审查修正）。"""
        base = date(2027, 1, 1)
        renew_a = self._view(
            "ra", "special_op", should_renew=base,
            created_at=datetime(2026, 1, 2),
        )
        renew_b = self._view(
            "rb", "special_op", should_renew=base,
            created_at=datetime(2026, 1, 3),
        )
        assert sort_like_mirror([renew_a, renew_b]) == [renew_a, renew_b]

    def test_none_created_at_sorts_stable(self) -> None:
        """直读侧 created_at 恒 None：同键组内保持输入顺序（稳定排序）。"""
        v1 = self._view("v1", "guardian_b")
        v2 = self._view("v2", "guardian_b")
        assert sort_like_mirror([v2, v1]) == [v2, v1]

    def test_matches_mirror_repo_ordering_contract(self) -> None:
        """与 repo.get_all_active 的 ORDER BY 契约（三键）逐条对应（文档化断言）。"""
        early_a = self._view("ea", "guardian_a", next_review=date(2026, 3, 1))
        late_a = self._view("la", "guardian_a", next_review=date(2026, 6, 1))
        no_date_b = self._view("nb", "guardian_b")
        special = self._view("sp", "special_op", next_review=date(2026, 1, 1))
        rows = [no_date_b, special, late_a, early_a]
        assert sort_like_mirror(rows) == [early_a, late_a, no_date_b, special]
