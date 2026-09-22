"""emergency_drill 主表直读视图对象（Ticket 01）。

照 contractor_admission_direct/views.py 模式：

1. EmergencyDrillRecordView：字段名与 EmergencyDrillRecord ORM 完全同名
   （审计列 is_deleted 等不设，契约单测固化）；id = feishu_record_id = recXXX
   （镜像按 feishu_record_id 对齐，两路径 id 空间一致）；created_at/updated_at
   恒 None——探针实证主表无「创建日期」公式列（spec §0，默认排序改
   plan_time_ref desc，spec §4.1 D3）；eval_source_record_file_token 平台专属
   去重 token，Bitable 无此列，恒 None。
2. view_from_record_id：复用镜像同一映射纯函数
   ``feishu/emergency_drill_bitable_handler._map_fields``（静态、零 IO；17 标量
   + 3 person + 计划时间参考；探针实证「组织人 (人员 )」「演练评估表」不在表，
   两侧恒 None 天然对齐），6 附件键覆盖为统一存储路径推算——
   _map_fields 产出的是 name/file_token JSON 串（下载前形态），镜像终态是
   handler 下载后的存储路径字符串列表（spec §4.1 D4 拍板）。
3. 附件路径推算与 handler ``_download_and_replace_attachments`` / drill_eval
   ``_write_bitable`` 落盘命名完全一致：
   ``drill_{recXXX}_{file_token}_{name}`` → attachment_store.safe_filename →
   MinIO 模式 ``drill/{sf}`` / 本地模式 ``safety/drill/{sf}``（统一正斜杠，
   files 端点 normpath 兼容，与 MinIO key 同形）；前端
   /api/v1/safety/files/{path} 两态同链接；未下载过的文件 404 降级（spec 落档）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.core.storage import is_enabled as minio_enabled
from app.modules.safety import attachment_store
from app.modules.safety.feishu.emergency_drill_bitable_handler import (
    ATTACHMENT_FIELDS,
    BITABLE_TO_MODEL,
    PERSON_FIELDS,
    _map_fields,
)

__all__ = [
    "EmergencyDrillRecordView",
    "attachment_store_paths",
    "mapped_field_keys",
    "view_from_record_id",
]


@dataclass
class EmergencyDrillRecordView:
    """演练主表行的内存视图对象（不落库、不参与 ORM）。"""

    # 标识与元数据（id/feishu_record_id 同值 recXXX）
    id: str = ""
    feishu_record_id: str | None = None

    # 计划阶段（字段名与 ORM 完全同名）
    plan_time: str | None = None
    plan_time_ref: date | None = None
    drill_type: str | None = None
    drill_content: str | None = None
    organizer: str | None = None
    department: str | None = None
    organizer_person: str | None = None
    participants: str | None = None
    coop_department: str | None = None
    duration: str | None = None
    notes: str | None = None
    alert_person: str | None = None
    alert_person_data: dict[str, Any] | None = None

    # 实施阶段
    execution_time: date | None = None
    drill_plan_file: list[Any] | None = None
    plan_final_file: list[Any] | None = None
    signin_file: list[Any] | None = None
    eval_form_file: list[Any] | None = None
    drill_record_file: list[Any] | None = None
    eval_ai_file: list[Any] | None = None
    eval_source_record_file_token: str | None = None  # 平台专属，直读恒 None

    # 复核阶段
    issues: str | None = None
    rectification_time: date | None = None
    rectification_person: str | None = None
    rectification_person_data: dict[str, Any] | None = None
    confirmer: str | None = None
    confirmer_data: dict[str, Any] | None = None
    status: str | None = None

    # 审计列（镜像有值；直读恒 None——无创建日期公式列，spec §0）
    created_at: datetime | None = None
    updated_at: datetime | None = None


def attachment_store_paths(record_id: str, raw: Any) -> list[str] | None:
    """Bitable 附件原始值 → 统一存储路径列表（handler 落盘命名同款推算）。"""
    if not raw or not isinstance(raw, list):
        return None
    safe_record = record_id.replace("/", "_").replace("\\", "_")
    paths: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        token = str(item.get("file_token") or "")
        if not name and not token:
            continue
        filename = (
            f"drill_{safe_record}_{token}_{name}" if token
            else f"drill_{safe_record}_{name}"
        )
        stored = attachment_store.safe_filename(filename)
        paths.append(f"drill/{stored}" if minio_enabled() else f"safety/drill/{stored}")
    return paths or None


def view_from_record_id(record_id: str, fields: dict[str, Any]) -> EmergencyDrillRecordView:
    """Bitable 原始 fields dict → 视图对象（映射复用 handler 同一纯函数）。"""
    mapped = _map_fields(fields) or {}
    view = EmergencyDrillRecordView(id=record_id)
    for key, value in mapped.items():
        setattr(view, key, value)
    view.feishu_record_id = record_id
    # 附件列覆盖为存储路径推算（_map_fields 的 JSON 串形态是下载前中间态）
    for cn_field, en_field in ATTACHMENT_FIELDS.items():
        setattr(view, en_field, attachment_store_paths(record_id, fields.get(cn_field)))
    return view


def mapped_field_keys() -> tuple[str, ...]:
    """映射产出键全集（静态映射字典推导；本域无直读触发器，供 verify/回填用）。"""
    keys: set[str] = set(BITABLE_TO_MODEL.values())
    keys.update(PERSON_FIELDS.values())
    keys.update(ATTACHMENT_FIELDS.values())
    keys.add("plan_time_ref")
    return tuple(sorted(keys))
