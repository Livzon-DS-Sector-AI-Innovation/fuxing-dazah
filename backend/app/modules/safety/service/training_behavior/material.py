"""链2：讲义/试卷生成——读培训行 → 知识供给 → AI → docx → 挂附件列。

数据流（DESIGN 二期 §5.1）：POST generate-material → 读 training 行（主题/
类别/学时/对象）→ knowledge_md 文档选择器（§5.2，关键词+标题匹配，无进程
内 RAG）→ AI(training_material_generation)：讲义 temp 0.2 / 试卷 temp 0.1
→ docx 渲染（safety 侧独立渲染器）→ upload_media(parent_type=bitable_file)
拿媒体 token → 附件注册写「课件与试卷」列 → 行备注追加生成记录（幂等标记，
防重复生成同类型）。试卷命题材料=讲义要点卡+检索片段（讲义 JSON 只跑一次
AI，讲义 docx 与试卷共用）。

关键口径：
- 产物全部落附件列可审（讲师定稿前是草案），**不推送任何消息**；
- 幂等：备注含 `AI课件(日期)`/`AI试卷(日期)` 标记即拒绝同类型重生成；
- 知识选择器复用 knowledge/query_service._build_document_context 的成熟
  片段格式（[N] 文档标题 + 条款正文片段，--- 分隔），总量 ≤8000 字，
  匹配不到→空串（提示词已兜底「待补法规出处」）；
- 附件追加不覆盖：读行时带出既有附件，写回=既有 + 新增；
- 行读取走 list_all_records 全量拉取后按 record_id 定位（底座禁逐条读，
  手动 API 单次调用可接受整表一页）。

接缝（双接缝测试）：opener 替身注入 Bitable 客户端（fake 需实现
list_all_records/update_record/upload_media）；ai_service 注入假服务。
"""

from __future__ import annotations

import logging
import pathlib
import re
import tempfile
from collections import OrderedDict
from types import SimpleNamespace
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.ai_training_material import (
    ExamInput,
    ExamPlugin,
    LectureInput,
    LecturePlugin,
    TrainingMaterialError,
)
from app.modules.safety.ai_training_material.docx_renderer import (
    render_exam_docx,
    render_lecture_docx,
)
from app.modules.safety.models.knowledge import RegulationChunk
from app.modules.safety.service.bitable_direct import fields as bd_fields
from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.training_behavior.common import Opener, bj_today

logger = logging.getLogger(__name__)

ATTACHMENT_COLUMN = "课件与试卷"
REMARK_COLUMN = "备注"

LECTURE_MARKER = "AI课件"
EXAM_MARKER = "AI试卷"

_LECTURE_SUFFIX = "讲义要点卡"
_EXAM_SUFFIX = "试卷"
_READ_FIELDS = (
    "培训名称", "培训类别", "培训形式", "组织部门", "培训学时",
    ATTACHMENT_COLUMN, REMARK_COLUMN,
)

_KNOWLEDGE_MAX_CHARS = 8000
_KNOWLEDGE_CHUNK_LIMIT = 200
_EXAM_MATERIAL_MAX_CHARS = 8000

MATERIAL_TYPES = ("lecture", "exam", "both")


class MaterialStateError(ValueError):
    """生成前置条件不满足（行不存在/同类型已生成/域未接入）。"""


# ═══════════════════════════ 知识选择器（§5.2） ═══════════════════════════


def _topic_keywords(topic: str) -> list[str]:
    """主题 → 匹配关键词（≥2 字词；空主题回退整串）。"""
    words = [w for w in re.split(r"[\s·、，,。；;：:/\\()\[\]（）【】]+", topic or "") if len(w) >= 2]
    return words or ([topic] if topic else [])


