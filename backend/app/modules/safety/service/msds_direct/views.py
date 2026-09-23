"""MSDS 台账直读视图对象（Ticket 01）。

照 knowledge_direct/views.py 模式，字段与 MsdsDocument ORM 完全同名：

1. id = feishu_record_id = recXXX（legacy 为镜像 UUID——工具体 id 仅信息性，
   双态落档 spec §4.3）；
2. 直读常量列（spec §0 结论三 + §4.3）：
   - review_status/archive_status 恒 "pending"：全库无赋值点、审核流未上线，
     与镜像实际值一致；审核流上线需重评估切面；
   - collection_record_id/label_elements/hazard_class/msds_attachment_path/
     reviewed_by/reviewed_at/archived_at：Bitable 无此列或镜像专属 → 恒 None；
   - created_at/updated_at：PG 审计时间不可直读 → 恒 None；
   - is_deleted 恒 False：Bitable 行删除即物理消失，直读天然不含已删行。
3. 映射用底座 fields.*（f_text/f_datetime/f_attachments 双形态解析），
   **不复用 handler `_text`**：其对 search 富文本段形态产出字符串化垃圾
   （handler 自身走 get_record 纯字符串形态故无恙，spec §0 探针实证）。
   日期语义与 handler `_date_from_raw` 同为 UTC .date()（镜像同口径）；
   附件四键投影（name/file_token/url/tmp_url）与空→None 对齐 handler
   `_attachments`。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.modules.safety.service.bitable_direct import fields as bd_fields

__all__ = [
    "MsdsDocumentView",
    "view_from_record",
]

# 台账表 28 个数据列的 Bitable 中文列名 → 视图属性
# （= handler BITABLE_TO_MODEL 去 source_date/msds_attachment 的文本面）
_TEXT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("物质名称", "name"),
    ("CAS号", "cas_no"),
    ("分子式", "molecular_formula"),
    ("UN编号", "un_no"),
    ("危险性说明", "hazard_statement"),
    ("外观与现状", "appearance"),
    ("溶解性", "solubility"),
    ("熔点", "melting_point"),
    ("沸点", "boiling_point"),
    ("闪点", "flash_point"),
    ("相对密度", "relative_density"),
    ("爆炸上限", "explosion_upper_limit"),
    ("爆炸下限", "explosion_lower_limit"),
    ("自燃温度", "autoignition_temperature"),
    ("分解温度", "decomposition_temperature"),
    ("PC-TWA", "pc_twa"),
    ("PC-STEL", "pc_stel"),
    ("MAC", "mac"),
    ("健康危害", "health_hazard"),
    ("环境危害", "environmental_hazard"),
    ("急救措施", "first_aid"),
    ("消防措施", "fire_fighting"),
    ("泄漏应急处理", "leakage_response"),
    ("废弃处置", "waste_disposal"),
    ("接触控制与个体防护", "exposure_controls"),
    ("操作处置与储存注意事项", "handling_storage"),
    ("稳定性和反应性", "stability_reactivity"),
)


@dataclass
class MsdsDocumentView:
    """MSDS 台账行的内存视图对象（不落库、不参与 ORM）。"""

    # 标识与元数据（id/feishu_record_id 同值 recXXX）
    id: str = ""
    feishu_record_id: str | None = None

    # 业务字段（与 ORM 完全同名）
    source_date: date | None = None
    name: str | None = None
    cas_no: str | None = None
    molecular_formula: str | None = None
    un_no: str | None = None
    hazard_class: str | None = None
    hazard_statement: str | None = None
    label_elements: str | None = None
    appearance: str | None = None
    solubility: str | None = None
    melting_point: str | None = None
    boiling_point: str | None = None
    flash_point: str | None = None
    relative_density: str | None = None
    explosion_upper_limit: str | None = None
    explosion_lower_limit: str | None = None
    autoignition_temperature: str | None = None
    decomposition_temperature: str | None = None
    pc_twa: str | None = None
    pc_stel: str | None = None
    mac: str | None = None
    health_hazard: str | None = None
    environmental_hazard: str | None = None
    first_aid: str | None = None
    fire_fighting: str | None = None
    leakage_response: str | None = None
    waste_disposal: str | None = None
    exposure_controls: str | None = None
    handling_storage: str | None = None
    stability_reactivity: str | None = None
    msds_attachment: list[dict[str, Any]] | None = None
    msds_attachment_path: str | None = None

    # 状态列（镜像专属；直读常量，见模块 docstring）
    review_status: str = "pending"
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    archive_status: str = "pending"
    archived_at: datetime | None = None
    collection_record_id: str | None = None

    # 审计列（PG 审计时间/操作人不可直读）
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: str | None = None
    updated_by: str | None = None
    is_deleted: bool = False


def _attachments_like_handler(value: Any) -> list[dict[str, Any]] | None:
    """附件四键投影 + 空→None（对齐 handler `_attachments` 语义）。"""
    items = bd_fields.attachment_list(value)
    metas = [
        {
            "name": str(item.get("name", "")),
            "file_token": str(item.get("file_token", "")),
            "url": str(item.get("url", "")),
            "tmp_url": str(item.get("tmp_url", "")),
        }
        for item in items
    ]
    return metas or None


def view_from_record(record_id: str, fields: dict[str, Any]) -> MsdsDocumentView:
    """Bitable 原始 fields dict → 视图对象（纯函数，零 IO）。"""
    view = MsdsDocumentView(id=record_id, feishu_record_id=record_id)
    for column, attr in _TEXT_COLUMNS:
        setattr(view, attr, bd_fields.text(fields, column))
    raw_date = bd_fields.datetime_ms(fields, "日期")
    view.source_date = raw_date.date() if raw_date else None
    view.msds_attachment = _attachments_like_handler(fields.get("MSDS附件"))
    return view
