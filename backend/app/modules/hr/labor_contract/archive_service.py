"""合同电子档案库（P2）：扫描件上传/版本保留/代理下载/调阅留痕/未归档清单。

对象存储与审计照搬证件资料库（app/core/file_storage + 平台审计）：
- 一份合同一个合并文件（需求：逐页合并一份、不拆分）；换传即升版本，旧版本保留可查
- 展示/下载名按需求规则由服务端生成：工号+姓名+签订次数+起止日期；存储 key 用英文安全字符
- 调阅权限三级（归档规则第 8 条）：HR（全量数据范围）全部原件；员工本人（self_only）
  仅本人合同；部门数据范围只可见本部门在职人员合同基本信息，不含原件
- 每次 view / download 写 hr_contract_access_logs + 平台审计

SQLAlchemy async 铁律：INSERT flush 返回即可；UPDATE 后不直接读 updated_at（上层重查）。
"""

import logging
import uuid as uuid_mod
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ForbiddenException
from app.core.file_storage import (
    cleanup_object,
    content_disposition,
    read_object,
    store_object,
    validate_upload,
)
from app.modules.hr.deps import HrAccessContext
from app.modules.hr.labor_contract import repository as repo
from app.modules.hr.labor_contract.models import (
    ContractAccessLog,
    ContractArchiveVersion,
    LaborContract,
)
from app.modules.hr.models import DepartureRecord

logger = logging.getLogger(__name__)

MODULE = "hr"
RESOURCE_TYPE = "hr_labor_contract"

# 合同扫描件：常见图片 + PDF，与证件资料库同上限
_ALLOWED_EXTENSIONS: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".pdf": "application/pdf",
}
_MAX_SIZE = 20 * 1024 * 1024

UNARCHIVED_EXPORT_HEADERS = [
    "部门", "工号", "姓名", "岗位", "学历", "签订次数", "合同期限", "起始日", "到期日",
    "签订日", "领取时间", "人员状态", "合同状态",
]

# 换传（已有当前版本再上传）必须写明原因：作废或重签的保留原版本并注明原因，不直接覆盖
REPLACE_REASON_REQUIRED_MESSAGE = "已有扫描件，换传新版本必须填写换传原因"

# 学历筛选项：由高到低的已知取值；未列出的排其后。明显脏值（含「-」或超过 8 个字）不进字典
EDUCATION_RANK = ("博士", "硕士", "本科", "大专", "中专", "高中", "初中", "小学")
_EDUCATION_MAX_LENGTH = 8


def sort_education_options(values: Iterable[str | None]) -> list[str]:
    """学历筛选项字典：去空、去脏值，按由高到低排列（未列明的取值按字典序排在其后）。"""
    cleaned = {
        value.strip() for value in values
        if value and value.strip() and "-" not in value and len(value.strip()) <= _EDUCATION_MAX_LENGTH
    }
    return sorted(cleaned, key=lambda v: (
        EDUCATION_RANK.index(v) if v in EDUCATION_RANK else len(EDUCATION_RANK), v,
    ))


def archive_display_name(contract: LaborContract, ext: str) -> str:
    """需求命名规则：工号+姓名+签订次数+起止日期（ext 不带点）。"""
    end = contract.end_date.isoformat() if contract.end_date else "无固定期限"
    return (
        f"{contract.employee_number}_{contract.name}_第{contract.seq_no}次_"
        f"{contract.start_date.isoformat()}至{end}.{ext}"
    )


def version_dict(version: ContractArchiveVersion) -> dict[str, Any]:
    return {
        "id": str(version.id),
        "contract_id": str(version.contract_id),
        "version_no": version.version_no,
        "is_current": version.is_current,
        "file_name": version.file_name,
        "content_type": version.content_type,
        "size": version.size,
        "reason": version.reason,
        "remark": version.remark,
        "source": version.source,
        "uploaded_by": str(version.created_by) if version.created_by else None,
        "uploaded_at": version.created_at.isoformat() if version.created_at else None,
    }


def ensure_can_archive(ctx: HrAccessContext) -> None:
    """扫描件归档（上传/批量挂接/删除版本）仅限 HR：全量数据范围。"""
    if not ctx.is_unrestricted:
        raise ForbiddenException("数据范围限制：合同扫描件归档仅限 HR（全量数据范围）")


def can_access_file(ctx: HrAccessContext, contract: LaborContract) -> bool:
    """调阅权限三级：HR 全部原件；员工本人仅本人合同；部门范围不含原件。"""
    if ctx.is_unrestricted:
        return True
    if ctx.data_scope == "self_only":
        return bool(ctx.employee_number) and contract.employee_number == ctx.employee_number
    return False


# ═══════════════════════════════════════════════════════════════
# 上传 / 版本化（单个上传与批量挂接共用的入库核心）
# ═══════════════════════════════════════════════════════════════

