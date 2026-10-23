"""链3：签到/成绩单解析——附件下载 → vision 解析 → 分级回填。

数据流（DESIGN 二期 §6.1）：POST parse-record（取该行「签到表」附件列首个
文件）→ download_bitable_attachment（bitablePerm extra 鉴权，与照片回填
同构的既有链）→ encode_image_for_vision（Pillow 校验+降采样）→
AI(training_record_parsing, vision, temp 0.1) → 按 §6.3 分级回填：

- confidence=high 且 doc_type∈{签到表,成绩单} → 回填 实到人数/考核合格人数
  （None 不回填）+ 备注追加解析明细；
- confidence=medium/low → 数字列不动，明细进备注（`AI解析(confidence=…)`）
  待人工；
- doc_type=无法识别 → 仅备注记录。

人终判：人工在表上直接改=覆盖（重复解析按需手动触发，无幂等标记）。

接缝（双接缝测试）：opener 替身注入 Bitable 客户端（fake 需实现
list_all_records/list_fields/update_record/download_bitable_attachment）；
ai_service 注入假服务（chat_vision_parsed）。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.modules.safety.ai_training_record_parsing import (
    CONFIDENCE_HIGH,
    DOC_UNKNOWN,
    TrainingRecordParseInput,
    TrainingRecordParseOutput,
    TrainingRecordParsingError,
    TrainingRecordParsingPlugin,
)
from app.modules.safety.service.bitable_direct import fields as bd_fields
from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.bitable_direct.writer import resolve_field_id
from app.modules.safety.service.training_behavior.common import Opener, bj_today

logger = logging.getLogger(__name__)

SIGN_COLUMN = "签到表"
ATTENDANCE_COLUMN = "实到人数"
PASSED_COLUMN = "考核合格人数"
REMARK_COLUMN = "备注"

_READ_FIELDS = (
    "培训名称", "应到人数", "考核方式", SIGN_COLUMN,
    ATTENDANCE_COLUMN, PASSED_COLUMN, REMARK_COLUMN,
)


class RecordParseStateError(ValueError):
    """解析前置条件不满足（行不存在/无签到附件/域未接入/附件非图片）。"""


# ═══════════════════════════ 明细行构造（纯函数） ═══════════════════════════


def build_remark_line(output: TrainingRecordParseOutput, *, today: str) -> str:
    """解析结果 → 备注明细行（§6.3：AI解析(confidence=…) 前缀）。"""
    parts: list[str] = []
    if output.attendance_count is not None:
        parts.append(f"实到 {output.attendance_count} 人")
    if output.passed_count is not None:
        parts.append(f"考核合格 {output.passed_count} 人")
    if output.unrecognized:
        parts.append(
            f"辨认不清 {len(output.unrecognized)} 名：{'、'.join(output.unrecognized)}"
        )
    if output.notes:
        parts.append(output.notes)
    detail = "；".join(parts)
    head = f"AI解析(confidence={output.confidence},{output.doc_type},{today})"
    return f"{head}：{detail}" if detail else head


def build_writeback_fields(
    output: TrainingRecordParseOutput,
    *,
    remark: str | None,
    today: str,
) -> dict[str, Any]:
    """解析结果 → 回填 fields（§6.3 分级口径；备注=既有+明细行追加）。"""
    fields: dict[str, Any] = {}
    if output.confidence == CONFIDENCE_HIGH and output.doc_type != DOC_UNKNOWN:
        if output.attendance_count is not None:
            fields[ATTENDANCE_COLUMN] = str(output.attendance_count)
        if output.passed_count is not None:
            fields[PASSED_COLUMN] = str(output.passed_count)
    line = build_remark_line(output, today=today)
    base = (remark or "").rstrip()
    fields[REMARK_COLUMN] = f"{base}\n{line}" if base else line
    return fields


# ═══════════════════════════ 解析编排 ═══════════════════════════


async def parse_training_record(
    *,
    record_id: str,
    opener: Opener | None = None,
    ai_service: Any = None,
) -> dict[str, Any]:
    """单行解析：读行 → 下载签到表首个附件 → vision 解析 → 分级回填。"""
    open_client = opener or bd_reader.resolve_client
    try:
        client = open_client("training_behavior", "training")
    except Exception as exc:
        raise RecordParseStateError(f"培训台账未接入: {exc}") from exc
    records = await client.list_all_records(
        field_names=list(_READ_FIELDS), strict=True
    )
    row = next(
        (r for r in records if str(r.get("record_id") or "") == record_id), None
    )
    if row is None:
        raise RecordParseStateError(f"培训行不存在: {record_id}")
    fields = row.get("fields") or {}

    attachments = bd_fields.attachments(fields, SIGN_COLUMN)
    if not attachments:
        raise RecordParseStateError(f"该行「{SIGN_COLUMN}」附件列为空: {record_id}")
    attachment = attachments[0]
    file_token = str(attachment.get("file_token") or "")
    file_name = str(attachment.get("name") or "attachment")
    if not file_token:
        raise RecordParseStateError(f"签到表附件缺 file_token: {record_id}")

    from app.modules.safety.vision.constants import IMAGE_MIME_MAP
    from app.modules.safety.vision.utils import encode_image_for_vision

    mime = IMAGE_MIME_MAP.get(os.path.splitext(file_name)[1].lower())
    if mime is None:
        raise RecordParseStateError(
            f"签到表附件非图片（{file_name}），当前仅支持照片解析: {record_id}"
        )
    # 一次性查列 id：用私有 cache 而非进程级缓存（手动 API 单次调用，
    # 进程缓存会拿假 table_id 的陈旧值）
    field_id = await resolve_field_id(client, SIGN_COLUMN, cache={})
    if not field_id:
        raise RecordParseStateError(f"签到表列 field_id 解析失败: {record_id}")
    raw = await client.download_bitable_attachment(
        file_token=file_token, record_id=record_id, field_id=field_id,
    )
    if not raw:
        raise RecordParseStateError(
            f"签到表附件下载失败（token={file_token}）: {record_id}"
        )
    data_uri = encode_image_for_vision(raw, mime, file_name)
    if data_uri is None:
        raise RecordParseStateError(
            f"签到表图片无效或损坏（{file_name}）: {record_id}"
        )

    if ai_service is None:
        from app.modules.safety.service.config import create_ai_service

        ai_service = create_ai_service("vision")
    plugin = TrainingRecordParsingPlugin(ai_service)
    output = await plugin.generate(TrainingRecordParseInput(
        training_name=bd_fields.text(fields, "培训名称") or "",
        expected_count=bd_fields.text(fields, "应到人数") or "",
        assessment=bd_fields.select(fields, "考核方式") or "",
        image_data_uri=data_uri,
    ))

    today = bj_today().isoformat()
    writeback = build_writeback_fields(
        output, remark=bd_fields.text(fields, REMARK_COLUMN), today=today
    )
    await client.update_record(record_id=record_id, fields=writeback)
    logger.info(
        "签到成绩解析回填：record=%s doc_type=%s confidence=%s 数字列=%s",
        record_id, output.doc_type, output.confidence,
        [k for k in (ATTENDANCE_COLUMN, PASSED_COLUMN) if k in writeback],
    )
    return {
        "record_id": record_id,
        "parse": output.model_dump(),
        "writeback_keys": list(writeback.keys()),
    }


__all__ = [
    "ATTENDANCE_COLUMN",
    "PASSED_COLUMN",
    "REMARK_COLUMN",
    "SIGN_COLUMN",
    "RecordParseStateError",
    "TrainingRecordParsingError",
    "build_remark_line",
    "build_writeback_fields",
    "parse_training_record",
]
