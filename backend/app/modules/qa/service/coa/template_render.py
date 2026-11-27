"""COA 回填：按已确认的模板标注，把出具登记的数据写进 docx。

纯代码、不经过模型——同一份登记数据每次生成结果都相同。

生成前的守卫（配置问题直接报错，数据问题拦下来并列清单）：
- 模板文件摘要与标注记录不一致 → 报错，必须重新核对标注
- 标注确认后字段配置变了（标注引用的字段被移除、新增字段还没标注位置、
  类型/单位变了）→ 报错，重新核对并保存标注之后才能生成
- 必填字段没有登记值 → 拦截并列出缺项：不许带着模板旧值或空白出报告

生成后的扫描：
- 原模板里的旧批号/旧流水号/旧日期还出现在输出里 → 有位置漏标了，拦截

出文件的同时留档（render_archive）：系统出过的每一份都有底稿。
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import file_storage
from app.core.exceptions import AppException
from app.modules.qa.models import CoaReport, CoaStandard
from app.modules.qa.repository import coa as repo
from app.modules.qa.service.coa.common import (
    compose_batch_info,
    get_report_or_404,
    get_standard_or_404,
    resolve_standard_fields,
)
from app.modules.qa.service.coa.render_archive import archive_render
from app.modules.qa.service.coa.template_address import (
    TemplateDoc,
    flat_text,
    squash,
)
from app.modules.qa.service.coa.template_bind import (
    BUILTIN_VERDICTS,
    FieldDef,
    binding_drift,
    build_fields,
    load_template_data,
    parse_template,
)
from app.platform.identity.models import User

COA_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_NUMBER_TEXT_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
# 「＜1」「≥0.25」这类值后面要跟单位；「未检出」「符合规定」后面不能跟
_NUMBER_LIKE_RE = re.compile(r"^[<＜>＞≤≥＝=]?\s*[+-]?\d")
_LATIN_RE = re.compile(r"[A-Za-z]")


# ─────────────────────── 格式化 ───────────────────────


def _format_number(raw: str, decimals: int) -> str:
    quantum = Decimal(1).scaleb(-decimals)
    return f"{Decimal(raw).quantize(quantum, rounding=ROUND_HALF_UP):.{decimals}f}"


def format_value(
    fmt: dict[str, Any], raw: str, verdicts: dict[str, str]
) -> tuple[str, bool]:
    """登记的值 → 写进模板的文字。返回 (文字, 是否缺英文对照)。

    数值规则遇到非数值（未检出、<0.1）按文字规则出并补单位后缀；文字规则在
    开了「补英文」且词典里有对照时补英文（符合规定→符合规定Conform）。
    比较符保持登记时的半角写法，不转全角。
    """
    text = raw.strip()
    suffix = str(fmt.get("suffix") or "")
    kind = fmt.get("kind")
    if kind == "date":
        try:
            return date.fromisoformat(text[:10]).strftime(str(fmt["pattern"])), False
        except (ValueError, KeyError, TypeError):
            return text, False
    if kind == "number" and _NUMBER_TEXT_RE.match(text):
        try:
            return _format_number(text, int(fmt.get("decimals", 2))) + suffix, False
        except (InvalidOperation, ValueError):
            pass
    missing_english = False
    if fmt.get("bilingual") and text and not _LATIN_RE.search(text):
        english = verdicts.get(text) or BUILTIN_VERDICTS.get(text)
        if english:
            text = f"{text}{fmt.get('joiner') or ''}{english}"
        else:
            missing_english = True
    tail = suffix if not text or _NUMBER_LIKE_RE.match(text) else ""
    return text + tail, missing_english


# ─────────────────────── 取数与守卫 ───────────────────────


@dataclass
class _Context:
    standard: CoaStandard
    report: CoaReport
    doc: TemplateDoc
    binding: dict[str, Any]
    fields: dict[str, FieldDef]
    values: dict[str, str]  # 字段键 → 登记的值（没填的不在里面）


async def _prepare(db: AsyncSession, report_id: uuid.UUID) -> _Context:
    report = await get_report_or_404(db, report_id)
    standard = await get_standard_or_404(db, report.standard_id)
    if not standard.template_key:
        raise AppException(
            status_code=400, message="该报告所属标准尚未上传 COA 模板，无法生成"
        )
    binding = standard.template_binding
    if not binding:
        raise AppException(
            status_code=409,
            message="该报告所属标准的模板还没有确认标注，请先在客户标准里完成「模板标注」",
        )
    data = await load_template_data(standard)
    if hashlib.sha256(data).hexdigest() != standard.template_sha256:
        raise AppException(status_code=409, message="模板文件已更换，请重新核对模板标注")
    doc = await asyncio.to_thread(parse_template, data)
    field_list = await build_fields(db, standard)
    fields = {f.key: f for f in field_list}
    drift = binding_drift(field_list, binding)
    if drift:
        # detail 用现成的条目文字（全局 http-client 会把对象形式的 detail 拼成 [object Object]）
        raise AppException(
            status_code=409,
            message="标注确认后字段配置有变化，请重新核对模板标注",
            detail=drift["lines"],
        )
    _verify_slots(doc, binding)
    effective, _custom = await resolve_standard_fields(db, standard.id)
    product = await repo.get_product(db, report.product_id)
    values: dict[str, str] = {
        f"batch:{key}": value
        for key, value in compose_batch_info(
            report, effective, product_name=product.name if product else None
        ).items()
    }
    for row in await repo.list_values_by_report(db, report.id):
        raw = (row.value_text or "").strip() or (
            str(row.value_num) if row.value_num is not None else ""
        )
        if raw:
            values[f"item:{row.item_id}"] = raw
    return _Context(standard, report, doc, binding, fields, values)


def _verify_slots(doc: TemplateDoc, binding: dict[str, Any]) -> None:
    """标注记录的每个数据位都要能在模板里按原样定位，否则说明标注与文件不是一对。"""
    broken: list[str] = []
    for entry in binding.get("fields", []):
        for slot in entry.get("slots", []):
            resolved = doc.resolve(str(slot.get("sid", "")))
            if resolved is None:
                broken.append(str(slot.get("sid", "")))
                continue
            flat = flat_text(resolved.element)
            sample = str(slot.get("sample") or "")
            intact = (
                squash(flat) == squash(sample)
                if slot.get("mode") == "replace"
                else bool(sample) and flat.count(sample) == 1
            )
            if not intact:
                broken.append(resolved.sid)
    if broken:
        raise AppException(
            status_code=409,
            message="模板标注与模板文件对不上，请重新核对模板标注",
            detail=broken,
        )


def _filename(ctx: _Context) -> str:
    raw = f"{ctx.report.batch_no}_{ctx.standard.code}_COA.docx"
    return file_storage.safe_filename(raw, "COA.docx")


def _build(ctx: _Context) -> tuple[bytes | None, dict[str, Any]]:
    """按标注把值写进模板；有任何拦截项就不出文件。"""
    verdicts = {**BUILTIN_VERDICTS, **(ctx.binding.get("verdicts") or {})}
    blocking: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    writes: list[tuple[str, str, str, str]] = []  # sid, mode, 被替换的原文, 新文字
    owner: dict[str, str] = {}
    valued: set[str] = set()
    positions = 0  # 写入登记值的数据位数（清空旧值的不算）
    written_fields: list[dict[str, Any]] = []  # 字段 → 登记值 → 各数据位写入的文字（留档用）
    for entry in ctx.binding.get("fields", []):
        key = str(entry.get("field"))
        field = ctx.fields[key]
        raw = ctx.values.get(key, "")
        entry_slots: list[dict[str, str]] = []
        if not raw.strip():
            if entry.get("required", True):
                blocking.append(
                    {
                        "kind": "missing",
                        "field": key,
                        "label": field.label_cn,
                        "item": field.kind == "item",
                    }
                )
                continue
            # 非必填字段没值：把模板里的旧值清掉，绝不带着旧样例出报告
            for slot in entry.get("slots", []):
                writes.append(
                    (str(slot["sid"]), str(slot.get("mode") or "replace"), str(slot.get("sample") or ""), "")
                )
                owner[str(slot["sid"])] = key
                entry_slots.append({"sid": str(slot["sid"]), "mode": str(slot.get("mode") or "replace"), "text": ""})
        else:
            valued.add(key)
            positions += len(entry.get("slots", []))
            for slot in entry.get("slots", []):
                text, missing_english = format_value(dict(slot.get("fmt") or {}), raw, verdicts)
                if missing_english:
                    warnings.append(
                        {"kind": "no_english", "field": key, "label": field.label_cn, "text": raw}
                    )
                sid = str(slot["sid"])
                mode = str(slot.get("mode") or "replace")
                writes.append((sid, mode, str(slot.get("sample") or ""), text))
                owner[sid] = key
                entry_slots.append({"sid": sid, "mode": mode, "text": text})
        written_fields.append(
            {
                "field": key,
                "label": field.label_cn,
                "item": field.kind == "item",
                "raw": raw,
                "slots": entry_slots,
            }
        )
    # 有登记值、但标注里没有位置的字段：确认标注时人已经认可它不写入模板，
    # 所以只提示不拦——出报告的人要知道这项内容不会出现在 COA 上
    unbound_items: list[str] = []
    unbound_batch: list[str] = []
    for key in ctx.values:
        if key in valued or key not in ctx.fields:
            continue
        (unbound_items if key.startswith("item:") else unbound_batch).append(
            ctx.fields[key].label_cn
        )
    if unbound_items:
        warnings.append(
            {"kind": "unbound_items", "count": len(unbound_items), "labels": unbound_items[:8]}
        )
    if unbound_batch:
        warnings.append(
            {"kind": "unbound_batch", "count": len(unbound_batch), "labels": unbound_batch[:8]}
        )
    check: dict[str, Any] = {
        "ok": not blocking,
        "filename": _filename(ctx),
        "template": ctx.standard.template_filename,
        # 这次会写进模板的内容，供出具页在下载前给用户看个概要
        "written": {
            "batch": sum(1 for key in valued if key.startswith("batch:")),
            "items": sum(1 for key in valued if key.startswith("item:")),
            "positions": positions,
        },
        "blocking": blocking,
        "warnings": warnings,
        # 逐字段写了什么：生成留档存的就是它（验证时逐位比对）
        "writes": written_fields,
    }
    if blocking:
        return None, check

    for sid, mode, old, new in writes:
        ctx.doc.write(sid, mode, old, new)
    # 旧值泄漏：填过值的模板上，旧批号/旧流水号/旧日期还留在输出里 = 有位置没标到
    after = {sid: squash(text) for sid, text in ctx.doc.snapshot().items()}
    written = {sid: squash(new) for sid, _mode, _old, new in writes}
    for entry in ctx.binding.get("fields", []):
        key = str(entry.get("field"))
        if not key.startswith("batch:"):
            continue
        for slot in entry.get("slots", []):
            sid = str(slot["sid"])
            old = squash(str(slot.get("sample") or ""))
            if not old or old == written.get(sid):
                continue
            found = [
                other
                for other, text in after.items()
                if owner.get(other) != key and old in text
            ]
            if found:
                blocking.append({"kind": "stale", "sample": str(slot.get("sample")), "found_in": found})
    if blocking:
        check["ok"] = False
        check["blocking"] = blocking
        return None, check
    return ctx.doc.bytes(), check


async def check_report_render(db: AsyncSession, report_id: uuid.UUID) -> dict[str, Any]:
    """预检：缺项、旧值泄漏（拦截项）与警告（缺英文、没标注到模板的字段）。"""
    ctx = await _prepare(db, report_id)
    _data, check = await asyncio.to_thread(_build, ctx)
    return check


async def _build_checked(
    db: AsyncSession, report_id: uuid.UUID
) -> tuple[_Context, bytes, dict[str, Any]]:
    """回填出 docx 字节；有任何拦截项就抛 422，detail 是预检清单。"""
    ctx = await _prepare(db, report_id)
    data, check = await asyncio.to_thread(_build, ctx)
    if data is None:
        kinds = {str(item["kind"]) for item in check["blocking"]}
        raise AppException(
            status_code=422, message=_BLOCK_MESSAGES.get(next(iter(kinds)), _BLOCK_MESSAGES[""])
            if len(kinds) == 1
            else _BLOCK_MESSAGES[""],
            detail=check,
        )
    return ctx, data, check


async def build_report_docx(
    db: AsyncSession, report_id: uuid.UUID
) -> tuple[bytes, str, dict[str, Any]]:
    """只生成 docx 字节，不留档——给「转成 PDF 打印」这类自己负责留档的调用方用。

    有拦截项时同样抛 422。
    """
    _ctx, data, check = await _build_checked(db, report_id)
    return data, str(check["filename"]), check


async def render_report_docx(
    db: AsyncSession, report_id: uuid.UUID, user: User | None = None
) -> tuple[bytes, str, dict[str, Any]]:
    """生成 docx 字节并留档；有拦截项时抛 422，detail 是预检清单。

    留档失败同样不出文件：送出去的每一份都必须在系统里有底稿。
    """
    ctx, data, check = await _build_checked(db, report_id)
    filename = str(check["filename"])
    await archive_render(
        db,
        report=ctx.report,
        standard=ctx.standard,
        data=data,
        filename=filename,
        check=check,
        user=user,
    )
    return data, filename, check


_BLOCK_MESSAGES = {
    "missing": "有字段没有登记值，不能生成 COA（不许带着模板旧值或空白出报告）",
    "stale": "输出里仍能找到模板的旧批号/旧日期，有位置没标到，不能生成 COA",
    "": "预检未通过，不能生成 COA",
}
