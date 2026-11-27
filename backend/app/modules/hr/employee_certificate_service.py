"""员工电子证件资料库：上传版本化 + 台账检索 + 缺件标注 + 调阅审计。

- 上传：指定员工+类别归档；同类别再传 = 换证/补交新版本（旧版本保留可查，
  is_current 翻转，部分唯一索引保证同员工同类别仅一个当前版本）
- 检索：台账按部门/类别/姓名过滤（HrAccessContext 数据范围收敛）；
  员工视图按六类分组展示当前版本+历史+待补交（应交清单见
  hr.certificate_requirements，重点岗位按 applies_to=key_position 追加）
- 保密：证件号码输出始终部分隐藏；原件预览/下载经后端代理并写审计
  （resource_type=hr.employee_certificate，QA operation-logs 同模式）
"""

import logging
import uuid as uuid_mod
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.file_storage import (
    content_disposition,
    read_object,
    store_object,
    validate_upload,
)
from app.modules.hr.deps import HrAccessContext
from app.modules.hr.models import (
    CertificateRequirement,
    Employee,
    EmployeeCertificate,
)

logger = logging.getLogger(__name__)

MODULE = "hr"
RESOURCE_TYPE = "hr.employee_certificate"

# 证件扫描件：常见图片 + PDF，与 QA 偏差附件同上限
_ALLOWED_EXTENSIONS: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".pdf": "application/pdf",
}
_MAX_SIZE = 20 * 1024 * 1024


def mask_certificate_no(no: str | None) -> str | None:
    """证件号码部分隐藏：短号全遮，长号保留首尾各 2 位。"""
    if not no:
        return None
    stripped = no.strip()
    if len(stripped) <= 4:
        return "*" * len(stripped)
    return f"{stripped[:2]}{'*' * (len(stripped) - 4)}{stripped[-2:]}"


def _serialize(cert: EmployeeCertificate) -> dict[str, Any]:
    return {
        "id": str(cert.id),
        "employee_id": str(cert.employee_id),
        "category": cert.category,
        "certificate_name": cert.certificate_name,
        "certificate_no": mask_certificate_no(cert.certificate_no),
        "issue_date": cert.issue_date.isoformat() if cert.issue_date else None,
        "expiry_date": cert.expiry_date.isoformat() if cert.expiry_date else None,
        "is_permanent": cert.is_permanent,
        "version_no": cert.version_no,
        "is_current": cert.is_current,
        "filename": cert.filename,
        "content_type": cert.content_type,
        "size": cert.size,
        "remark": cert.remark,
        "created_at": cert.created_at.isoformat() if cert.created_at else None,
    }


async def _audit(
    session: AsyncSession, ctx: HrAccessContext, action: str,
    cert: EmployeeCertificate, employee: Employee,
    *, old_value: dict[str, Any] | None = None, new_value: dict[str, Any] | None = None,
) -> None:
    from app.platform.audit.service import record_audit_log

    await record_audit_log(
        session,
        action=action,
        user=ctx.user,
        resource_type=RESOURCE_TYPE,
        resource_id=cert.id,
        old_value=old_value,
        new_value=new_value,
        extra={
            "employee_id": str(employee.id),
            "employee_name": employee.name,
            "category": cert.category,
            "version_no": cert.version_no,
        },
    )


# ═══════════════════════════════════════════════════════════════
# 应交清单 / 缺件计算
# ═══════════════════════════════════════════════════════════════

