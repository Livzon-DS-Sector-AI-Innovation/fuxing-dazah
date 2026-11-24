"""证件批量导入：ZIP 一次性上传 → 文件名解析（姓名+类别）→ 预检确认 → 批量归档。

两步预检式（与劳动合同台账导入同模式）：
- precheck：解压 ZIP，按文件名解析「姓名 + 证件类别」并匹配员工档案；每个合法
  文件先存暂存区（certificates/_batch/<批次>/），返回逐行状态供确认页修正
  （重名/未匹配手动选人、类别识别不出归「其他」、补填证号/有效期）
- commit：按确认行正式入库——读暂存文件写入正式 key（certificates/<员工>/<类别>/），
  版本化规则同单个上传（同类别自动升版本）；同批同「员工×类别」重复行拒绝，
  避免一版双文件互相顶成历史版本
- 文件名约定：<姓名><分隔符><证件类别关键词>，分隔符/顺序随意、支持中文名直连，
  如「张三_身份证.jpg」「李四-特种作业操作证.pdf」「王五健康证.png」；
  ZIP 支持子文件夹（取文件名解析）；Windows 简中打包的 GBK 文件名自动转码
"""

import io
import logging
import re
import uuid as uuid_mod
import zipfile
from datetime import date
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.file_storage import (
    cleanup_object,
    is_safe_key,
    read_object,
    store_object,
    validate_upload,
)
from app.modules.hr import employee_certificate_service as cert_service
from app.modules.hr.deps import HrAccessContext
from app.modules.hr.models import Employee, EmployeeCertificate

logger = logging.getLogger(__name__)

STAGING_PREFIX = "certificates/_batch/"
MAX_ZIP_SIZE = 200 * 1024 * 1024
MAX_UNCOMPRESSED = 400 * 1024 * 1024  # 防压缩炸弹：解压总量上限
MAX_BATCH_FILES = 200
MAX_OPTIONS = 50

# 类别关键词：全表取最长命中（最具体优先），识别不出由确认页人工修正
_CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("id_card", ("身份证", "身分证")),
    ("graduation", ("毕业证书", "毕业证", "学位证", "学历证", "毕业", "学历", "学位", "文凭")),
    ("professional_qualification", ("职业资格证书", "职业资格", "资格证", "职称证", "职称", "执业证")),
    ("special_operation", ("特种作业操作证", "特种作业", "操作证", "作业证", "特种")),
    ("health", ("健康证明", "健康证", "健康", "体检报告", "体检")),
)
_FILENAME_SEPS = re.compile(r"[_\-–—\s.·()（）\[\]【】,，、;；]+")
_CHINESE_NAME_RE = re.compile(r"^[\u4e00-\u9fff]{2,4}$")


def _member_name(info: zipfile.ZipInfo) -> str:
    """ZIP 成员名：未打 UTF-8 标记（Windows 简中常见 GBK）时尝试转码。"""
    name = info.filename
    if not (info.flag_bits & 0x800):
        try:
            name = name.encode("cp437").decode("gbk")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return name


def _is_junk_member(name: str) -> bool:
    parts = PurePosixPath(name.replace("\\", "/")).parts
    return any(p in ("__MACOSX",) or p.startswith(".") for p in parts[:-1]) or \
        parts[-1].startswith(".")


def match_category(stem: str) -> tuple[str | None, str | None]:
    """从文件名主干提取证件类别，返回 (类别, 命中关键词)。"""
    best: tuple[str, str] | None = None
    for cat, keywords in _CATEGORY_KEYWORDS:
        for kw in keywords:
            if kw in stem and (best is None or len(kw) > len(best[1])):
                best = (cat, kw)
    return best if best else (None, None)


def parse_certificate_filename(filename: str) -> dict[str, Any]:
    """文件名 → {姓名提示, 工号提示, 类别}。姓名取首个 2~4 字纯中文段。"""
    stem = PurePosixPath(filename.replace("\\", "/")).name
    stem = stem.rsplit(".", 1)[0].strip()
    category, keyword = match_category(stem)
    rest = stem.replace(keyword, " ", 1) if keyword else stem
    segments = [s for s in _FILENAME_SEPS.split(rest) if s]
    name = next((s for s in segments if _CHINESE_NAME_RE.fullmatch(s)), None)
    number = next((s for s in segments if s.isdigit() and len(s) >= 4), None)
    return {
        "name": name,
        "number": number,
        "category": category or EmployeeCertificate.CATEGORY_OTHER,
        "category_matched": category is not None,
    }


# ── 员工匹配 ──


