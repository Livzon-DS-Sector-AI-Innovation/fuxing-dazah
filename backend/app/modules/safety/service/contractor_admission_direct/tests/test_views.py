"""contractor_admission 直读视图接缝单测（Ticket 01）。

覆盖：视图与 ORM 字段同名契约、映射纯函数复用（富文本/Person/日期/附件原始结构）、
派生 AI 态（3 列推导，D2）、创建日期公式列、diff 键附件归约。
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.safety.models import ContractorAdmission
from app.modules.safety.service.contractor_admission_direct.views import (
    AI_REVIEW_STATUS_COMPLETED,
    AI_REVIEW_STATUS_NONE,
    ContractorAdmissionView,
    derive_ai_state,
    mapped_diff_key,
    mapped_field_keys,
    view_from_record_id,
)

_VIEW_OMITTED_ORM_COLUMNS = {"created_by", "updated_by", "is_deleted"}


def _orm_column_names() -> set[str]:
    return {c.name for c in ContractorAdmission.__table__.columns}


def _fields(**over):
    f: dict = {
        "作业单位名称": [{"text": "某某工程有限公司", "type": "text"}],
        "相关方类型": "承包商",
        "承包商负责人": [{"text": "张三", "type": "text"}],
        "承包商负责人联系电话": [{"text": "13800000000", "type": "text"}],
        "对接人员": [{"id": "ou_x", "name": "李四"}],
        "入厂日期": 1765382400000,
        "开始日期": 1765382400000,
        "结束日期": 1767964800000,
        "材料失效日期": 1770470400000,
        "实际提交日期": 1765296000000,
        "实际完成日期": None,
        "提交状态": "已完成",
        "培训状态": "已培训/待补材",
        "备注": [{"text": "备注内容", "type": "text"}],
        "承包商安全管理协议": [{
            "file_token": "tok_a", "name": "协议.pdf", "size": 123,
            "url": "https://example/a", "tmp_url": "https://example/b",
        }],
        "企业营业执照": [{"file_token": "tok_b", "name": "执照.png"}],
        "现场作业保险凭证": None,
        "创建日期": 1765443837000,
        "AI审核结论": "需补充完善",
        "AI审核报告": [{"text": "一、安全管理协议-A基础信息类……", "type": "text"}],
        "AI不符合项": ["安全管理协议-A基础信息类", "安全管理协议-C签章类"],
    }
    f.update(over)
    return f


class TestViewSeam:
    def test_view_fields_cover_orm_columns(self) -> None:
        view_fields = {f.name for f in ContractorAdmissionView.__dataclass_fields__.values()}
        missing = _orm_column_names() - _VIEW_OMITTED_ORM_COLUMNS - view_fields
        assert not missing, f"视图缺少 ORM 同名字段: {sorted(missing)}"

    def test_view_from_record_id_mapping(self) -> None:
        view = view_from_record_id("rec1", _fields())
        assert view.id == "rec1"
        assert view.feishu_record_id == "rec1"
        assert view.feishu_table_id == "admission"
        assert view.source == "bitable"
        assert view.admission_no is None
        assert view.feishu_url is None
        assert view.updated_at is None
        # 富文本 / Person / Select 直存
        assert view.company_name == "某某工程有限公司"
        assert view.contact_person == "张三"
        assert view.contact_phone == "13800000000"
        assert view.liaison_user_id == "ou_x"
        assert view.liaison_user_name == "李四"
        assert view.related_party_type == "承包商"
        assert view.submit_status == "已完成"
        assert view.training_status == "已培训/待补材"
        assert view.notes == "备注内容"
        # 日期 ms → date（平台只存日期部分）
        assert view.entry_date == datetime.fromtimestamp(1765382400, tz=UTC).date()
        assert view.actual_complete_date is None
        # 附件保留原始 Bitable 结构（含 url）
        assert view.safety_agreement_files == [{
            "file_token": "tok_a", "name": "协议.pdf", "size": 123,
            "url": "https://example/a", "tmp_url": "https://example/b",
        }]
        assert view.insurance_files is None
        # created_at = 创建日期公式列（ms → UTC datetime）
        assert view.created_at == datetime.fromtimestamp(1765443837, tz=UTC)

    def test_derived_ai_state_completed(self) -> None:
        view = view_from_record_id("rec1", _fields())
        assert view.ai_review_status == AI_REVIEW_STATUS_COMPLETED
        result = view.ai_review_result
        assert result is not None
        assert result["agreement"] is None
        assert result["license"] is None
        assert result["insurance"] is None
        assert result["overall_conclusion"] == "需补充完善"
        assert result["overall_report"] == "一、安全管理协议-A基础信息类……"
        assert result["defect_categories"] == [
            "安全管理协议-A基础信息类", "安全管理协议-C签章类",
        ]
        assert result["regulations"] == []
        assert view.ai_error_message is None
        assert view.ai_reviewed_at is None

    def test_derived_ai_state_none(self) -> None:
        view = view_from_record_id("rec2", _fields(AI审核结论=None, AI审核报告=None,
                                                    AI不符合项=None))
        assert view.ai_review_status == AI_REVIEW_STATUS_NONE
        assert view.ai_review_result is None

    def test_derive_ai_state_dedup_and_plain_str(self) -> None:
        status, result = derive_ai_state(_fields(
            AI审核结论="审核通过",
            AI审核报告="纯文本报告",
            AI不符合项=["安全管理协议-B有效期类", "安全管理协议-B有效期类", ""],
        ))
        assert status == AI_REVIEW_STATUS_COMPLETED
        assert result is not None
        assert result["overall_conclusion"] == "审核通过"
        assert result["overall_report"] == "纯文本报告"
        assert result["defect_categories"] == ["安全管理协议-B有效期类"]

    def test_mapped_field_keys_cover_mapping(self) -> None:
        keys = set(mapped_field_keys())
        assert "company_name" in keys
        assert "safety_agreement_files" in keys
        assert "ai_review_status" not in keys  # 派生态不在 map_fields 键集


class TestMappedDiffKey:
    def test_attachment_reduced_to_file_tokens(self) -> None:
        """附件只比 file_token：url 每拉必变，diff 键必须稳定。"""
        a = mapped_diff_key({
            "company_name": "甲",
            "safety_agreement_files": [{"file_token": "t1", "url": "https://x/1"}],
        })
        b = mapped_diff_key({
            "company_name": "甲",
            "safety_agreement_files": [{"file_token": "t1", "url": "https://x/2"}],
        })
        assert a == b

    def test_diff_detects_value_change(self) -> None:
        unchanged = mapped_diff_key({"submit_status": "已完成", "notes": None})
        changed = mapped_diff_key({"submit_status": "进行中", "notes": None})
        assert unchanged != changed

    def test_key_order_stable_across_insert_order(self) -> None:
        a = mapped_diff_key({"a": 1, "b": 2})
        b = mapped_diff_key({"b": 2, "a": 1})
        assert a == b
