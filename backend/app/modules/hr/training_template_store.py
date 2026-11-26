"""培训导出模板存取服务：版本化存储、上传校验、加载与渲染。

加载口径：DB 当前自定义版优先；无当前版（或存储对象丢失）回退
backend/assets/hr/ 仓库默认模板。生成器保持同步函数、接收
``template_bytes`` 参数；路由侧用 :func:`render_training_document`
一行完成「取模板字节 → 调生成器」。

模板元数据（标记清单/说明）在 training_template_registry，本模块
只管存取与校验，不 commit、不写审计（由路由层负责，与合同档案库同约定）。
"""

import logging
from collections.abc import Callable
from io import BytesIO
from uuid import UUID, uuid4

from docx import Document
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundException
from app.core.file_storage import (
    cleanup_object,
    read_object,
    store_object,
    validate_upload,
)
from app.modules.hr.docx_markers import find_missing_markers
from app.modules.hr.models import TrainingExportTemplateVersion
from app.modules.hr.template_utils import find_hr_template_bytes
from app.modules.hr.training_template_registry import (
    TEMPLATES_BY_KEY,
    TrainingTemplateDef,
)

logger = logging.getLogger(__name__)

MODULE = "hr"
_STORAGE_PREFIX = "training-templates"
_MAX_SIZE = 10 * 1024 * 1024
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def get_template_def(key: str) -> TrainingTemplateDef:
    tdef = TEMPLATES_BY_KEY.get(key)
    if tdef is None:
        raise NotFoundException("培训导出模板", key)
    return tdef


# ───────────────────────── 加载 / 渲染 ─────────────────────────