async def list_employee_options(
    session: AsyncSession, ctx: HrAccessContext, *,
    keyword: str | None = None, limit: int = MAX_OPTIONS,
) -> list[dict[str, Any]]:
    """批量导入补选员工：姓名/工号模糊搜索（数据范围收敛）。"""
    stmt = select(Employee.id, Employee.name, Employee.employee_number, Employee.department).where(
        Employee.is_deleted.is_(False),
    )
    stmt = ctx.apply_list_scope(stmt, Employee)
    kw = (keyword or "").strip()
    if kw:
        like = f"%{kw}%"
        stmt = stmt.where(or_(Employee.name.ilike(like), Employee.employee_number.ilike(like)))
    rows = (await session.execute(stmt.order_by(Employee.name).limit(limit))).all()
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "employee_number": r.employee_number,
            "department": r.department,
        }
        for r in rows
    ]


async def _load_employee_index(session: AsyncSession, ctx: HrAccessContext):
    stmt = select(Employee.id, Employee.name, Employee.employee_number, Employee.department).where(
        Employee.is_deleted.is_(False),
    )
    stmt = ctx.apply_list_scope(stmt, Employee)
    rows = (await session.execute(stmt)).all()
    by_number: dict[str, Any] = {}
    by_name: dict[str, list[Any]] = {}
    for r in rows:
        by_number[r.employee_number] = r
        by_name.setdefault(r.name, []).append(r)
    return by_number, by_name


# ── 预检 ──


async def precheck_import(
    session: AsyncSession, ctx: HrAccessContext, *, zip_bytes: bytes,
) -> dict[str, Any]:
    if len(zip_bytes) > MAX_ZIP_SIZE:
        raise ValueError(f"ZIP 包大小不能超过 {MAX_ZIP_SIZE // (1024 * 1024)}MB")
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise ValueError("不是有效的 ZIP 文件，请重新打包上传")

    members = [i for i in zf.infolist() if not i.is_dir() and not _is_junk_member(i.filename)]
    if not members:
        raise ValueError("ZIP 内没有可导入的文件")
    if len(members) > MAX_BATCH_FILES:
        raise ValueError(f"单批最多 {MAX_BATCH_FILES} 个文件，请分批导入")
    if sum(i.file_size for i in members) > MAX_UNCOMPRESSED:
        raise ValueError("ZIP 解压后总大小超限，请分批导入")

    by_number, by_name = await _load_employee_index(session, ctx)
    batch_id = uuid_mod.uuid4().hex
    rows: list[dict[str, Any]] = []

    for info in sorted(members, key=lambda i: _member_name(i)):
        filename = _member_name(info)
        row: dict[str, Any] = {
            "filename": filename, "status": "ok", "error": None,
            "name_hint": None, "employee_number_hint": None,
            "employee": None, "candidates": [],
            "category": EmployeeCertificate.CATEGORY_OTHER, "category_matched": False,
            "storage_key": None, "content_type": None, "size": 0,
            "replaces": None, "dup_in_batch": False,
        }
        parsed = parse_certificate_filename(filename)
        row.update({
            "name_hint": parsed["name"],
            "employee_number_hint": parsed["number"],
            "category": parsed["category"],
            "category_matched": parsed["category_matched"],
        })

        try:
            data = zf.read(info)
            _, ext, mime = validate_upload(
                filename, data,
                allowed=cert_service._ALLOWED_EXTENSIONS,
                max_size=cert_service._MAX_SIZE,
                kind_label="图片/PDF 扫描件", default_name="certificate",
            )
        except AppException as e:
            row["status"], row["error"] = "invalid", str(e.message)
            rows.append(row)
            continue
        except Exception:
            row["status"], row["error"] = "invalid", "文件读取失败，可能已损坏"
            rows.append(row)
            continue

        # 员工匹配：工号精确命中 > 姓名唯一命中 > 重名待选 > 未匹配
        emp = by_number.get(parsed["number"]) if parsed["number"] else None
        if emp is None and parsed["name"]:
            hits = by_name.get(parsed["name"], [])
            if len(hits) == 1:
                emp = hits[0]
            elif len(hits) > 1:
                row["status"] = "ambiguous"
                row["candidates"] = [
                    {"id": str(r.id), "name": r.name, "employee_number": r.employee_number,
                     "department": r.department}
                    for r in hits[:MAX_OPTIONS]
                ]
        if emp is None and row["status"] == "ok":
            row["status"] = "unmatched"
        if emp is not None:
            row["employee"] = {
                "id": str(emp.id), "name": emp.name,
                "employee_number": emp.employee_number, "department": emp.department,
            }

        key = f"{STAGING_PREFIX}{batch_id}/{uuid_mod.uuid4().hex}.{ext}"
        store_object(cert_service.MODULE, key, data, mime)
        row.update({"storage_key": key, "content_type": mime, "size": len(data)})
        rows.append(row)

    # 已有当前版本的「员工×类别」标注换证提示
    matched = [r for r in rows if r["employee"]]
    pairs = {(r["employee"]["id"], r["category"]) for r in matched}
    if pairs:
        emp_ids = {UUID(p[0]) for p in pairs}
        cats = {p[1] for p in pairs}
        currents = (await session.execute(
            select(EmployeeCertificate).where(
                EmployeeCertificate.employee_id.in_(emp_ids),
                EmployeeCertificate.category.in_(cats),
                EmployeeCertificate.is_current.is_(True),
                EmployeeCertificate.is_deleted.is_(False),
            )
        )).scalars().all()
        existing = {(str(c.employee_id), c.category): c for c in currents}
        for r in matched:
            cert = existing.get((r["employee"]["id"], r["category"]))
            if cert is not None:
                r["replaces"] = {
                    "version_no": cert.version_no,
                    "expiry_date": cert.expiry_date.isoformat() if cert.expiry_date else None,
                    "is_permanent": cert.is_permanent,
                }

    # 同批同「员工×类别」多个文件 → 提交会被拒，预检阶段先亮出来
    seen: set[tuple[str, str]] = set()
    for r in rows:
        if r["employee"]:
            pair = (r["employee"]["id"], r["category"])
            if pair in seen:
                r["dup_in_batch"] = True
            seen.add(pair)

    summary = {
        "total": len(rows),
        "ok": sum(r["status"] == "ok" for r in rows),
        "unmatched": sum(r["status"] == "unmatched" for r in rows),
        "ambiguous": sum(r["status"] == "ambiguous" for r in rows),
        "invalid": sum(r["status"] == "invalid" for r in rows),
        "replaces": sum(bool(r["replaces"]) for r in rows),
    }
    return {"rows": rows, "summary": summary}


