"""msds_direct 视图对象单测（Ticket 01）——字段映射等价与直读常量列。"""

from __future__ import annotations

from datetime import date

from app.modules.safety.models import MsdsDocument
from app.modules.safety.service.msds_direct.views import (
    MsdsDocumentView,
    view_from_record,
)

# 台账表文本字段 search 口径为富文本段，get_record 口径为纯字符串——
# 直读只见前者，但两种形态都必须解析出与镜像一致的值（spec §0 探针实证）
_SEGMENTS_NAME = [{"text": "2-丙醇;异丙醇", "type": "text"}]
_PLAIN_CAS = "67-63-0"
_DATE_MS = 1785974400000  # 2026-08-06T00:00:00Z → UTC date 2026-08-06


def _fields() -> dict:
    return {
        "物质名称": _SEGMENTS_NAME,
        "CAS号": _PLAIN_CAS,
        "UN编号": [{"text": "1219", "type": "text"}],
        "日期": _DATE_MS,
        "危险性说明": [{"text": "高度易燃液体和蒸气", "type": "text"}],
        "闪点": "12 ℃（CC）",
        "MSDS附件": [
            {
                "file_token": "tok1", "name": "std.pdf",
                "url": "https://example.com/u", "tmp_url": "", "size": 123,
            },
        ],
    }


def test_view_maps_all_business_fields() -> None:
    v = view_from_record("recABC123", _fields())
    assert v.id == "recABC123"
    assert v.feishu_record_id == "recABC123"
    assert v.name == "2-丙醇;异丙醇"
    assert v.cas_no == "67-63-0"
    assert v.un_no == "1219"
    assert v.source_date == date(2026, 8, 6)
    assert v.hazard_statement == "高度易燃液体和蒸气"
    assert v.flash_point == "12 ℃（CC）"
    # 附件四键投影对齐 handler _attachments（size/type 不带入）
    assert v.msds_attachment == [
        {"name": "std.pdf", "file_token": "tok1",
         "url": "https://example.com/u", "tmp_url": ""},
    ]


def test_view_constants_and_mirror_only_columns() -> None:
    v = view_from_record("recABC123", _fields())
    # 审核流未上线、全库无赋值点 → 与镜像实际值一致的常量（spec §4.3）
    assert v.review_status == "pending"
    assert v.archive_status == "pending"
    # Bitable 无此列/镜像专属 → 恒 None
    assert v.collection_record_id is None
    assert v.label_elements is None
    assert v.hazard_class is None
    assert v.msds_attachment_path is None
    assert v.reviewed_by is None
    assert v.reviewed_at is None
    assert v.archived_at is None
    # PG 审计时间不可直读
    assert v.created_at is None
    assert v.updated_at is None
    # Bitable 物理删除 → 直读天然不含已删行
    assert v.is_deleted is False


def test_view_empty_fields_all_none() -> None:
    v = view_from_record("recX", {})
    assert v.name is None
    assert v.cas_no is None
    assert v.source_date is None
    assert v.msds_attachment is None


def test_view_fields_match_orm_columns() -> None:
    """视图字段与 ORM 列完全同名（判定/消费代码零改动的等价性基础）。"""
    orm_cols = {c.key for c in MsdsDocument.__table__.columns}
    view_fields = {f.name for f in MsdsDocumentView.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    assert view_fields == orm_cols
