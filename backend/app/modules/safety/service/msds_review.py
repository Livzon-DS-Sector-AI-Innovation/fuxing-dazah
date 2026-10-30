"""MSDS 错别字审核 + 修订同步引擎（PDF 追平字段，2026-10-30 用户需求）。

两条机制：

1. 错别字审核：写回管线/修订重生成前，AI 校对 28 个内容字段的中文文本，
   疑似错别字写入台账表「错别字审核」(单选) +「错别字明细」(文本) 供人工
   复核。AI 只标记不修改——化学品术语误改风险高，裁决权在人；人工在台账
   表修正字段后由机制 2 追平 PDF，形成「AI 标记 → 人工修订 → PDF 同步 →
   重新校对」闭环。

2. 修订同步：台账表 record_edited 事件 → 当前内容字段 hash 与 PDF 生成时
   hash（msds_documents.pdf_content_hash）比对 → 不一致才重生成标准 PDF 并
   替换「MSDS附件」，同时追加「修订记录」行。防环三层：
   - hash 相同 → PDF 已追平，跳过（at-least-once 重推幂等）；
   - Redis 自写标记 msds_self_write_{record_id}（写回管线/修订自身写 Bitable
     前落标记，事件回环时标记==当前 hash → 跳过并补齐 PG hash）；
   - 审核/附件/日期字段变化不影响内容 hash，不触发重生成。

hash 归一化：比对剥离全部空白（\s+）——Bitable 富文本/换行形态差异不扰动
判定；纯空白级修改不值得替换附件，属预期口径。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.core.database import async_session_factory
from app.core.redis import redis_client
from app.modules.safety.bitable_config.store import store
from app.modules.safety.feishu.msds_bitable_handler import BITABLE_TO_MODEL
from app.modules.safety.models import MsdsDocument

logger = logging.getLogger(__name__)

# ── Bitable 审核字段名（setup_msds_review_fields.py 幂等建列）──
FIELD_TYPO_STATUS = "错别字审核"
FIELD_TYPO_DETAIL = "错别字明细"
FIELD_REVISION_LOG = "修订记录"

TYPO_STATUS_UNREVIEWED = "未审核"
TYPO_STATUS_CLEAN = "无错别字"
TYPO_STATUS_SUSPECT = "疑似错别字"
TYPO_STATUS_OPTIONS = (TYPO_STATUS_UNREVIEWED, TYPO_STATUS_CLEAN, TYPO_STATUS_SUSPECT)

# 修订记录最多保留行数（追加裁剪，防无限增长撑爆单元格）
REVISION_LOG_MAX_LINES = 20

# 自写标记：value=本次写入的内容 hash，TTL 秒
_SELF_WRITE_KEY = "msds_self_write_{}"
_SELF_WRITE_TTL = 600

# 参与内容比对/PDF 生成的字段（中文列名 → entry key；新旧外观列名共存）。
# 排除面（写它们绝不触发 PDF 重生成，否则同步自身写回会死循环）：
# source_date/msds_attachment（非内容）、typo_review_status/typo_review_detail/
# revision_log（审核与修订机制自身字段）。
_EXCLUDED_MODEL_COLS = frozenset({
    "source_date", "msds_attachment",
    "typo_review_status", "typo_review_detail", "revision_log",
    "label_elements", "hazard_class",  # 台账表无列/非内容（镜像专属）
})
_CONTENT_COLUMNS: tuple[tuple[str, str], ...] = tuple(
    (cn, en) for cn, en in BITABLE_TO_MODEL.items()
    if en not in _EXCLUDED_MODEL_COLS
)
# entry key → 展示用中文列名（新名优先；外观列取「外观与性状」）
_FIELD_LABELS: dict[str, str] = {}
for _cn, _en in _CONTENT_COLUMNS:
    _FIELD_LABELS.setdefault(_en, _cn)

CONTENT_FIELD_KEYS: tuple[str, ...] = tuple(sorted(_FIELD_LABELS))


def _norm_text(value: Any) -> str:
    """hash 归一化：剥离全部空白（换行/空格形态差异不扰动判定）。"""
    if value is None:
        return ""
    return re.sub(r"\s+", "", str(value))


def msds_content_hash(entry: Mapping[str, Any]) -> str:
    """28 内容字段 → 稳定 sha256（字段按 key 排序，值剥空白）。"""
    payload = "|".join(f"{k}={_norm_text(entry.get(k))}" for k in CONTENT_FIELD_KEYS)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def entry_from_bitable_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    """台账表记录 fields → PDF entry（中文列名反查；外观列新旧名兼容）。

    get_record 返回纯字符串形态；search 富文本段（[{text,...}]）兜底拼接。
    """
    entry: dict[str, Any] = {}
    for cn, en in _CONTENT_COLUMNS:
        raw = fields.get(cn)
        if isinstance(raw, list):  # 富文本段兜底
            raw = "".join(seg.get("text", "") for seg in raw if isinstance(seg, dict))
        if raw is None:
            continue
        s = str(raw)
        if s.strip():
            entry[en] = s
    return entry


def decide_pdf_sync(
    current_hash: str,
    pdf_hash: str | None,
    marker_hash: str | None,
    *,
    force: bool = False,
) -> str:
    """纯判定：regenerate / skip_up_to_date / skip_self_write。

    - force 恒 regenerate（人工触发重建，如模板错别字修复后追平存量附件）；
    - pdf_hash==current → PDF 已与字段一致；
    - marker==current → 内容是平台自己刚写入（写回管线/修订回写），PDF 即
      由该内容生成，仅需补齐 PG hash。
    """
    if force:
        return "regenerate"
    if pdf_hash and pdf_hash == current_hash:
        return "skip_up_to_date"
    if marker_hash and marker_hash == current_hash:
        return "skip_self_write"
    return "regenerate"


async def get_self_write_marker(record_id: str) -> str | None:
    try:
        val = await redis_client.get(_SELF_WRITE_KEY.format(record_id))
        return val.decode() if isinstance(val, bytes) else (val if val else None)
    except Exception:
        return None


async def set_self_write_marker(record_id: str, content_hash: str) -> None:
    """写回管线/修订自身写 Bitable 前调用（失败仅告警，hash 兜底仍防环）。"""
    try:
        await redis_client.set(
            _SELF_WRITE_KEY.format(record_id), content_hash, ex=_SELF_WRITE_TTL
        )
    except Exception:
        logger.warning("MSDS 自写标记写入失败(非致命): record_id=%s", record_id)


# ═══════════════════════════════════════════════════════════════════
# 错别字 AI 校对
# ═══════════════════════════════════════════════════════════════════

MSDS_PROOFREAD_SYSTEM_PROMPT = """你是中文化学品安全技术说明书（MSDS）校对专家。
对给定字段文本逐字段检查错别字：同音字、形近字、字序颠倒、多字漏字。