async def list_requirements(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (await session.execute(
        select(CertificateRequirement)
        .where(CertificateRequirement.is_deleted.is_(False))
        .order_by(CertificateRequirement.applies_to, CertificateRequirement.category)
    )).scalars().all()
    return [{
        "id": str(r.id),
        "category": r.category,
        "applies_to": r.applies_to,
    } for r in rows]


async def _required_categories(session: AsyncSession, is_key_position: bool | None) -> set[str]:
    """应交类别集合：全员清单 ∪（重点岗位追加清单）。"""
    rows = (await session.execute(
        select(CertificateRequirement.category).where(
            CertificateRequirement.is_deleted.is_(False),
            CertificateRequirement.applies_to == CertificateRequirement.APPLIES_ALL,
        )
    )).scalars().all()
    required = set(rows)
    if is_key_position:
        extra = (await session.execute(
            select(CertificateRequirement.category).where(
                CertificateRequirement.is_deleted.is_(False),
                CertificateRequirement.applies_to == CertificateRequirement.APPLIES_KEY_POSITION,
            )
        )).scalars().all()
        required.update(extra)
    return required


async def add_requirement(session: AsyncSession, category: str, applies_to: str) -> dict[str, Any]:
    if category not in EmployeeCertificate.CATEGORIES:
        raise ValueError(f"非法证件类别：{category}")
    if applies_to not in (CertificateRequirement.APPLIES_ALL, CertificateRequirement.APPLIES_KEY_POSITION):
        raise ValueError("适用范围需为 all / key_position")
    exists = (await session.execute(
        select(CertificateRequirement).where(
            CertificateRequirement.category == category,
            CertificateRequirement.applies_to == applies_to,
            CertificateRequirement.is_deleted.is_(False),
        )
    )).scalar_one_or_none()
    if exists is not None:
        raise ValueError("该应交配置已存在")
    req = CertificateRequirement(
        id=uuid_mod.uuid4(), category=category, applies_to=applies_to,
    )
    session.add(req)
    await session.commit()
    return {"id": str(req.id), "category": category, "applies_to": applies_to}


async def delete_requirement(session: AsyncSession, requirement_id: UUID) -> None:
    req = (await session.execute(
        select(CertificateRequirement).where(
            CertificateRequirement.id == requirement_id,
            CertificateRequirement.is_deleted.is_(False),
        )
    )).scalar_one_or_none()
    if req is None:
        raise ValueError("应交配置不存在")
    req.is_deleted = True
    await session.commit()


# ═══════════════════════════════════════════════════════════════
# 台账 / 员工证件视图 / 缺件清单
# ═══════════════════════════════════════════════════════════════

async def list_certificates(
    session: AsyncSession, ctx: HrAccessContext, *,
    department: str | None = None,
    category: str | None = None,
    keyword: str | None = None,
    current_only: bool = True,
    page: int = 1, page_size: int = 20,
) -> tuple[list[dict], int]:
    stmt = (
        select(EmployeeCertificate, Employee)
        .join(Employee, Employee.id == EmployeeCertificate.employee_id)
        .where(EmployeeCertificate.is_deleted.is_(False), Employee.is_deleted.is_(False))
    )
    stmt = ctx.apply_list_scope(stmt, Employee)
    if current_only:
        stmt = stmt.where(EmployeeCertificate.is_current.is_(True))
    if department:
        stmt = stmt.where(Employee.department == department)
    if category:
        stmt = stmt.where(EmployeeCertificate.category == category)
    if keyword:
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(
            Employee.name.like(like) | Employee.employee_number.like(like)
        )
    total = int((await session.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar_one())
    rows = (await session.execute(
        stmt.order_by(Employee.department, Employee.employee_number, EmployeeCertificate.category)
        .offset((max(page, 1) - 1) * page_size).limit(page_size)
    )).all()
    items = []
    for cert, emp in rows:
        item = _serialize(cert)
        item.update({
            "employee_name": emp.name,
            "employee_number": emp.employee_number,
            "department": emp.department,
            "position": emp.position,
        })
        items.append(item)
    return items, total


async def get_employee_certificates(
    session: AsyncSession, ctx: HrAccessContext, employee_id: UUID,
) -> dict[str, Any]:
    """员工证件视图：六类分组（当前版本 + 历史 + 待补交标注）。"""
    employee = (await session.execute(
        select(Employee).where(Employee.id == employee_id, Employee.is_deleted.is_(False))
    )).scalar_one_or_none()
    if employee is None:
        raise ValueError("员工不存在")
    ctx.ensure_can_access_employee(employee)

    certs = (await session.execute(
        select(EmployeeCertificate).where(
            EmployeeCertificate.employee_id == employee_id,
            EmployeeCertificate.is_deleted.is_(False),
        ).order_by(EmployeeCertificate.version_no.desc())
    )).scalars().all()

    by_category: dict[str, list[EmployeeCertificate]] = {c: [] for c in EmployeeCertificate.CATEGORIES}
    for cert in certs:
        by_category.setdefault(cert.category, []).append(cert)

    required = await _required_categories(session, employee.is_key_position)
    categories = []
    missing: list[dict[str, Any]] = []
    for cat in EmployeeCertificate.CATEGORIES:
        entries = by_category.get(cat) or []
        current = next((c for c in entries if c.is_current), None)
        is_required = cat in required
        categories.append({
            "category": cat,
            "label": EmployeeCertificate.CATEGORY_LABELS[cat],
            "required": is_required,
            "current": _serialize(current) if current else None,
            "history": [_serialize(c) for c in entries if not c.is_current],
        })
        if is_required and current is None:
            missing.append({
                "category": cat,
                "label": EmployeeCertificate.CATEGORY_LABELS[cat],
            })

    return {
        "employee": {
            "id": str(employee.id),
            "employee_number": employee.employee_number,
            "name": employee.name,
            "department": employee.department,
            "position": employee.position,
            "status": employee.status,
            "is_key_position": employee.is_key_position,
        },
        "categories": categories,
        "missing": missing,
    }


async def list_missing(
    session: AsyncSession, ctx: HrAccessContext, *,
    department: str | None = None,
) -> list[dict[str, Any]]:
    """缺件清单（HR 催收视图）：应交而未交的员工×类别行。"""
    stmt = select(Employee).where(
        Employee.is_deleted.is_(False),
        Employee.status != "离职",
    )
    stmt = ctx.apply_list_scope(stmt, Employee)
    if department:
        stmt = stmt.where(Employee.department == department)
    employees = (await session.execute(stmt)).scalars().all()
    if not employees:
        return []

    all_required = await _required_categories(session, is_key_position=None)  # 全员档
    key_required = await _required_categories(session, is_key_position=True)
    key_only = key_required - all_required

    emp_ids = [e.id for e in employees]
    has_current = set((await session.execute(
        select(EmployeeCertificate.employee_id, EmployeeCertificate.category).where(
            EmployeeCertificate.employee_id.in_(emp_ids),
            EmployeeCertificate.is_current.is_(True),
            EmployeeCertificate.is_deleted.is_(False),
        )
    )).all())

    result = []
    for emp in employees:
        required = all_required | (key_only if emp.is_key_position else set())
        for cat in sorted(required):
            if (emp.id, cat) not in has_current:
                result.append({
                    "employee_id": str(emp.id),
                    "employee_name": emp.name,
                    "employee_number": emp.employee_number,
                    "department": emp.department,
                    "is_key_position": bool(emp.is_key_position),
                    "category": cat,
                    "category_label": EmployeeCertificate.CATEGORY_LABELS.get(cat, cat),
                })
    return result


# ═══════════════════════════════════════════════════════════════
# 上传 / 换证（版本化）
# ═══════════════════════════════════════════════════════════════

async def upload_certificate(
    session: AsyncSession, ctx: HrAccessContext, employee_id: UUID, *,
    file_bytes: bytes, filename: str | None,
    category: str, certificate_name: str | None = None,
    certificate_no: str | None = None, issue_date: date | None = None,
    expiry_date: date | None = None, is_permanent: bool = False,
    remark: str | None = None,
) -> dict[str, Any]:
    employee = (await session.execute(
        select(Employee).where(Employee.id == employee_id, Employee.is_deleted.is_(False))
    )).scalar_one_or_none()
    if employee is None:
        raise ValueError("员工不存在")
    ctx.ensure_can_access_employee(employee)
    if category not in EmployeeCertificate.CATEGORIES:
        raise ValueError(f"非法证件类别：{category}")

    safe_name, ext, mime = validate_upload(
        filename, file_bytes,
        allowed=_ALLOWED_EXTENSIONS, max_size=_MAX_SIZE, kind_label="图片/PDF 扫描件",
        default_name="certificate",
    )

    # 版本化：先翻旧版本（flush 落 UPDATE，避免唯一索引与后续 INSERT 冲突）
    old_current = (await session.execute(
        select(EmployeeCertificate).where(
            EmployeeCertificate.employee_id == employee_id,
            EmployeeCertificate.category == category,
            EmployeeCertificate.is_current.is_(True),
            EmployeeCertificate.is_deleted.is_(False),
        )
    )).scalar_one_or_none()
    if old_current is not None:
        old_current.is_current = False
        await session.flush()

    max_version = (await session.execute(
        select(func.max(EmployeeCertificate.version_no)).where(
            EmployeeCertificate.employee_id == employee_id,
            EmployeeCertificate.category == category,
            EmployeeCertificate.is_deleted.is_(False),
        )
    )).scalar_one() or 0

    key = f"certificates/{employee_id}/{category}/{uuid_mod.uuid4().hex}.{ext}"
    store_object(MODULE, key, file_bytes, mime)

    cert = EmployeeCertificate(
        id=uuid_mod.uuid4(),
        employee_id=employee_id,
        category=category,
        certificate_name=(certificate_name or "").strip() or None,
        certificate_no=(certificate_no or "").strip() or None,
        issue_date=issue_date,
        expiry_date=expiry_date,
        is_permanent=is_permanent,
        version_no=max_version + 1,
        is_current=True,
        storage_key=key,
        filename=safe_name,
        content_type=mime,
        size=len(file_bytes),
        remark=(remark or "").strip() or None,
    )
    session.add(cert)
    await session.flush()

    await _audit(session, ctx, "certificate_upload", cert, employee,
                 new_value={"version_no": cert.version_no, "filename": safe_name})
    await session.commit()
    return _serialize(cert)


# ═══════════════════════════════════════════════════════════════
# 原件调阅（预览/下载，记审计）
# ═══════════════════════════════════════════════════════════════

async def get_certificate_file(
    session: AsyncSession, ctx: HrAccessContext, cert_id: UUID, *,
    download: bool = False,
) -> tuple[bytes, dict[str, str]]:
    """读取原件：数据范围校验 + 审计留痕，返回 (bytes, 响应头)。"""
    cert = (await session.execute(
        select(EmployeeCertificate).where(
            EmployeeCertificate.id == cert_id,
            EmployeeCertificate.is_deleted.is_(False),
        )
    )).scalar_one_or_none()
    if cert is None:
        raise ValueError("证件不存在")
    employee = (await session.execute(
        select(Employee).where(Employee.id == cert.employee_id)
    )).scalar_one_or_none()
    if employee is None:
        raise ValueError("员工档案不存在")
    ctx.ensure_can_access_employee(employee)

    obj = read_object(MODULE, cert.storage_key)
    if obj is None:
        raise ValueError("证件原件文件缺失，请联系管理员")
    data, _content_type = obj

    await _audit(session, ctx,
                 "certificate_download" if download else "certificate_view",
                 cert, employee)
    await session.commit()

    disposition = "attachment" if download or cert.content_type == "application/pdf" else "inline"
    headers = {
        "Content-Disposition": content_disposition(disposition, cert.filename),
        "Content-Type": cert.content_type,
    }
    return data, headers


# ═══════════════════════════════════════════════════════════════
# 要素更正 / 删除
# ═══════════════════════════════════════════════════════════════

_UPDATABLE_FIELDS = (
    "certificate_name", "certificate_no", "issue_date",
    "expiry_date", "is_permanent", "remark",
)


async def update_certificate(
    session: AsyncSession, ctx: HrAccessContext, cert_id: UUID, *,
    changes: dict[str, Any],
) -> dict[str, Any]:
    cert = (await session.execute(
        select(EmployeeCertificate).where(
            EmployeeCertificate.id == cert_id,
            EmployeeCertificate.is_deleted.is_(False),
        )
    )).scalar_one_or_none()
    if cert is None:
        raise ValueError("证件不存在")
    employee = (await session.execute(
        select(Employee).where(Employee.id == cert.employee_id)
    )).scalar_one_or_none()
    if employee is None:
        raise ValueError("员工档案不存在")
    ctx.ensure_can_access_employee(employee)

    old_value: dict[str, Any] = {}
    for field in _UPDATABLE_FIELDS:
        if field in changes and changes[field] != getattr(cert, field):
            old_value[field] = getattr(cert, field)
            setattr(cert, field, changes[field])
    if old_value:
        await _audit(session, ctx, "certificate_update", cert, employee,
                     old_value=old_value)
    await session.commit()
    # UPDATE 后 re-fetch（async 铁律：updated_at 等 server 端值不回填内存对象）
    refreshed = (await session.execute(
        select(EmployeeCertificate).where(EmployeeCertificate.id == cert_id)
    )).scalar_one()
    return _serialize(refreshed)


async def delete_certificate(session: AsyncSession, ctx: HrAccessContext, cert_id: UUID) -> None:
    cert = (await session.execute(
        select(EmployeeCertificate).where(
            EmployeeCertificate.id == cert_id,
            EmployeeCertificate.is_deleted.is_(False),
        )
    )).scalar_one_or_none()
    if cert is None:
        raise ValueError("证件不存在")
    employee = (await session.execute(
        select(Employee).where(Employee.id == cert.employee_id)
    )).scalar_one_or_none()
    if employee is None:
        raise ValueError("员工档案不存在")
    ctx.ensure_can_access_employee(employee)

    cert.is_deleted = True
    await session.flush()
    # 删的是当前版本时：同类别剩余最新历史版本升为当前（若存在）
    if cert.is_current:
        successor = (await session.execute(
            select(EmployeeCertificate).where(
                EmployeeCertificate.employee_id == cert.employee_id,
                EmployeeCertificate.category == cert.category,
                EmployeeCertificate.is_deleted.is_(False),
            ).order_by(EmployeeCertificate.version_no.desc()).limit(1)
        )).scalar_one_or_none()
        if successor is not None:
            successor.is_current = True

    await _audit(session, ctx, "certificate_delete", cert, employee,
                 old_value={"version_no": cert.version_no})
    await session.commit()
    # 存储对象保留（软删除可恢复），不物理清文件


# ═══════════════════════════════════════════════════════════════
# 调阅记录查询（审计）
# ═══════════════════════════════════════════════════════════════

async def list_access_logs(
    session: AsyncSession, ctx: HrAccessContext, *,
    employee_id: UUID | None = None,
    page: int = 1, page_size: int = 20,
) -> tuple[list[dict], int]:
    from app.platform.audit.service import list_audit_logs

    logs, total = await list_audit_logs(
        session,
        page=page, page_size=page_size,
        resource_type=RESOURCE_TYPE,
        extra_equals={"employee_id": str(employee_id)} if employee_id else None,
    )
    items = []
    for log in logs:
        extra = log.extra or {}
        items.append({
            "id": str(log.id),
            "action": log.action,
            "employee_id": extra.get("employee_id"),
            "employee_name": extra.get("employee_name"),
            "category": extra.get("category"),
            "version_no": extra.get("version_no"),
            "user_id": str(log.user_id) if log.user_id else None,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        })
    return items, total