async def select_knowledge_fragments(
    db: AsyncSession, *, topic: str, max_chars: int = _KNOWLEDGE_MAX_CHARS
) -> str:
    """按主题关键词+标题匹配筛文档，取正文片段拼 markdown（≤max_chars）。

    片段格式复用 knowledge/query_service._build_document_context（[N] 文档
    标题 + 条款正文片段，--- 分隔）；匹配不到返回空串（提示词兜底）。
    """
    from app.modules.safety.knowledge.query_service import _build_document_context

    keywords = _topic_keywords(topic)
    if not keywords:
        return ""
    stmt = (
        select(RegulationChunk)
        .where(or_(*[RegulationChunk.doc_title.ilike(f"%{k}%") for k in keywords]))
        .order_by(RegulationChunk.doc_title, RegulationChunk.chunk_index)
        .limit(_KNOWLEDGE_CHUNK_LIMIT)
    )
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return ""

    groups: OrderedDict[str, list[RegulationChunk]] = OrderedDict()
    for chunk in rows:
        groups.setdefault(chunk.doc_title, []).append(chunk)

    doc_groups: OrderedDict[str, dict] = OrderedDict()
    for title, chunks in groups.items():
        doc_groups[title] = {
            "title": title,
            "article_ids": [str(c.article_id) for c in chunks[:1]],
            "doc_category": chunks[0].doc_category,
            "chunks": [
                SimpleNamespace(
                    source_article=c.article_ref,
                    chunk_text=c.chunk_text,
                    article_id=str(c.article_id),
                )
                for c in chunks
            ],
        }
    markdown = _build_document_context(doc_groups)
    if len(markdown) <= max_chars:
        return markdown
    cut = markdown.rfind("\n---\n", 0, max_chars)
    if cut <= 0:
        cut = markdown.rfind("\n", 0, max_chars)
    return markdown[:cut if cut > 0 else max_chars]


# ═══════════════════════════ 培训行读写 ═══════════════════════════


async def _open_training(opener: Opener | None):
    open_client = opener or bd_reader.resolve_client
    return open_client("training_behavior", "training")


async def _find_training_row(
    client: Any, record_id: str
) -> dict[str, Any]:
    """全量拉取后按 record_id 定位行（底座禁逐条读）。"""
    records = await client.list_all_records(
        field_names=list(_READ_FIELDS), strict=True
    )
    for record in records:
        if str(record.get("record_id") or "") == record_id:
            return record
    raise MaterialStateError(f"培训行不存在: {record_id}")


def _has_marker(remark: str | None, marker: str) -> bool:
    return marker in (remark or "")


def _append_marker(remark: str | None, marker_line: str) -> str:
    base = (remark or "").rstrip()
    return f"{base}\n{marker_line}" if base else marker_line


def _attachment_entries(fields: dict[str, Any]) -> list[dict[str, str]]:
    """既有附件 → 写回用最小条目（file_token+name），丢弃 extra 等只读键。"""
    entries: list[dict[str, str]] = []
    for item in bd_fields.attachments(fields, ATTACHMENT_COLUMN):
        token = str(item.get("file_token") or "")
        if token:
            entries.append({
                "file_token": token,
                "name": str(item.get("name") or "附件"),
            })
    return entries


# ═══════════════════════════ 附件挂载链（§5.3） ═══════════════════════════


async def _upload_media(
    client: Any,
    *,
    docx_bytes: bytes,
    file_name: str,
) -> dict[str, str]:
    """temp 写盘 → upload_media 拿媒体 token（附件注册与备注标记由调用方
    在核末尾一次写回，避免多产物多次 update）。

    上传失败抛错（上层不写标记，可整体重试）；媒体已传但写回失败=孤儿媒体
    无害，幂等标记未落即可重试，接受此窗口。
    """
    safe_name = file_name.replace("/", "_").replace("\\", "_")
    tmp_path = pathlib.Path(tempfile.gettempdir()) / safe_name
    try:
        tmp_path.write_bytes(docx_bytes)
        upload = await client.upload_media(str(tmp_path.resolve()), safe_name)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass
    if not upload or not upload.get("file_token"):
        raise TrainingMaterialError(f"附件上传失败: {safe_name}")
    return {"file_token": str(upload["file_token"]), "name": safe_name}