判定边界（严格遵守）：
1. 只标记疑似错别字，不改写、不润色、不合并段落；每处只给最小修正建议。
2. 化学品专业术语是正确写法，不是错别字：如「性状」「蒸气」「拮抗」「瘙
   痒」「灼伤」「发绀」「肺水肿」「苯」「烷/烯/炔」「酯/腈/肼」等。
3. 单位符号、CAS 号、化学式、数字、标点全半角差异不算错别字。
4. 「无资料」「/」「无意义」等占位原样保留，不算错别字。
5. 不确定时不标记（宁漏勿误）。

输出 JSON：
{"issues": [{"field": "字段名(原样返回)", "original": "原文错误片段(≤20字)", "suggestion": "修正后片段", "reason": "错别字类型,如 形近字/字序颠倒"}]}
无错别字输出 {"issues": []}。禁止输出任何其他文字。"""


def _clip(text: Any, limit: int = 60) -> str:
    s = str(text or "").strip()
    return s[:limit]


def _validate_issues(raw_issues: Iterable[Any]) -> list[dict[str, str]]:
    """过滤/裁剪 AI 输出：字段名须在已知清单，片段非空，条数≤30。"""
    known_fields = set(_FIELD_LABELS.values()) | set(_FIELD_LABELS.keys())
    valid: list[dict[str, str]] = []
    for item in raw_issues:
        if not isinstance(item, dict):
            continue
        field = _clip(item.get("field"), 40)
        original = _clip(item.get("original"), 40)
        suggestion = _clip(item.get("suggestion"), 40)
        if not field or field not in known_fields:
            continue
        if not original or not suggestion or original == suggestion:
            continue
        valid.append({
            "field": field,
            "original": original,
            "suggestion": suggestion,
            "reason": _clip(item.get("reason"), 30) or "疑似错别字",
        })
        if len(valid) >= 30:
            break
    return valid


async def proofread_entry(entry: Mapping[str, Any]) -> list[dict[str, str]]:
    """AI 校对单条 MSDS entry 的 28 字段文本，返回疑似错别字列表。

    全空 entry 不发起调用（返回 []）；AI 异常上抛由调用方决定降级。
    """
    payload = {
        label: str(entry.get(key) or "")
        for key, label in _FIELD_LABELS.items()
        if entry.get(key)
    }
    if not payload:
        return []

    from app.modules.safety.ai_audit import ai_audit_scope
    from app.modules.safety.service.config import create_ai_service

    with ai_audit_scope(
        scenario="msds_proofread",
        channel="system",
        resource_type="msds_document",
    ):
        ai = create_ai_service("text")
        try:
            result = await ai.chat_parsed(
                messages=[
                    {"role": "system", "content": MSDS_PROOFREAD_SYSTEM_PROMPT},
                    # 变量数据放 user 末尾（前缀缓存友好，对齐提取链路）
                    {"role": "user", "content": "待校对字段如下：\n" + json.dumps(payload, ensure_ascii=False)},
                ],
                expected_keys=["issues"],
                temperature=0.1,
            )
        finally:
            await ai.close()
    raw = result.get("issues")
    if not isinstance(raw, list):
        return []
    return _validate_issues(raw)


def typo_review_fields(issues: list[dict[str, str]]) -> dict[str, str]:
    """校对结果 → 台账表写字段（单选状态 + 明细文本）。"""
    return {
        FIELD_TYPO_STATUS: TYPO_STATUS_SUSPECT if issues else TYPO_STATUS_CLEAN,
        FIELD_TYPO_DETAIL: format_typo_detail(issues),
    }


def format_typo_detail(issues: list[dict[str, str]]) -> str:
    """明细行：「急救措施」：『迅术』→『迅速』（形近字）。空返回空串。"""
    lines = [
        f"「{i['field']}」：『{i['original']}』→『{i['suggestion']}』（{i['reason']}）"
        for i in issues
    ]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# 修订同步（record_edited → PDF 追平）
# ═══════════════════════════════════════════════════════════════════


def _bj_now_str() -> str:
    return datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M")


def append_revision_log(existing: Any, line: str) -> str:
    """追加修订记录行，裁剪保留最近 REVISION_LOG_MAX_LINES 行。"""
    if isinstance(existing, list):  # 富文本段兜底
        existing = "".join(seg.get("text", "") for seg in existing if isinstance(seg, dict))
    lines = [ln.strip() for ln in str(existing or "").splitlines() if ln.strip()]
    lines.append(f"{_bj_now_str()} {line}")
    return "\n".join(lines[-REVISION_LOG_MAX_LINES:])


def revision_pdf_filename(entry: Mapping[str, Any], record_id: str) -> str:
    """修订版 pdf 文件名（sanitized，rev 时间戳区别首版）。"""
    name = (entry.get("name") or "unknown").replace("/", "_").replace("\\", "_")
    cas = (entry.get("cas_no") or "no_cas").replace("/", "_").replace("\\", "_")
    stamp = datetime.now(UTC).astimezone().strftime("%Y%m%d%H%M")
    return f"{name}_{cas}_rev_{record_id[-6:].lower()}_{stamp}.pdf"


async def sync_pdf_revision(record_id: str, *, force: bool = False) -> dict[str, Any]:
    """台账记录修订同步：内容 hash 变化 → 重生成标准 PDF 替换附件。

    由 msds_bitable_handler._handle_changed（record_edited）与人工触发端点
    调用；force=True 跳过 hash 判定直接重建（模板修复后追平存量附件用）。
    返回 {"status": skip_up_to_date/skip_self_write/skip_no_content/
    skip_not_found/failed_not_configured/regenerated/failed_upload, ...}。
    """
    from app.modules.safety.attachment_store import cleanup_temp, store_bytes
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient
    from app.modules.safety.feishu.msds_pdf import build_standard_msds_pdf
    import tempfile

    conn = store.get_connection("msds", "registry")
    if conn is None or conn.status == "disabled":
        return {"status": "failed_not_configured", "record_id": record_id}
    client = SafetyBitableClient(app_token=conn.app_token, table_id=conn.table_id)

    fields = await client.get_record(record_id=record_id)
    if not fields:
        return {"status": "skip_not_found", "record_id": record_id}
    entry = entry_from_bitable_fields(fields)
    if not entry:
        return {"status": "skip_no_content", "record_id": record_id}
    current_hash = msds_content_hash(entry)

    # PG 镜像行：pdf hash + label_elements 补充（台账表无该列）
    async with async_session_factory() as session:
        row = await session.scalar(
            select(MsdsDocument).where(
                MsdsDocument.feishu_record_id == record_id,
                MsdsDocument.is_deleted == False,  # noqa: E712
            )
        )
    pdf_hash = row.pdf_content_hash if row else None
    decision = decide_pdf_sync(
        current_hash, pdf_hash,
        await get_self_write_marker(record_id),
        force=force,
    )
    if decision == "skip_up_to_date":
        return {"status": decision, "record_id": record_id}
    if decision == "skip_self_write":
        # 平台自写回环：补齐 PG hash（写回管线 UPSERT 竞态兜底）
        if row and row.pdf_content_hash != current_hash:
            async with async_session_factory() as session:
                obj = await session.scalar(
                    select(MsdsDocument).where(MsdsDocument.id == row.id)
                )
                if obj:
                    obj.pdf_content_hash = current_hash
                    await session.commit()
        return {"status": decision, "record_id": record_id}

    # ① 重生成标准 PDF（label_elements 从镜像补，台账表无此列）
    if row and row.label_elements:
        entry["label_elements"] = row.label_elements
    filename = revision_pdf_filename(entry, record_id)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp_path = tmp.name
    try:
        build_standard_msds_pdf(entry, tmp_path)
        with open(tmp_path, "rb") as f:
            pdf_bytes = f.read()
    finally:
        cleanup_temp(tmp_path)
    std_pdf_path = store_bytes(
        "msds", filename, pdf_bytes, content_type="application/pdf",
    )

    # ② 上传飞书 Drive
    upload = await client.upload_media(std_pdf_path, filename)
    if not upload:
        logger.error("MSDS 修订 PDF 上传失败: record_id=%s file=%s", record_id, filename)
        return {"status": "failed_upload", "record_id": record_id}

    # ③ 写回：替换附件 + 追加修订记录（+修订后重跑错别字校对）
    revision_line = (
        "标准 PDF 已重建（人工触发，内容未变）" if force
        else "内容字段已修改，标准 PDF 已同步重新生成"
    )
    update_fields: dict[str, Any] = {
        "MSDS附件": [upload],
        FIELD_REVISION_LOG: append_revision_log(fields.get(FIELD_REVISION_LOG), revision_line),
    }
    try:
        review = typo_review_fields(await proofread_entry(entry))
        update_fields.update(review)
        typo_status = review[FIELD_TYPO_STATUS]
        typo_detail = review[FIELD_TYPO_DETAIL] or None
    except Exception:
        logger.exception("MSDS 修订后错别字校对失败(附件替换不受影响): %s", record_id)
        typo_status = None
        typo_detail = None

    # 自写标记先落（本次 update 触发的 edited 回环靠它跳过）
    await set_self_write_marker(record_id, current_hash)
    ok = await client.update_record(record_id=record_id, fields=update_fields)
    if not ok:
        return {"status": "failed_update", "record_id": record_id}

    # ④ PG 镜像追平：hash/附件/审核字段
    async with async_session_factory() as session:
        obj = await session.scalar(
            select(MsdsDocument).where(
                MsdsDocument.feishu_record_id == record_id,
                MsdsDocument.is_deleted == False,  # noqa: E712
            )
        )
        if obj:
            obj.pdf_content_hash = current_hash
            obj.msds_attachment = [upload]
            obj.msds_attachment_path = std_pdf_path
            if typo_status:
                obj.typo_review_status = typo_status
                obj.typo_review_detail = typo_detail
            await session.commit()

    logger.info(
        "MSDS 修订同步完成: record_id=%s file=%s typo=%s",
        record_id, filename, typo_status,
    )
    return {"status": "regenerated", "record_id": record_id, "file": filename}


async def run_proofread_for_record(record_id: str) -> dict[str, Any]:
    """对单条台账记录执行错别字校对并写回（API 手动触发/存量补跑用）。

    返回 {"status": ok/skip_empty/failed, "issues": [...]}。
    """
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient

    conn = store.get_connection("msds", "registry")
    if conn is None or conn.status == "disabled":
        return {"status": "failed", "reason": "not_configured"}
    client = SafetyBitableClient(app_token=conn.app_token, table_id=conn.table_id)

    fields = await client.get_record(record_id=record_id)
    if not fields:
        return {"status": "skip_not_found", "record_id": record_id}
    entry = entry_from_bitable_fields(fields)
    if not entry:
        return {"status": "skip_no_content", "record_id": record_id}

    issues = await proofread_entry(entry)
    review = typo_review_fields(issues)
    # hash 标记防环：审核字段写入不触发 PDF 重生成（hash 本就不变，双保险）
    await set_self_write_marker(record_id, msds_content_hash(entry))
    ok = await client.update_record(record_id=record_id, fields=review)
    if not ok:
        return {"status": "failed_update", "record_id": record_id, "issues": issues}

    async with async_session_factory() as session:
        obj = await session.scalar(
            select(MsdsDocument).where(
                MsdsDocument.feishu_record_id == record_id,
                MsdsDocument.is_deleted == False,  # noqa: E712
            )
        )
        if obj:
            obj.typo_review_status = review[FIELD_TYPO_STATUS]
            obj.typo_review_detail = review[FIELD_TYPO_DETAIL] or None
            await session.commit()

    return {"status": "ok", "record_id": record_id, "issues": issues}