async def create_archive_version(
    db: AsyncSession, *, contract: LaborContract, file_bytes: bytes,
    filename: str | None, remark: str | None = None, user=None,
    source: str = ContractArchiveVersion.SOURCE_SINGLE,
    reason: str | None = None,
) -> ContractArchiveVersion:
    """校验文件并写入新版本（旧版本转历史），同步合同行归档快照。不 commit 不写审计。

    文件校验失败抛 AppException(422)；换传（已有当前版本）必须带 reason，否则同样 422——
    在落文件之前拦下，被拒的换传不留孤儿对象。落库失败时清掉已写入的对象。
    """
    _, ext, mime = validate_upload(
        filename, file_bytes,
        allowed=_ALLOWED_EXTENSIONS, max_size=_MAX_SIZE,
        kind_label="图片/PDF 扫描件", default_name="contract",
    )
    old_current = await repo.get_current_version(db, contract.id)
    reason_text = (reason or "").strip() or None
    if old_current is not None and not reason_text:
        raise AppException(message=REPLACE_REASON_REQUIRED_MESSAGE, status_code=422)
    # 存储 key 只用英文安全字符（中文名、日期放展示名）
    key = f"contracts/{contract.id}/{uuid_mod.uuid4().hex}.{ext}"
    store_object(MODULE, key, file_bytes, mime)
    try:
        if old_current is not None:
            old_current.is_current = False
            await db.flush()  # 先落 UPDATE，避免当前版唯一索引与 INSERT 冲突
        uploader_id = user.id if user is not None else None
        version = ContractArchiveVersion(
            contract_id=contract.id,
            version_no=await repo.max_version_no(db, contract.id) + 1,
            is_current=True,
            storage_key=key,
            file_name=archive_display_name(contract, ext),
            content_type=mime,
            size=len(file_bytes),
            reason=reason_text[:255] if reason_text else None,
            remark=(remark or "").strip() or None,
            source=source,
            created_by=uploader_id,
        )
        db.add(version)
        contract.archive_status = LaborContract.ARCHIVE_ARCHIVED
        contract.archive_file_name = version.file_name
        contract.archive_uploaded_by = uploader_id
        contract.archive_uploaded_at = datetime.now(UTC)
        await db.flush()
    except Exception:
        cleanup_object(MODULE, key)
        raise
    return version


async def delete_version(
    db: AsyncSession, ctx: HrAccessContext, contract: LaborContract,
    version: ContractArchiveVersion,
) -> None:
    """删除一个扫描件版本（软删）。删的是当前版时最新历史版本顶替；没有剩余版本则回到未归档。"""
    ensure_can_archive(ctx)
    version.is_deleted = True
    version.is_current = False
    await db.flush()
    remaining = await repo.list_versions(db, contract.id)
    successor = remaining[0] if remaining else None
    if successor is not None:
        successor.is_current = True
        contract.archive_file_name = successor.file_name
    else:
        contract.archive_status = LaborContract.ARCHIVE_UNARCHIVED
        contract.archive_file_name = None
        contract.archive_uploaded_by = None
        contract.archive_uploaded_at = None
    contract.updated_by = ctx.user.id
    await db.flush()
    # 存储对象保留（软删除可恢复），不物理清文件


# ═══════════════════════════════════════════════════════════════
# 原件调阅（预览/下载，三级权限 + 留痕）
# ═══════════════════════════════════════════════════════════════

async def _log_access(
    db: AsyncSession, ctx: HrAccessContext, contract: LaborContract,
    version: ContractArchiveVersion, action: str,
) -> None:
    from app.platform.audit.service import record_audit_log

    db.add(ContractAccessLog(
        contract_id=contract.id,
        version_id=version.id,
        viewer_id=ctx.user.id,
        viewer_name=ctx.user.name or str(ctx.user.id),
        action=action,
        # 显式取墙钟时间：server 端 now() 是事务开始时间，同一事务内多次调阅会并列、排序不稳
        created_at=datetime.now(UTC),
    ))
    await record_audit_log(
        db, action=f"hr.contract.archive_{action}", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=contract.id,
        extra={
            "employee_number": contract.employee_number,
            "seq_no": contract.seq_no,
            "version_no": version.version_no,
        },
    )


async def get_archive_file(
    db: AsyncSession, ctx: HrAccessContext, contract: LaborContract,
    version: ContractArchiveVersion, *, download: bool = False,
) -> tuple[bytes, dict[str, str]]:
    """读取扫描件原件：调阅权限校验 + 留痕，返回 (bytes, 响应头)。"""
    if not can_access_file(ctx, contract):
        raise ForbiddenException("数据范围限制：合同扫描件原件仅限 HR 与员工本人调阅")
    obj = read_object(MODULE, version.storage_key)
    if obj is None:
        raise AppException(message="扫描件文件缺失，请联系管理员", status_code=404)
    data, _content_type = obj
    await _log_access(
        db, ctx, contract, version,
        ContractAccessLog.ACTION_DOWNLOAD if download else ContractAccessLog.ACTION_VIEW,
    )
    disposition = "attachment" if download or version.content_type == "application/pdf" else "inline"
    return data, {
        "Content-Disposition": content_disposition(disposition, version.file_name),
        "Content-Type": version.content_type,
    }