# ═══════════════════════════ 生成编排（讲义/试卷/both 单入口核） ═══════════════════════════


async def generate_material(
    db: AsyncSession,
    *,
    record_id: str,
    material_type: str = "lecture",
    config: dict | None = None,
    opener: Opener | None = None,
    ai_service: Any = None,
) -> dict[str, Any]:
    """单入口编排：读行 → 知识 → 讲义 AI（一次）→ 试卷 AI（按需）→ docx
    渲染 → 逐个上传 → **一次写回**（附件=既有+新增，备注追加各类型标记）。

    material_type：lecture / exam / both。试卷命题材料=讲义要点卡 + 检索
    片段（讲义 JSON 不落库、只作命题材料与 docx 素材，故 both 只跑一次
    讲义 AI）。
    """
    if material_type not in MATERIAL_TYPES:
        raise MaterialStateError(
            f"非法 material_type: {material_type}（可选 {'/'.join(MATERIAL_TYPES)}）"
        )
    want_lecture = material_type in ("lecture", "both")
    want_exam = material_type in ("exam", "both")

    try:
        client = await _open_training(opener)
    except Exception as exc:
        raise MaterialStateError(f"培训台账未接入: {exc}") from exc
    row = await _find_training_row(client, record_id)
    fields = row.get("fields") or {}

    remark = bd_fields.text(fields, REMARK_COLUMN)
    blocked = [
        label for label, wanted, marker in (
            ("讲义", want_lecture, LECTURE_MARKER),
            ("试卷", want_exam, EXAM_MARKER),
        ) if wanted and _has_marker(remark, marker)
    ]
    if blocked:
        raise MaterialStateError(
            f"该行已生成过{'/'.join(blocked)}（标记在案），勿重复生成"
        )

    topic = bd_fields.text(fields, "培训名称") or "（未命名培训）"
    knowledge_md = ""
    try:
        knowledge_md = await select_knowledge_fragments(db, topic=topic)
    except Exception as exc:
        logger.warning("知识选择器读取失败，降级为无知识增强: %s", exc)

    if ai_service is None:
        from app.modules.safety.service.config import create_ai_service

        ai_service = create_ai_service("text")

    # 讲义 JSON：讲义 docx 与试卷命题材料共用（只调一次 AI）
    lecture_output = await LecturePlugin(ai_service).generate(LectureInput(
        topic=topic,
        category=bd_fields.select(fields, "培训类别"),
        hours=bd_fields.text(fields, "培训学时") or None,
        position=bd_fields.select(fields, "组织部门"),
        knowledge_md=knowledge_md,
    ))

    exam_output = None
    if want_exam:
        material_text = (
            "## 讲义要点\n"
            f"{lecture_output.card_markdown}\n\n"
            "## 检索片段（来源见 [N] 编号标注）\n"
            f"{knowledge_md or '（无检索片段）'}"
        )
        exam_output = await ExamPlugin(ai_service).generate(ExamInput(
            material=material_text[:_EXAM_MATERIAL_MAX_CHARS],
            config=config,
        ))

    today = bj_today().isoformat()
    info_line = (
        f"类别：{bd_fields.select(fields, '培训类别') or '—'}"
        f"｜学时：{bd_fields.text(fields, '培训学时') or '—'}"
        f"｜对象：{bd_fields.select(fields, '组织部门') or '—'}"
    )

    # 逐个上传 → 一次写回（附件合并 + 各类型标记一起追加）
    uploads: list[dict[str, str]] = []
    if want_lecture:
        file_name = f"{topic}-{_LECTURE_SUFFIX}-{today}.docx"
        docx_bytes = render_lecture_docx(lecture_output, info_line=info_line)
        uploads.append(await _upload_media(client, docx_bytes=docx_bytes,
                                           file_name=file_name))
    if want_exam:
        file_name = f"{topic}-{_EXAM_SUFFIX}-{today}.docx"
        docx_bytes = render_exam_docx(
            exam_output.questions, title=f"{topic}考核试卷",
        )
        uploads.append(await _upload_media(client, docx_bytes=docx_bytes,
                                           file_name=file_name))

    new_remark = remark or ""
    for marker in (LECTURE_MARKER, EXAM_MARKER):
        if (marker == LECTURE_MARKER and want_lecture) or (
            marker == EXAM_MARKER and want_exam
        ):
            new_remark = _append_marker(new_remark, f"{marker}({today})")
    entries = _attachment_entries(fields) + [
        {"file_token": u["file_token"], "name": u["name"]} for u in uploads
    ]
    await client.update_record(
        record_id=record_id,
        fields={ATTACHMENT_COLUMN: entries, REMARK_COLUMN: new_remark},
    )

    materials: list[dict[str, Any]] = []
    if want_lecture:
        materials.append({
            "material_type": "lecture",
            "file_name": uploads[0]["name"],
            "file_token": uploads[0]["file_token"],
            "generated_at": today,
            "title": lecture_output.title,
            "references": lecture_output.references,
            "knowledge_chars": len(knowledge_md),
        })
    if want_exam:
        materials.append({
            "material_type": "exam",
            "file_name": uploads[-1]["name"],
            "file_token": uploads[-1]["file_token"],
            "generated_at": today,
            "total_count": exam_output.total_count,
            "counts": {k: len(v) for k, v in exam_output.questions.items() if v},
            "knowledge_chars": len(knowledge_md),
        })
    logger.info(
        "课件生成挂载：record=%s 类型=%s 文件=%s 知识片段=%d字",
        record_id, material_type, [u["name"] for u in uploads], len(knowledge_md),
    )
    return {"record_id": record_id, "material_type": material_type,
            "materials": materials}