async def get_current_version(db: AsyncSession, key: str) -> TrainingExportTemplateVersion | None:
    return (
        await db.execute(
            select(TrainingExportTemplateVersion).where(
                TrainingExportTemplateVersion.template_key == key,
                TrainingExportTemplateVersion.is_current.is_(True),
                TrainingExportTemplateVersion.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()


async def load_training_template_bytes(db: AsyncSession, key: str) -> tuple[bytes, str]:
    """加载模板字节。返回 (bytes, source)：source 为 "custom"（DB 当前版）
    或 "default"（仓库默认模板）。当前版对象丢失时告警并回退默认。"""
    get_template_def(key)  # 校验注册键存在
    row = await get_current_version(db, key)
    if row is not None:
        obj = read_object(MODULE, row.storage_key)
        if obj is not None:
            return obj[0], "custom"
        logger.warning(
            "培训导出模板 %s 当前版对象丢失（storage_key=%s），回退仓库默认模板",
            key, row.storage_key,
        )
    return find_hr_template_bytes(key), "default"


async def render_training_document(
    db: AsyncSession,
    key: str,
    render: Callable[[bytes], BytesIO],
) -> BytesIO:
    """路由侧统一入口：取模板字节（自定义优先）→ 调生成器 → 返回文档流。"""
    data, _source = await load_training_template_bytes(db, key)
    return render(data)


def default_template_bytes(key: str) -> bytes:
    """仓库默认模板字节（前端「下载默认模板」用，不走 DB）。"""
    get_template_def(key)  # 校验注册键存在
    return find_hr_template_bytes(key)


# ───────────────────────── 上传校验 ─────────────────────────


def validate_template_document(filename: str | None, data: bytes) -> str:
    """扩展名/魔数/大小校验 + python-docx 可解析校验，返回安全文件名。"""
    safe_name, _ext, _mime = validate_upload(
        filename, data,
        allowed={".docx": _DOCX_MIME}, max_size=_MAX_SIZE,
        kind_label="Word 模板", default_name="template",
    )
    try:
        Document(BytesIO(data))
    except Exception as exc:  # PackageNotFoundError / BadZipFile / OxmlError 等
        raise AppException(status_code=422, message=f"模板文件无法解析：{exc}") from exc
    return safe_name


async def upload_training_template(
    db: AsyncSession,
    key: str,
    filename: str | None,
    data: bytes,
    user=None,
    remark: str | None = None,
) -> TrainingExportTemplateVersion:
    """上传新版本：校验 → 旧当前版转历史 → 落对象存储 → 入库（当前版）。

    校验失败抛 AppException(422)（含缺失标记清单）；落库失败清理已写入的对象。
    不 commit，由路由层负责。
    """
    tdef = get_template_def(key)
    safe_name = validate_template_document(filename, data)
    missing = find_missing_markers(tdef.required_markers, data)
    if missing:
        raise AppException(
            status_code=422,
            message="模板缺少必填标记：" + "、".join(missing),
        )

    storage_key = f"{_STORAGE_PREFIX}/{key}/{uuid4().hex}.docx"
    store_object(MODULE, storage_key, data, _DOCX_MIME)
    try:
        # 先落「旧当前版转历史」的 UPDATE，再 INSERT，避免当前版唯一索引冲突
        await db.execute(
            update(TrainingExportTemplateVersion)
            .where(
                TrainingExportTemplateVersion.template_key == key,
                TrainingExportTemplateVersion.is_current.is_(True),
                TrainingExportTemplateVersion.is_deleted.is_(False),
            )
            .values(is_current=False)
        )
        next_no = (
            await db.execute(
                select(func.max(TrainingExportTemplateVersion.version_no)).where(
                    TrainingExportTemplateVersion.template_key == key,
                    TrainingExportTemplateVersion.is_deleted.is_(False),
                )
            )
        ).scalar() or 0
        row = TrainingExportTemplateVersion(
            template_key=key,
            version_no=next_no + 1,
            is_current=True,
            storage_key=storage_key,
            file_name=safe_name,
            content_type=_DOCX_MIME,
            size=len(data),
            remark=(remark or "").strip() or None,
            created_by=user.id if user is not None else None,
        )
        db.add(row)
        await db.flush()
        return row
    except Exception:
        cleanup_object(MODULE, storage_key)
        raise


# ───────────────────────── 版本管理 ─────────────────────────


async def list_versions(db: AsyncSession, key: str) -> list[TrainingExportTemplateVersion]:
    get_template_def(key)  # 校验注册键存在
    rows = (
        await db.execute(
            select(TrainingExportTemplateVersion).where(
                TrainingExportTemplateVersion.template_key == key,
                TrainingExportTemplateVersion.is_deleted.is_(False),
            ).order_by(TrainingExportTemplateVersion.version_no.desc())
        )
    ).scalars().all()
    return list(rows)


async def get_version(db: AsyncSession, key: str, version_id: UUID) -> TrainingExportTemplateVersion:
    row = await db.get(TrainingExportTemplateVersion, version_id)
    if row is None or row.template_key != key or row.is_deleted:
        raise NotFoundException("模板版本", str(version_id))
    return row


async def read_version_bytes(row: TrainingExportTemplateVersion) -> bytes:
    obj = read_object(MODULE, row.storage_key)
    if obj is None:
        raise NotFoundException("模板文件", row.storage_key)
    return obj[0]


async def activate_version(db: AsyncSession, key: str, version_id: UUID, user=None) -> TrainingExportTemplateVersion:
    """激活历史版本（回滚）：目标版置当前，其余全部转历史。"""
    row = await get_version(db, key, version_id)
    await db.execute(
        update(TrainingExportTemplateVersion)
        .where(
            TrainingExportTemplateVersion.template_key == key,
            TrainingExportTemplateVersion.is_current.is_(True),
            TrainingExportTemplateVersion.is_deleted.is_(False),
        )
        .values(is_current=False)
    )
    row.is_current = True
    if user is not None:
        row.updated_by = user.id
    await db.flush()
    return row


async def restore_default(db: AsyncSession, key: str) -> None:
    """恢复官方默认：当前版全部转历史（行保留可再激活），加载回退仓库模板。"""
    get_template_def(key)
    await db.execute(
        update(TrainingExportTemplateVersion)
        .where(
            TrainingExportTemplateVersion.template_key == key,
            TrainingExportTemplateVersion.is_current.is_(True),
            TrainingExportTemplateVersion.is_deleted.is_(False),
        )
        .values(is_current=False)
    )
    await db.flush()


# ───────────────────────── 展示字典 ─────────────────────────


async def resolve_uploader_names(db: AsyncSession, rows: list[TrainingExportTemplateVersion]) -> dict[UUID, str]:
    """批量解析上传人姓名（identity.users），缺失的不进字典。"""
    ids = {row.created_by for row in rows if row.created_by}
    if not ids:
        return {}
    from app.platform.identity.models import User

    pairs = (
        await db.execute(select(User.id, User.name).where(User.id.in_(ids)))
    ).all()
    return {uid: name for uid, name in pairs}


def template_version_dict(row: TrainingExportTemplateVersion, uploader_name: str | None = None) -> dict:
    return {
        "id": str(row.id),
        "template_key": row.template_key,
        "version_no": row.version_no,
        "is_current": row.is_current,
        "file_name": row.file_name,
        "size": row.size,
        "remark": row.remark,
        "uploaded_by": uploader_name or (str(row.created_by) if row.created_by else None),
        "uploaded_at": row.created_at.isoformat() if row.created_at else None,
    }


def template_def_dict(tdef: TrainingTemplateDef, current: TrainingExportTemplateVersion | None,
                      version_count: int, uploader_name: str | None = None) -> dict:
    return {
        "key": tdef.key,
        "name": tdef.name,
        "description": tdef.description,
        "default_file": tdef.default_file,
        "markers": [
            {"name": m.name, "description": m.description, "required": m.required}
            for m in tdef.markers
        ],
        "notes": list(tdef.notes),
        "custom": template_version_dict(current, uploader_name) if current is not None else None,
        "version_count": version_count,
    }