async def list_access_logs(
    db: AsyncSession, contract_id: UUID, *, page: int = 1, page_size: int = 20,
) -> tuple[int, list[dict[str, Any]]]:
    """某份合同的调阅/下载记录（新→旧），带被调阅版本号。"""
    conds = (ContractAccessLog.contract_id == contract_id, ContractAccessLog.is_deleted.is_(False))
    total = int((await db.execute(
        select(func.count()).select_from(ContractAccessLog).where(*conds)
    )).scalar_one())
    rows = (await db.execute(
        select(ContractAccessLog, ContractArchiveVersion.version_no)
        .outerjoin(
            ContractArchiveVersion,
            ContractArchiveVersion.id == ContractAccessLog.version_id,
        )
        .where(*conds)
        .order_by(ContractAccessLog.created_at.desc())
        .offset((max(page, 1) - 1) * page_size).limit(page_size)
    )).all()
    items = [{
        "id": str(log.id),
        "viewer_name": log.viewer_name,
        "action": log.action,
        "action_label": ContractAccessLog.ACTION_LABELS.get(log.action, log.action),
        "version_no": version_no,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    } for log, version_no in rows]
    return total, items


# ═══════════════════════════════════════════════════════════════
# 未归档清单（补扫清单导出 / 归档缺失周提醒共用口径）
# ═══════════════════════════════════════════════════════════════

async def resolve_departed(
    db: AsyncSession, contracts: list[LaborContract],
) -> set[str]:
    """这批合同里属于离职人员的工号集合（口径同 repository.departed_expr）。"""
    numbers = list({c.employee_number for c in contracts})
    left = await repo.map_left_employees(db, numbers)
    if not numbers:
        return left
    departed_rows = (await db.execute(
        select(DepartureRecord.employee_number).where(
            DepartureRecord.employee_number.in_(numbers),
            DepartureRecord.is_deleted.is_(False),
        )
    )).scalars().all()
    return left | set(departed_rows)


def unarchived_export_rows(
    contracts: list[LaborContract], departed: set[str],
    education: Mapping[str, str | None] | None = None,
) -> list[list[str]]:
    """补扫清单行（调用前已按部门-工号-签订次数排好序）；education 为 {工号: 学历}。"""
    taught = education or {}
    rows: list[list[str]] = []
    for c in contracts:
        rows.append([
            c.department, c.employee_number, c.name, c.position or "",
            taught.get(c.employee_number) or "",
            c.seq_label, c.term_label,
            c.start_date.isoformat() if c.start_date else "",
            c.end_date.isoformat() if c.end_date else "无固定期限",
            c.sign_date.isoformat() if c.sign_date else "",
            c.delivered_at.strftime("%Y-%m-%d %H:%M") if c.delivered_at else "",
            "离职" if c.employee_number in departed else "在职",
            c.status_label,
        ])
    return rows


async def archive_stats(db: AsyncSession) -> dict[str, int]:
    """档案库概览：在职/离职 × 未归档/已归档 的合同份数。"""
    inner = (
        select(
            LaborContract.archive_status.label("archive_status"),
            repo.departed_expr().label("departed"),
        )
        .where(LaborContract.is_deleted.is_(False))
        .subquery()
    )
    rows = (await db.execute(
        select(inner.c.archive_status, inner.c.departed, func.count())
        .group_by(inner.c.archive_status, inner.c.departed)
    )).all()
    stats = {
        "in_service_unarchived": 0, "in_service_archived": 0,
        "departed_unarchived": 0, "departed_archived": 0,
    }
    for archive_status, is_departed, count in rows:
        key = ("departed_" if is_departed else "in_service_") + (
            "archived" if archive_status == LaborContract.ARCHIVE_ARCHIVED else "unarchived"
        )
        stats[key] = stats.get(key, 0) + int(count)
    return stats


async def unarchived_by_department(
    db: AsyncSession, *, departments: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """未归档份数按部门分组（档案库部门下拉 + 概览；按合同快照部门，跟随台账真实取值）。"""
    conds: list[ColumnElement[bool]] = [
        LaborContract.is_deleted.is_(False),
        LaborContract.archive_status == LaborContract.ARCHIVE_UNARCHIVED,
    ]
    if departments is not None:
        if not departments:
            return []
        conds.append(LaborContract.department.in_(departments))
    rows = (await db.execute(
        select(LaborContract.department, func.count())
        .where(*conds)
        .group_by(LaborContract.department)
        .order_by(func.count().desc(), LaborContract.department.asc())
    )).all()
    return [{"department": department, "unarchived": int(count)} for department, count in rows]
