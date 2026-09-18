"""点检记录类型化模型：Bitable records/search 原始字段 -> InspectionRecord。

字段名与「灭火器点检」多维表格一致；缺失字段容错为 None/空元组，不抛错。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

# 业务时区固定东八（房内惯例，见 business_agent/core/prompt.py）
APP_TZ = timezone(timedelta(hours=8))

# 字段名常量（Bitable 按字段名索引）
FIELD_EQUIPMENT = "设备编号"
FIELD_INSPECTOR = "点检人"
FIELD_DEPT = "点检人.部门"
FIELD_INSPECT_AT = "点检时间"
FIELD_RESULT = "点检结果"
FIELD_RECTIFY = "整改状态"
FIELD_ABNORMAL = "异常描述"
FIELD_OVERALL_PHOTOS = "整体照片"
FIELD_KEY_PHOTOS = "关键部位照片"
FIELD_SIGNATURES = "签字"
FIELD_REPORTS = "巡检记录"
FIELD_CREATED_BY = "创建人"
FIELD_CREATED_AT = "创建时间"
FIELD_CONFIRM = "本人确认已按要求完成该消防设施现场点检，所填点检结果及上传照片真实有效。"

# 五个点检项目 checkbox，按归档样例行序
CHECK_FIELDS: tuple[str, ...] = (
    "外壳、支座、压把是否腐蚀严重",
    "封签、插销是否完好",
    "喷嘴皮管是否破损、老化",
    "压力表指针是否在绿色区域内",
    "灭火器是否在设定位置（无遮挡、易启用）",
)


@dataclass(frozen=True)
class Attachment:
    """附件引用（下载与回填所需最小字段）。"""

    file_token: str
    name: str
    size: int = 0


@dataclass(frozen=True)
class InspectionRecord:
    """单条点检记录的类型化视图。"""

    record_id: str
    equipment_no: str | None
    inspector: str | None
    dept: str | None
    inspect_at: datetime | None
    result: str | None
    rectify_status: str | None
    abnormal_desc: str | None
    confirmed: bool | None
    checks: tuple[tuple[str, bool | None], ...]
    overall_photos: tuple[Attachment, ...]
    key_photos: tuple[Attachment, ...]
    signatures: tuple[Attachment, ...]
    reports: tuple[Attachment, ...]
    created_by: str | None
    created_at: datetime | None


def _text(fields: dict[str, Any], name: str) -> str | None:
    """文本值归一：富文本段列表 [{text}] 直接拼接，select 数组用「、」连接。"""
    value = fields.get(name)
    if value is None:
        return None
    if isinstance(value, list):
        if any(isinstance(seg, dict) for seg in value):
            text = "".join(
                str(seg.get("text") or "") if isinstance(seg, dict) else str(seg)
                for seg in value
            )
        else:
            text = "、".join(str(seg) for seg in value)
        text = text.strip()
        return text or None
    text = str(value).strip()
    return text or None


def _ms_to_dt(value: Any) -> datetime | None:
    """Bitable datetime/created_at 为毫秒时间戳。"""
    if value is None or value == "":
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=APP_TZ)
    except (TypeError, ValueError, OSError):
        return None


def _user_name(value: Any) -> str | None:
    """user/created_by 字段：[{id, name}] 或 {id, name}，取首个姓名。"""
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return None
    for item in value:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            if name:
                return name
    return None


def _attachments(value: Any) -> tuple[Attachment, ...]:
    if not isinstance(value, list):
        return ()
    result: list[Attachment] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        token = str(item.get("file_token") or "").strip()
        if not token:
            continue
        try:
            size = int(item.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        result.append(Attachment(file_token=token, name=str(item.get("name") or ""), size=size))
    return tuple(result)


def _checkbox(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    return bool(value)


def parse_record(raw: dict[str, Any]) -> InspectionRecord:
    """解析 records/search 单条记录；容忍字段缺失。"""
    fields = raw.get("fields") or {}
    return InspectionRecord(
        record_id=str(raw.get("record_id") or ""),
        equipment_no=_text(fields, FIELD_EQUIPMENT),
        inspector=_user_name(fields.get(FIELD_INSPECTOR)),
        dept=_text(fields, FIELD_DEPT),
        inspect_at=_ms_to_dt(fields.get(FIELD_INSPECT_AT)),
        result=_text(fields, FIELD_RESULT),
        rectify_status=_text(fields, FIELD_RECTIFY),
        abnormal_desc=_text(fields, FIELD_ABNORMAL),
        confirmed=_checkbox(fields.get(FIELD_CONFIRM)),
        checks=tuple((name, _checkbox(fields.get(name))) for name in CHECK_FIELDS),
        overall_photos=_attachments(fields.get(FIELD_OVERALL_PHOTOS)),
        key_photos=_attachments(fields.get(FIELD_KEY_PHOTOS)),
        signatures=_attachments(fields.get(FIELD_SIGNATURES)),
        reports=_attachments(fields.get(FIELD_REPORTS)),
        created_by=_user_name(fields.get(FIELD_CREATED_BY)),
        created_at=_ms_to_dt(fields.get(FIELD_CREATED_AT)),
    )
