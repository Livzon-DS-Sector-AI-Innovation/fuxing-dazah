"""培训导出模板存取服务：版本化存储、上传校验、加载与渲染。

加载口径：DB 当前自定义版优先；无当前版（或存储对象丢失）回退
backend/assets/hr/ 仓库默认模板。生成器保持同步函数、接收
``template_bytes`` 参数；路由侧用 :func:`render_training_document`
一行完成「取模板字节 → 调生成器」。

模板元数据（标记清单/说明）在 training_template_registry，本模块
只管存取与校验，不 commit、不写审计（由路由层负责，与合同档案库同约定）。
"""

import logging
import re
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
from app.modules.hr.docx_markers import collect_template_text, find_missing_markers
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


# 占位符字面提取：先匹配双花括号（试卷模板 {{培训内容}}），再匹配单花括号
_MARKER_TOKEN_RE = re.compile(r"\{\{[^{}]{1,60}\}\}|\{[^{}]{1,60}\}")

# 标签格归一化：只保留中文（表格标签多为「培训内容\nTraining content」双语混排）
_CJK_ONLY_RE = re.compile(r"[^一-鿿]")


def _cell_cjk_label(text: str) -> str:
    """取单元格文本里的中文标签（去英文/空白），用于与标签词对照。"""
    return _CJK_ONLY_RE.sub("", text).strip()


def extract_docx_markers(data: bytes) -> list[str]:
    """自动识别 docx 模板里的占位符（去重、按首次出现顺序）。

    上传向导用：把用户文件里实际写了哪些 {标记} 扫出来，前端对照目标导出的
    必填清单做「缺哪些 / 哪些不被识别」的提示。识别不了占位符的普通文档返回空表。
    """
    text = collect_template_text(data)
    seen: list[str] = []
    for match in _MARKER_TOKEN_RE.finditer(text):
        token = match.group(0)
        if token not in seen:
            seen.append(token)
    return seen


def autofill_markers(key: str, data: bytes) -> tuple[bytes, list[dict[str, str]], list[str]]:
    """按标签对照自动生成缺失的占位符（上传向导「自动生成」用）。

    规则：遍历目标导出注册清单里缺失的标记，逐个在表格里找它的标签格
    （单元格中文即标签词、格内无既有标记）。插入位置二选一：
    「紧邻右侧空白格」（标签|内容 式表单）或「同列表头下一行的空白格」
    （列式表头+空白行式登记表）；紧邻格被占则不再向右找，直接走下一行。
    只新增文字、不改样式；放不下的留给 missing，由用户手动补。
    返回 (改好的 docx 字节——无插入时原样返回, 插入位置清单, 仍缺失清单)。
    """
    from app.modules.hr.docx_markers import set_cell_text
    from app.modules.hr.training_template_registry import MARKER_ALIASES

    def _distinct_cells(row) -> list:
        seen: list = []
        cells: list = []
        for cell in row.cells:
            if cell._tc in seen:
                continue
            seen.append(cell._tc)
            cells.append(cell)
        return cells

    placements: list[dict[str, str]] = []
    doc = Document(BytesIO(data))
    text = collect_template_text(doc)
    for marker in get_template_def(key).markers:
        if marker.name in text or marker.name not in MARKER_ALIASES:
            continue  # 已有，或该标记不参与自动生成（页码域/循环对/公式）
        aliases = {_CJK_ONLY_RE.sub("", a).strip() for a in MARKER_ALIASES[marker.name]}
        placed = False
        for table in doc.tables:
            if placed:
                break
            rows = list(table.rows)
            for ri, row in enumerate(rows):
                if placed:
                    break
                cells = _distinct_cells(row)
                for ci, cell in enumerate(cells):
                    label = _cell_cjk_label(cell.text)
                    if not label or label not in aliases or "{" in cell.text:
                        continue
                    target: object | None = None
                    where = ""
                    # 候选 A：紧邻右侧空白格（标签|内容）
                    if ci + 1 < len(cells) and not cells[ci + 1].text.strip():
                        target = cells[ci + 1]
                        where = f"「{label}」右侧"
                    # 候选 B：同列（同下标）下一行空白格（列式表头）
                    if target is None and ri + 1 < len(rows):
                        b_cells = _distinct_cells(rows[ri + 1])
                        if ci < len(b_cells) and not b_cells[ci].text.strip():
                            target = b_cells[ci]
                            where = f"「{label}」表头下方"
                    if target is None:
                        continue
                    set_cell_text(target, marker.name)
                    placements.append({"marker": marker.name, "where": where})
                    text = f"{text}\n{marker.name}"
                    placed = True
                    break

    if not placements:
        # 没动过文件：原字节返回，避免无意义改写
        return data, [], find_missing_markers(get_template_def(key).required_markers, data)

    missing = find_missing_markers(get_template_def(key).required_markers, doc)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue(), placements, missing


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
        "section": tdef.section,
        # usages 应为 tuple；单元素漏尾逗号会退化成 str，此处兜底避免逐字拆开
        "usages": list(tdef.usages) if isinstance(tdef.usages, (tuple, list)) else [tdef.usages],
        "markers": [
            {"name": m.name, "description": m.description, "required": m.required}
            for m in tdef.markers
        ],
        "notes": list(tdef.notes),
        "custom": template_version_dict(current, uploader_name) if current is not None else None,
        "version_count": version_count,
    }
