"""COA 生成留档与验证。

留档：每次生成，把送出去的字节原样存下，连同摘要和「当时写了什么」。
送出去的就是存下来的——存不下来就不出文件。

验证：一份 docx 丢进来，纯代码对着留档比对，不经过模型（导入解析走 AI，
模型会静默改写数值，举证不能依赖它）。结论四档：
- identical      与留档字节一致：就是系统出的那份
- content_match  字节不同但文字全同：系统出的，之后被 Word 重新保存过
- altered        有位置对不上：文件在生成后被改过，或根本不是系统出的
- no_record      系统没有这个批号的生成记录

哈希只能证实、不能证伪：Word 打开再保存就会改字节，所以字节不同时往下
比文字。文字比对忽略空白，换行/制表符算内容（被抹掉也算改动）。
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import html
import io
import re
import uuid
import zipfile
from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundException
from app.modules.qa import file_service
from app.modules.qa.models import CoaRenderRecord, CoaReport, CoaStandard
from app.modules.qa.repository import coa as repo
from app.modules.qa.service.coa.report_log import (
    COA_LOG_ACTION_RENDERED,
    record_report_log,
)
from app.modules.qa.service.coa.template_address import (
    Slot,
    TemplateDoc,
    TemplateDocError,
)
from app.platform.identity.models import User
from app.platform.identity.public_api import get_user_names

VERDICT_IDENTICAL = "identical"
VERDICT_CONTENT_MATCH = "content_match"
VERDICT_ALTERED = "altered"
VERDICT_NO_RECORD = "no_record"

# 比对范围：bytes=只比了哈希；full_text=对全部文字位；written_only=留档原件
# 已不在存储里，只按地址比了系统写入的位置
SCOPE_BYTES = "bytes"
SCOPE_FULL_TEXT = "full_text"
SCOPE_WRITTEN_ONLY = "written_only"

_WORD_PART_RE = re.compile(r"word/(?:document|header\d*|footer\d*)\.xml")
_TEXT_RE = re.compile(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>")


# ─────────────────────── 留档 ───────────────────────


def _positions_text(written: dict[str, Any]) -> str:
    return (
        f"{written.get('positions', 0)} 个"
        f"（批次信息 {written.get('batch', 0)} 项 · 检测结果 {written.get('items', 0)} 项）"
    )


async def archive_render(
    db: AsyncSession,
    *,
    report: CoaReport,
    standard: CoaStandard,
    data: bytes,
    filename: str,
    check: dict[str, Any],
    user: User | None,
) -> CoaRenderRecord:
    """存下这次生成的原件和值快照，并记一条操作日志；存不下来就抛错，不出文件。"""
    try:
        stored = await asyncio.to_thread(file_service.store_file, filename, None, data)
    except Exception as exc:  # noqa: BLE001 — 本地磁盘/对象存储的异常口径不一，统一成一个业务提示
        raise AppException(
            status_code=500,
            message="COA 留档保存失败，这次没有出文件；请重试或联系管理员",
        ) from exc
    actor = user.id if user is not None else None
    record = await repo.add_render_record(
        db,
        CoaRenderRecord(
            report_id=report.id,
            product_id=report.product_id,
            standard_id=report.standard_id,
            standard_code=standard.code,
            batch_no=report.batch_no,
            filename=filename,
            file_key=stored.key,
            file_sha256=stored.sha256,
            template_sha256=standard.template_sha256,
            values_snapshot={"fields": check.get("writes") or []},
            created_by=actor,
            updated_by=actor,
        ),
    )
    product = await repo.get_product(db, report.product_id)
    await record_report_log(
        db,
        action=COA_LOG_ACTION_RENDERED,
        report=report,
        user=user,
        product_name=product.name if product else None,
        standard_code=standard.code,
        new_cells={
            "COA 文件": {"值": filename, "备注": f"SHA-256 {record.file_sha256}"},
            "写入位置": {"值": _positions_text(check.get("written") or {})},
        },
        record_id=str(record.id),
        file_sha256=record.file_sha256,
    )
    return record


async def get_render_record_or_404(
    db: AsyncSession, record_id: uuid.UUID
) -> CoaRenderRecord:
    record = await repo.get_render_record(db, record_id)
    if record is None:
        raise NotFoundException("COA 生成留档")
    return record


def read_render_file(record: CoaRenderRecord) -> bytes | None:
    """留档原件的字节；文件已不在存储里返回 None。"""
    content = file_service.read_file(record.file_key)
    return content[0] if content else None


async def list_renders(
    db: AsyncSession,
    *,
    product_id: uuid.UUID | None = None,
    report_id: uuid.UUID | None = None,
    batch_no: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    rows, total = await repo.list_render_records(
        db,
        product_id=product_id,
        report_id=report_id,
        batch_no=batch_no,
        limit=page_size,
        offset=(max(page, 1) - 1) * page_size,
    )
    return await _record_dicts(db, rows), total


async def _record_dicts(
    db: AsyncSession, rows: Sequence[CoaRenderRecord]
) -> list[dict[str, Any]]:
    """留档行 → 响应：补操作人姓名、产品名、登记是否已作废。"""
    if not rows:
        return []
    names = await get_user_names(db, [row.created_by for row in rows])
    product_names: dict[uuid.UUID, str | None] = {}
    for product_id in {row.product_id for row in rows}:
        product = await repo.get_product(db, product_id)
        product_names[product_id] = product.name if product else None
    voided = await repo.list_report_states(db, list({row.report_id for row in rows}))
    return [
        {
            "id": str(row.id),
            "report_id": str(row.report_id),
            "product_id": str(row.product_id),
            "product_name": product_names.get(row.product_id),
            "standard_id": str(row.standard_id),
            "standard_code": row.standard_code,
            "batch_no": row.batch_no,
            "filename": row.filename,
            "file_sha256": row.file_sha256,
            "template_sha256": row.template_sha256,
            "positions": _positions(row),
            "created_at": row.created_at,
            "actor_id": row.created_by,
            "actor_name": names.get(row.created_by) if row.created_by else None,
            "report_voided": voided.get(row.report_id),
        }
        for row in rows
    ]


def _positions(record: CoaRenderRecord) -> int:
    return sum(
        len(entry.get("slots") or [])
        for entry in (record.values_snapshot or {}).get("fields", [])
    )


# ─────────────────────── 验证：文字比对 ───────────────────────


def _norm(text: str | None) -> str:
    """比对口径：忽略空白；换行/制表符记成可见符号——值里的换行被抹掉也算改动。"""
    return "".join((text or "").replace("\n", "⏎").replace("\t", "⇥").split())


def _matches(mode: str, expected: str, actual: str | None) -> bool:
    """系统写入的一段文字在上传文件的这一位里是否原样还在。"""
    want, have = _norm(expected), _norm(actual)
    if not want:
        return not have  # 被清空的位置：这一位必须真的是空的
    return want in have if mode == "inplace" else want == have


def _slot_rows(fields: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """快照里的 (字段, 数据位)，保持写入顺序。"""
    return [
        (entry, dict(slot))
        for entry in fields
        for slot in entry.get("slots") or []
    ]


def _slot_row(
    entry: dict[str, Any], slot: dict[str, Any], actual: str | None, status: str
) -> dict[str, Any]:
    return {
        "field": entry.get("field"),
        "label": entry.get("label"),
        "item": bool(entry.get("item")),
        "sid": str(slot.get("sid", "")),
        "mode": str(slot.get("mode") or "replace"),
        "expected": str(slot.get("text") or ""),
        "actual": actual,
        "status": status,
    }


def _split_slots(
    doc: TemplateDoc,
) -> tuple[list[Slot], dict[str, str], dict[str, str]]:
    """文字位分三块：正文（有先后）；页眉、页脚各自收成「出现过的文字」。

    页眉/页脚返回 {规整后的文字: 原文}。办公软件重新保存时会重排页眉页脚的
    部件：拆成首页/奇偶页、内容整体复制一份、多出空部件（LibreOffice 实测）。
    部件的编号和份数不是内容，所以页眉页脚不看位置，只看哪些文字出现过；
    空段落不算。
    """
    body: list[Slot] = []
    header: dict[str, str] = {}
    footer: dict[str, str] = {}
    for slot in doc.slots:
        text = _norm(slot.text)
        if slot.part == "document":
            body.append(slot)
        elif text:
            (header if slot.part == "header" else footer)[text] = slot.text
    return body, header, footer


def _counterparts(
    original: Sequence[Slot], uploaded: Sequence[Slot]
) -> tuple[list[int | None], list[bool]]:
    """正文文字位的序列对齐。

    返回 (原件每一位对到上传文件的哪一位, 上传文件的每一位是否对上了原件)。
    按先后顺序对齐而不是按地址硬对：对方删一行或加一个空段，后面的地址会
    整体错位，硬对会把没动过的位置全报成改动。
    """
    theirs = [_norm(slot.text) for slot in original]
    mine = [_norm(slot.text) for slot in uploaded]
    counterpart: list[int | None] = [None] * len(theirs)
    covered = [False] * len(mine)
    for tag, a1, a2, b1, b2 in difflib.SequenceMatcher(
        None, theirs, mine, autojunk=False
    ).get_opcodes():
        # 相等块整段对应；增删改块里一对一的部分按位对位，多出来的算新增/删除
        paired = a2 - a1 if tag == "equal" else min(a2 - a1, b2 - b1)
        for offset in range(paired):
            counterpart[a1 + offset] = b1 + offset
            covered[b1 + offset] = True
    return counterpart, covered


def _difference(
    where: str, sid: str, expected: str | None, actual: str | None, status: str
) -> dict[str, Any]:
    return {"where": where, "sid": sid, "expected": expected, "actual": actual, "status": status}


def _margin_differences(
    where: str, before: dict[str, str], after: dict[str, str]
) -> list[dict[str, Any]]:
    """页眉/页脚「出现过的文字」的差异；被改掉的那句和改后的那句尽量配成一对。

    只有一句不见、一句多出来时直接配成「改写」；多句时要有三分像才认，
    否则各记各的（结论不受影响，只是「改成」和「删了又加」的区别）。
    """

    def alike(left: str, right: str) -> float:
        return difflib.SequenceMatcher(None, left, right).ratio()

    gone = {key: before[key] for key in before.keys() - after.keys()}
    fresh = {key: after[key] for key in after.keys() - before.keys()}
    only_one_each = len(gone) == 1 and len(fresh) == 1
    out: list[dict[str, Any]] = []
    for key, text in gone.items():
        twin = max(fresh, key=lambda other: alike(key, other), default=None)
        if twin is not None and (only_one_each or alike(key, twin) >= 0.3):
            out.append(_difference(where, "", text, fresh.pop(twin), "differs"))
        else:
            out.append(_difference(where, "", text, None, "missing_position"))
    out.extend(_difference(where, "", None, text, "added") for text in fresh.values())
    return out


def _compare_with_original(
    original: TemplateDoc, uploaded: TemplateDoc, fields: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """对着留档原件比全部文字：系统写入的位置逐项列出，其余位置的差异另列。"""
    body, header, footer = _split_slots(original)
    mine, header_mine, footer_mine = _split_slots(uploaded)
    counterpart, covered = _counterparts(body, mine)
    index_of = {slot.sid: i for i, slot in enumerate(body)}
    written: set[int] = set()
    rows: list[dict[str, Any]] = []
    for entry, slot in _slot_rows(fields):
        sid = str(slot.get("sid", ""))
        mode = str(slot.get("mode") or "replace")
        expected = str(slot.get("text") or "")
        i = index_of.get(sid)
        if i is None and sid[:1] in ("H", "F"):
            # 写在页眉/页脚里的值：在对方的页眉/页脚文字里还得原样找得到
            pool = header_mine if sid[0] == "H" else footer_mine
            hit = next((text for text in pool.values() if _matches(mode, expected, text)), None)
            rows.append(_slot_row(entry, slot, hit, "match" if hit is not None else "differs"))
            continue
        j = counterpart[i] if i is not None else None
        actual = mine[j].text if j is not None else None
        if i is not None:
            written.add(i)
        if j is None:
            status = "missing_position"
        elif not _matches(mode, expected, actual):
            status = "differs"
        else:
            # 值还在，但同一段里的固定文字变了（标题行流水号夹在固定文字中间）
            intact = i is not None and _norm(body[i].text) == _norm(actual)
            status = "match" if intact else "context_differs"
        rows.append(_slot_row(entry, slot, actual, status))
    others: list[dict[str, Any]] = []
    for i, origin in enumerate(body):
        if i in written or not _norm(origin.text):
            continue
        j = counterpart[i]
        actual = mine[j].text if j is not None else None
        if j is None:
            others.append(_difference("正文", origin.sid, origin.text, None, "missing_position"))
        elif _norm(origin.text) != _norm(actual):
            others.append(_difference("正文", origin.sid, origin.text, actual, "differs"))
    for j, extra in enumerate(mine):
        if not covered[j] and _norm(extra.text):
            others.append(_difference("正文", extra.sid, None, extra.text, "added"))
    others.extend(_margin_differences("页眉", header, header_mine))
    others.extend(_margin_differences("页脚", footer, footer_mine))
    return rows, others


def _compare_by_address(
    uploaded: TemplateDoc, fields: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """留档原件已不在：退一步，只按地址看系统写入的位置。"""
    rows: list[dict[str, Any]] = []
    for entry, slot in _slot_rows(fields):
        resolved = uploaded.resolve(str(slot.get("sid", "")))
        actual = resolved.text if resolved is not None else None
        status = (
            "missing_position"
            if resolved is None
            else "match"
            if _matches(str(slot.get("mode") or "replace"), str(slot.get("text") or ""), actual)
            else "differs"
        )
        rows.append(_slot_row(entry, slot, actual, status))
    return rows


def _archived_doc(record: CoaRenderRecord) -> TemplateDoc | None:
    content = file_service.read_file(record.file_key)
    if not content:
        return None
    try:
        return TemplateDoc(content[0])
    except TemplateDocError:
        return None


def _counts(result: dict[str, Any]) -> dict[str, Any]:
    rows = result["slots"]
    result["compared"] = len(rows)
    result["differing"] = (
        sum(row["status"] in ("differs", "context_differs") for row in rows)
        + len(result["other_differences"])
    )
    result["unresolved"] = sum(row["status"] == "missing_position" for row in rows)
    return result


async def _compare_record(
    record: CoaRenderRecord, uploaded: TemplateDoc
) -> dict[str, Any] | None:
    """一条留档对上传文件的比对结果；快照是空的留档比不了。"""
    fields = (record.values_snapshot or {}).get("fields") or []
    if not _slot_rows(fields):
        return None
    original = await asyncio.to_thread(_archived_doc, record)
    if original is not None:
        rows, others = _compare_with_original(original, uploaded, fields)
        scope = SCOPE_FULL_TEXT
    else:
        rows, others, scope = _compare_by_address(uploaded, fields), [], SCOPE_WRITTEN_ONLY
    return _counts(
        {"scope": scope, "slots": rows, "other_differences": others}
    )


# ─────────────────────── 验证：入口 ───────────────────────


def _document_text(data: bytes) -> str:
    """正文 + 页眉页脚里的全部文字，不解析结构——只用来认批号。"""
    parts: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            if _WORD_PART_RE.fullmatch(name):
                xml = archive.read(name).decode("utf-8", "ignore")
                parts.extend(html.unescape(text) for text in _TEXT_RE.findall(xml))
    return "".join(parts)


async def _candidates(
    db: AsyncSession, data: bytes, report_id: uuid.UUID | None
) -> tuple[list[CoaRenderRecord], str | None, CoaReport | None]:
    """找要比对的留档：指定了报告就用它的；否则按文件里出现的批号认。"""
    if report_id is not None:
        records, _total = await repo.list_render_records(db, report_id=report_id)
        return records, "report_id", await repo.get_report(db, report_id)
    text = _norm(await asyncio.to_thread(_document_text, data))
    ids = await repo.list_render_ids_in_text(db, text)
    if not ids:
        return [], "batch_no", None
    records, _total = await repo.list_render_records(db, ids=ids)
    return records, "batch_no", None


def _open_upload(data: bytes, filename: str | None) -> TemplateDoc:
    """上传的待验文件：只收 docx，解析不了直接 400。"""
    name = filename or ""
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if extension != "docx":
        raise AppException(
            status_code=400,
            message="验证只支持 .docx 文件（PDF、旧版 .doc 请先用 Word 另存为 .docx）",
        )
    try:
        file_service.validate_file(name, None, data)
    except file_service.FileValidationError as exc:
        raise AppException(status_code=400, message=str(exc)) from exc
    try:
        return TemplateDoc(data)
    except TemplateDocError as exc:
        raise AppException(
            status_code=400,
            message="上传的文件无法读取（可能已加密或不是有效的 docx）",
        ) from exc


def _report_brief(report: CoaReport | None) -> dict[str, Any] | None:
    return {"id": str(report.id), "batch_no": report.batch_no} if report else None


async def verify_docx(
    db: AsyncSession,
    data: bytes,
    *,
    filename: str | None = None,
    report_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """一份 docx 是不是系统出的：对着生成留档比对，给出四档结论之一。"""
    result: dict[str, Any] = {
        "uploaded_sha256": hashlib.sha256(data).hexdigest(),
        "record": None,
        "other_records": [],
        "matched_by": None,
        "scope": None,
        "report": None,
        "slots": [],
        "other_differences": [],
        "compared": 0,
        "differing": 0,
        "unresolved": 0,
    }
    # 字节一致是最强的一档：不用解析，也没有歧义
    twins = await repo.list_render_records_by_sha256(db, result["uploaded_sha256"])
    if twins:
        twins_json = await _record_dicts(db, twins)
        return result | {
            "verdict": VERDICT_IDENTICAL,
            "record": twins_json[0],
            "other_records": twins_json[1:],
            "matched_by": "sha256",
            "scope": SCOPE_BYTES,
            "compared": twins_json[0]["positions"],
        }
    uploaded = await asyncio.to_thread(_open_upload, data, filename)
    candidates, matched_by, report = await _candidates(db, data, report_id)
    result["report"] = _report_brief(report)
    best: tuple[CoaRenderRecord, dict[str, Any]] | None = None
    for record in candidates:  # 新的在前；同一批号生成过多次时取对得上的那一次
        outcome = await _compare_record(record, uploaded)
        if outcome is not None and (
            best is None
            or outcome["differing"] + outcome["unresolved"]
            < best[1]["differing"] + best[1]["unresolved"]
        ):
            best = record, outcome
    if best is None:
        return result | {"verdict": VERDICT_NO_RECORD}
    record, outcome = best
    siblings, _total = await repo.list_render_records(db, report_id=record.report_id, limit=11)
    clean = not (outcome["differing"] or outcome["unresolved"])
    return result | outcome | {
        "verdict": VERDICT_CONTENT_MATCH if clean else VERDICT_ALTERED,
        "record": (await _record_dicts(db, [record]))[0],
        "other_records": await _record_dicts(
            db, [row for row in siblings if row.id != record.id][:10]
        ),
        "matched_by": matched_by,
    }