# ═══════════════════════════ 产物清单 ═══════════════════════════


def _marker_entries(remark: str | None) -> list[dict[str, str]]:
    """备注标记 → [{type, date}]（AI课件(YYYY-MM-DD) / AI试卷(...)）。"""
    entries: list[dict[str, str]] = []
    for match in re.finditer(
        rf"({LECTURE_MARKER}|{EXAM_MARKER})\((\d{{4}}-\d{{2}}-\d{{2}})\)", remark or ""
    ):
        kind = "lecture" if match.group(1) == LECTURE_MARKER else "exam"
        entries.append({"material_type": kind, "generated_at": match.group(2)})
    return entries


async def list_materials(
    *,
    record_id: str,
    opener: Opener | None = None,
) -> dict[str, Any]:
    """该行已生成产物清单：附件列（按文件名推类型）+ 备注生成标记。"""
    try:
        client = await _open_training(opener)
    except Exception as exc:
        raise MaterialStateError(f"培训台账未接入: {exc}") from exc
    row = await _find_training_row(client, record_id)
    fields = row.get("fields") or {}

    attachments: list[dict[str, Any]] = []
    for item in bd_fields.attachments(fields, ATTACHMENT_COLUMN):
        name = str(item.get("name") or "")
        kind = "exam" if "试卷" in name else ("lecture" if ("讲义" in name or "课件" in name) else None)
        attachments.append({
            "name": name,
            "file_token": str(item.get("file_token") or ""),
            "material_type": kind,
        })
    return {
        "record_id": record_id,
        "topic": bd_fields.text(fields, "培训名称"),
        "attachments": attachments,
        "generations": _marker_entries(bd_fields.text(fields, REMARK_COLUMN)),
    }


__all__ = [
    "ATTACHMENT_COLUMN",
    "EXAM_MARKER",
    "LECTURE_MARKER",
    "MATERIAL_TYPES",
    "MaterialStateError",
    "TrainingMaterialError",
    "generate_material",
    "list_materials",
    "select_knowledge_fragments",
]