# ── 提交 ──


class BatchImportCommitRow(BaseModel):
    storage_key: str
    filename: str
    employee_id: UUID
    category: str
    certificate_name: str | None = None
    certificate_no: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    is_permanent: bool = False
    remark: str | None = None


class BatchImportCommitPayload(BaseModel):
    rows: list[BatchImportCommitRow]


async def commit_import(
    session: AsyncSession, ctx: HrAccessContext,
    rows: list[BatchImportCommitRow],
) -> dict[str, Any]:
    if not rows:
        raise ValueError("没有可导入的行")

    employees = {e.id: e for e in (await session.execute(
        select(Employee).where(
            Employee.id.in_({r.employee_id for r in rows}),
            Employee.is_deleted.is_(False),
        )
    )).scalars()}

    results: list[dict[str, Any]] = []
    imported = 0
    seen_pairs: dict[tuple[UUID, str], str] = {}

    for r in rows:
        result: dict[str, Any] = {
            "filename": r.filename, "employee_name": None,
            "category_label": (EmployeeCertificate.CATEGORY_LABELS.get(r.category, r.category)),
            "version_no": None, "ok": False, "error": None,
        }
        employee = employees.get(r.employee_id)
        if employee is None:
            result["error"] = "员工不存在（或不在数据范围内）"
            results.append(result)
            continue
        ctx.ensure_can_access_employee(employee)
        result["employee_name"] = employee.name

        pair = (r.employee_id, r.category)
        if pair in seen_pairs:
            result["error"] = f"与「{seen_pairs[pair]}」同员工同类别，一次导入每类别仅一个文件"
            results.append(result)
            continue
        seen_pairs[pair] = r.filename

        if not is_safe_key(r.storage_key) or not r.storage_key.startswith(STAGING_PREFIX):
            result["error"] = "附件暂存键不合法，请重新上传 ZIP 预检"
            results.append(result)
            continue
        staged = read_object(cert_service.MODULE, r.storage_key)
        if staged is None:
            result["error"] = "暂存附件已失效，请重新上传 ZIP 预检"
            results.append(result)
            continue
        data, _mime = staged

        try:
            cert = await cert_service.create_certificate_version(
                session, employee=employee, category=r.category,
                file_bytes=data, filename=r.filename,
                certificate_name=r.certificate_name, certificate_no=r.certificate_no,
                issue_date=r.issue_date, expiry_date=r.expiry_date,
                is_permanent=r.is_permanent, remark=r.remark,
            )
        except ValueError as e:
            results.append(result | {"error": str(e)})
            continue

        cleanup_object(cert_service.MODULE, r.storage_key)  # 暂存搬正式后清掉
        await cert_service._audit(
            session, ctx, "certificate_upload", cert, employee,
            new_value={"version_no": cert.version_no, "filename": cert.filename,
                       "batch_import": True},
        )
        results.append(result | {"ok": True, "version_no": cert.version_no})
        imported += 1

    await session.commit()
    return {
        "results": results,
        "summary": {"imported": imported, "failed": len(rows) - imported},
    }
