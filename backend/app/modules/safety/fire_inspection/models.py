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
# AI 审核写回列（2026-11-05 建：审核结果单选 通过/不通过 + 审核说明文本）
FIELD_AUDIT_RESULT = "审核结果"
FIELD_AUDIT_NOTE = "审核说明"

# 点检项目字段，按表单行序（带全角序号前缀，与表内字段名逐字一致）。
# 2026-11-04 事故教训：表字段改名（加序号前缀 + 第 1/3 项正向化 + checkbox
# 改「是/否」单选）后代码常量未跟随，fields.get 全 None 被 PDF 渲染成
# 「不符合」，11-01 起连续 86 条归档全错。字段名必须与表逐字对齐。
CHECK_FIELDS: tuple[str, ...] = (
    "（1）外壳、支座、压把是否完好无腐蚀",
    "（2）封签、插销是否完好",
    "（3）喷嘴皮管是否完好无破损、老化",
    "（4）压力表指针是否在绿色区域内",
    "（5）灭火器是否在设定位置（无遮挡、易启用）",
)
# 消火栓表点检项（4 项，2026-11-10 接入；与灭火器表同 Base 克隆结构）
HYDRANT_CHECK_FIELDS: tuple[str, ...] = (
    "（1）箱框、面板、标识是否完好",
    "（2）消防水管道是否漏水；水阀及其接口是否完好",
    "（3）水枪头、水带是否齐全完好；软管卷盘是否完好",
    "（4）消火栓手动按钮红灯是否闪烁",
)


@dataclass(frozen=True)
class DeviceSpec:
    """设备类型规格：表坐标 + 点检项清单，PDF 归档/AI 审核按 spec 双表并行。

    两表为同 Base 克隆结构：共享字段名（设备编号/照片/签字/巡检记录
    fldpZSHrTd 等），仅点检项与 table_id 不同。
    """

    kind: str  # 稳定标识（日志/测试）
    label: str  # 中文名（日志/错误信息）
    table_config_key: str  # app_config 键（表坐标可被 DB/env 覆盖）
    table_default: str
    check_fields: tuple[str, ...]


EXTINGUISHER_SPEC = DeviceSpec(
    kind="extinguisher",
    label="灭火器",
    table_config_key="SAFETY_FIRE_INSPECTION_TABLE_ID",
    table_default="tblUB2sT3b3GBerU",
    check_fields=CHECK_FIELDS,
)
HYDRANT_SPEC = DeviceSpec(
    kind="hydrant",
    label="消火栓",
    table_config_key="SAFETY_FIRE_INSPECTION_HYDRANT_TABLE_ID",
    table_default="tblQGM4mJsTPQCht",
    check_fields=HYDRANT_CHECK_FIELDS,
)
ALL_SPECS: tuple[DeviceSpec, ...] = (EXTINGUISHER_SPEC, HYDRANT_SPEC)


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
    # AI 审核现状（空 = 未审，轮询待审队列的判定依据）
    audit_result: str | None = None
    audit_note: str | None = None


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
    """点检项取值：现表为「是/否」单选字符串，旧表为 checkbox 布尔。

    未识别的值（含缺失）返回 None，由渲染层显示「—」，绝不猜成符合/不符合。
    注意 bool("否") 为 True——字符串必须按词表显式解析。
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text in {"是", "true", "True", "TRUE", "1", "yes"}:
            return True
        if text in {"否", "false", "False", "FALSE", "0", "no"}:
            return False
        return None
    return bool(value)


def parse_record(raw: dict[str, Any], spec: DeviceSpec = EXTINGUISHER_SPEC) -> InspectionRecord:
    """解析 records/search 单条记录；容忍字段缺失。

    点检项按 spec.check_fields 取值——两表项目清单不同，默认灭火器保持
    既有调用兼容。
    """
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
        checks=tuple((name, _checkbox(fields.get(name))) for name in spec.check_fields),
        overall_photos=_attachments(fields.get(FIELD_OVERALL_PHOTOS)),
        key_photos=_attachments(fields.get(FIELD_KEY_PHOTOS)),
        signatures=_attachments(fields.get(FIELD_SIGNATURES)),
        reports=_attachments(fields.get(FIELD_REPORTS)),
        created_by=_user_name(fields.get(FIELD_CREATED_BY)),
        created_at=_ms_to_dt(fields.get(FIELD_CREATED_AT)),
        audit_result=_text(fields, FIELD_AUDIT_RESULT),
        audit_note=_text(fields, FIELD_AUDIT_NOTE),
    )
