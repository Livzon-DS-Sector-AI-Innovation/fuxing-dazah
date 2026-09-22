"""emergency_drill 直读视图对象单测（Ticket 01）。

覆盖：视图字段与 ORM 奇偶、_map_fields 复用映射、附件 store 路径推算
（MinIO/本地双模式）、person dict 派生、探针实证缺失字段恒 None、
created_at/updated_at/eval_source_record_file_token 恒 None。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.safety import attachment_store
from app.modules.safety.models import EmergencyDrillRecord
from app.modules.safety.service.emergency_drill_direct import views as views_mod
from app.modules.safety.service.emergency_drill_direct.views import (
    EmergencyDrillRecordView,
    mapped_field_keys,
    view_from_record_id,
)


# 与探针实证形态一致的合成主表字段（search 口径）
def _main_fields() -> dict[str, Any]:
    return {
        "计划时间": [{"text": "1月", "type": "text"}],
        "计划时间参考": 1767196800000,
        "演练类型": "应急疏散演练",
        "演练内容": [{"text": "第一季度火灾疏散演练", "type": "text"}],
        "组织人": "张三",
        "演练部门": "设备动力部",
        "参演人员": [{"text": "当班人员", "type": "text"}],
        "配合部门": "行政楼其他部门",
        "课时": "1小时",
        "备  注": [{"text": "备注x", "type": "text"}],
        "提醒人员": "李四",
        "实施时间": 1768924800000,
        "演练问题": [{"text": "1. 灭火器过期", "type": "text"}],
        "整改时间": 1770000000000,
        "整改责任人": [{"id": "ou1", "name": "王五"}],
        "确认人": [{"id": "ou2", "name": "赵六"}],
        "状态": "已完成",
        "演练方案（AI）": [
            {"file_token": "tok_plan", "name": "方案.docx"},
            {"file_token": "tok_plan2", "name": "方案v2.docx"},
        ],
        "签到表": [{"file_token": "tok_sign", "name": "签到表.pdf"}],
        "演练记录表": [{"file_token": "tok_rec", "name": "记录表.docx"}],
        "演练评估表（AI）": [{"file_token": "tok_eval", "name": "评估表.docx"}],
    }


class TestFieldParity:
    def test_view_covers_orm_business_columns(self) -> None:
        """视图字段 ⊇ ORM 业务列（审计列豁免，契约固化）。"""
        orm_cols = {c.name for c in EmergencyDrillRecord.__table__.columns}
        audit = {"is_deleted", "created_by", "updated_by"}
        view_fields = set(EmergencyDrillRecordView.__dataclass_fields__)
        missing = (orm_cols - audit) - view_fields
        assert not missing, f"视图缺 ORM 列: {sorted(missing)}"
        assert "is_deleted" not in view_fields

    def test_mapped_field_keys_static(self) -> None:
        from app.modules.safety.feishu.emergency_drill_bitable_handler import (
            ATTACHMENT_FIELDS,
            BITABLE_TO_MODEL,
            PERSON_FIELDS,
        )

        expected = (
            set(BITABLE_TO_MODEL.values())
            | set(PERSON_FIELDS.values())
            | set(ATTACHMENT_FIELDS.values())
            | {"plan_time_ref"}
        )
        assert set(mapped_field_keys()) == expected


class TestMapping:
    def test_scalar_mapping_reuses_handler(self) -> None:
        view = view_from_record_id("rec1", _main_fields())
        assert view.id == "rec1"
        assert view.feishu_record_id == "rec1"
        assert view.plan_time == "1月"
        assert view.drill_type == "应急疏散演练"
        assert view.drill_content == "第一季度火灾疏散演练"
        assert view.department == "设备动力部"
        assert view.participants == "当班人员"
        assert view.status == "已完成"
        assert view.issues == "1. 灭火器过期"
        # 日期 ms → date（与 handler _date 同口径）
        assert view.plan_time_ref == datetime.fromtimestamp(
            1767196800, tz=UTC
        ).date()
        assert view.execution_time == datetime.fromtimestamp(
            1768924800, tz=UTC
        ).date()

    def test_person_derivation(self) -> None:
        view = view_from_record_id("rec1", _main_fields())
        assert view.rectification_person == "王五"
        assert view.rectification_person_data == {
            "open_id": "ou1", "name": "王五", "email": "",
        }
        assert view.confirmer == "赵六"
        assert view.confirmer_data == {
            "open_id": "ou2", "name": "赵六", "email": "",
        }

    def test_probe_absent_fields_none(self) -> None:
        """探针实证不在表的字段：镜像恒 None，直读同口径。"""
        view = view_from_record_id("rec1", _main_fields())
        assert view.organizer_person is None  # 组织人 (人员 ) 不在表
        assert view.eval_form_file is None  # 演练评估表 不在表
        assert view.alert_person_data is None  # 提醒人员 (人员 ) 不在表
        assert view.alert_person == "李四"


class TestAttachmentPaths:
    def test_local_mode_paths(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(views_mod, "minio_enabled", lambda: False)
        view = view_from_record_id("rec1", _main_fields())
        assert view.signin_file == [
            "safety/drill/"
            + attachment_store.safe_filename("drill_rec1_tok_sign_签到表.pdf")
        ]
        assert view.drill_plan_file == [
            "safety/drill/"
            + attachment_store.safe_filename("drill_rec1_tok_plan_方案.docx"),
            "safety/drill/"
            + attachment_store.safe_filename("drill_rec1_tok_plan2_方案v2.docx"),
        ]

    def test_minio_mode_paths(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(views_mod, "minio_enabled", lambda: True)
        view = view_from_record_id("rec1", _main_fields())
        assert view.drill_record_file == [
            "drill/"
            + attachment_store.safe_filename("drill_rec1_tok_rec_记录表.docx")
        ]
        assert view.eval_ai_file == [
            "drill/"
            + attachment_store.safe_filename("drill_rec1_tok_eval_评估表.docx")
        ]

    def test_attachment_empty_shapes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(views_mod, "minio_enabled", lambda: True)
        view = view_from_record_id("rec1", {
            "演练记录表": [],
            "签到表": [{"name": "", "file_token": ""}, "junk",
                      {"file_token": "tok", "name": "a.pdf"}],
        })
        assert view.drill_record_file is None
        assert view.signin_file == [
            "drill/" + attachment_store.safe_filename("drill_rec1_tok_a.pdf")
        ]

    def test_attachment_path_matches_handler_download_naming(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """推算命名与 handler _download_and_replace_attachments 落盘一致（D4 根基）。"""
        record_id = "recX/1"  # 含分隔符时 handler 先替换
        monkeypatch.setattr(views_mod, "minio_enabled", lambda: True)
        view = view_from_record_id(record_id, {
            "签到表": [{"file_token": "tok", "name": "a b.pdf"}],
        })
        safe_record = record_id.replace("/", "_").replace("\\", "_")
        expected = "drill/" + attachment_store.safe_filename(
            f"drill_{safe_record}_tok_a b.pdf"
        )
        assert view.signin_file == [expected]


class TestControlledNone:
    def test_audit_and_platform_only_none(self) -> None:
        view = view_from_record_id("rec1", _main_fields())
        # 探针实证：主表无创建日期公式列 → created_at/updated_at 恒 None
        assert view.created_at is None
        assert view.updated_at is None
        # 平台专属去重 token 不在 Bitable → 恒 None
        assert view.eval_source_record_file_token is None

    def test_empty_fields_minimal_view(self) -> None:
        view = view_from_record_id("rec2", {})
        assert view.id == "rec2"
        assert view.drill_type is None
        assert view.drill_plan_file is None
