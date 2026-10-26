"""QA 偏差管理业务服务：编号、状态机、阶段守卫、重复偏差识别、附件与审计。

无审批节点：持 ``qa:deviation:update`` / ``qa:capa:update`` 的人即可推进
状态，每个动作写流转日志和审计日志以替代纸质签字。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import uuid
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import time as app_time
from app.core.exceptions import AppException, NotFoundException
from app.modules.qa import file_service
from app.modules.qa.models import (
    Capa,
    CapaAction,
    CapaActionStatus,
    CapaStatus,
    CapaStatusLog,
    Deviation,
    DeviationAttachment,
    DeviationHypothesisTest,
    DeviationItem,
    DeviationStatus,
    DeviationStatusLog,
    EffectConclusion,
    EffectMethod,
)
from app.modules.qa.repository import deviation as repo
from app.modules.qa.schemas import (
    CapaActionIn,
    CapaActionPatch,
    CapaCreate,
    CapaTransitionIn,
    CapaUpdate,
    DeviationCreate,
    DeviationExtendIn,
    DeviationItemIn,
    DeviationTransitionIn,
    DeviationUpdate,
    HypothesisTestIn,
)
from app.platform.audit.service import record_audit_log
from app.platform.identity.models import User

logger = logging.getLogger(__name__)

# SOP.02.1204：偏差自发现之日起 30 天内关闭。
CLOSE_WINDOW_DAYS = 30
_MAX_NO_RETRIES = 3

DEVIATION_TRANSITIONS: dict[str, list[str]] = {
    DeviationStatus.DRAFT.value: [DeviationStatus.INVESTIGATING.value],
    DeviationStatus.INVESTIGATING.value: [DeviationStatus.ASSESSING.value],
    DeviationStatus.ASSESSING.value: [DeviationStatus.CLOSED.value],
    DeviationStatus.CLOSED.value: [],
}
_DEVIATION_ACTION_TARGET: dict[str, DeviationStatus] = {
    "start_investigation": DeviationStatus.INVESTIGATING,
    "submit_assessment": DeviationStatus.ASSESSING,
    "close": DeviationStatus.CLOSED,
}
DEVIATION_STATUS_LABELS = {
    DeviationStatus.DRAFT.value: "登记中",
    DeviationStatus.INVESTIGATING.value: "调查中",
    DeviationStatus.ASSESSING.value: "评估中",
    DeviationStatus.CLOSED.value: "已关闭",
}

CAPA_TRANSITIONS: dict[str, list[str]] = {
    CapaStatus.PLANNED.value: [CapaStatus.IN_PROGRESS.value],
    CapaStatus.IN_PROGRESS.value: [CapaStatus.COMPLETED.value],
    CapaStatus.COMPLETED.value: [CapaStatus.EFFECT_EVALUATING.value],
    CapaStatus.EFFECT_EVALUATING.value: [CapaStatus.CLOSED.value],
    CapaStatus.CLOSED.value: [],
}
_CAPA_ACTION_TARGET: dict[str, CapaStatus] = {
    "start": CapaStatus.IN_PROGRESS,
    "complete": CapaStatus.COMPLETED,
    "start_evaluation": CapaStatus.EFFECT_EVALUATING,
    "close": CapaStatus.CLOSED,
}
CAPA_STATUS_LABELS = {
    CapaStatus.PLANNED.value: "已发起",
    CapaStatus.IN_PROGRESS.value: "实施中",
    CapaStatus.COMPLETED.value: "措施完成",
    CapaStatus.EFFECT_EVALUATING.value: "有效性评估中",
    CapaStatus.CLOSED.value: "已关闭",
}
# 有效性评估周期的默认天数；按批次/自定义的无法从日期推导，由 QA 填写。
_EFFECT_DEFAULT_DAYS = {
    EffectMethod.TRACKING_WEEK.value: 7,
    EffectMethod.TRACKING_MONTH.value: 30,
}


# ───────────────────────── 通用辅助 ─────────────────────────


def _actor_id(user: User | None) -> uuid.UUID | None:
    return user.id if user is not None else None


def _actor_name(user: User | None) -> str | None:
    return getattr(user, "name", None) if user is not None else None


async def _audit(
    db: AsyncSession,
    *,
    action: str,
    user: User | None,
    resource_type: str,
    resource_id: uuid.UUID | None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    await record_audit_log(
        db,
        action=action,
        user=user,
        user_id=_actor_id(user),
        resource_type=f"qa.{resource_type}",
        resource_id=resource_id,
        old_value=old_value,
        new_value=new_value,
        extra=extra,
    )


def validate_transition(
    current: str, target: str, transitions: dict[str, list[str]], labels: dict[str, str]
) -> None:
    if target not in transitions.get(current, []):
        raise AppException(
            status_code=409,
            message=(
                f"状态不允许从「{labels.get(current, current)}」"
                f"转换到「{labels.get(target, target)}」"
            ),
        )


async def _resolve_department(
    db: AsyncSession, department_id: str | None, department_name: str | None
) -> tuple[str | None, str | None]:
    """有飞书部门 ID 时校验并取名称快照；没有 ID 允许手填部门名称。"""
    if not department_id:
        return None, department_name
    from app.platform.identity.public_api import get_department_brief

    department = await get_department_brief(db, department_id)
    if department is None or not department.is_active:
        raise AppException(status_code=422, message="发生部门不存在或已停用")
    return department.feishu_department_id, department.name


def _default_due_date(discovery_date: date) -> date:
    return discovery_date + timedelta(days=CLOSE_WINDOW_DAYS)


def _month_prefix() -> str:
    """编号按登记月份：DE + 两位年 + 两位月。"""
    return f"DE{app_time.today():%y%m}"


async def _next_deviation_no(db: AsyncSession) -> str:
    prefix = _month_prefix()
    last = await repo.get_max_deviation_no(db, prefix)
    serial = 1
    if last:
        tail = last[len(prefix) :]
        if tail.isdigit():
            serial = int(tail) + 1
    return f"{prefix}{serial:03d}"


async def _get_deviation(
    db: AsyncSession, deviation_id: uuid.UUID, *, for_update: bool = False
) -> Deviation:
    deviation = await repo.get_deviation(db, deviation_id, for_update=for_update)
    if deviation is None:
        raise NotFoundException("偏差", str(deviation_id))
    return deviation


def _ensure_deviation_editable(deviation: Deviation) -> None:
    if deviation.status == DeviationStatus.CLOSED.value:
        raise AppException(status_code=409, message="偏差已关闭，不能再修改")


async def _log_deviation(
    db: AsyncSession,
    deviation: Deviation,
    *,
    action: str,
    user: User | None,
    from_status: str | None,
    to_status: str | None,
    comment: str | None = None,
) -> None:
    db.add(
        DeviationStatusLog(
            deviation_id=deviation.id,
            from_status=from_status,
            to_status=to_status,
            action=action,
            operator_id=_actor_id(user),
            operator_name=_actor_name(user),
            comment=comment,
            created_by=_actor_id(user),
            updated_by=_actor_id(user),
        )
    )


async def _replace_items(
    db: AsyncSession,
    deviation_id: uuid.UUID,
    items: list[DeviationItemIn],
    user: User | None,
) -> None:
    for existing in await repo.get_items(db, deviation_id):
        existing.is_deleted = True
        existing.updated_by = _actor_id(user)
    for index, item in enumerate(items):
        db.add(
            DeviationItem(
                deviation_id=deviation_id,
                category=item.category.value,
                name=item.name,
                batch_no=item.batch_no,
                handling=item.handling,
                sort_order=index,
                created_by=_actor_id(user),
                updated_by=_actor_id(user),
            )
        )


async def _replace_hypothesis_tests(
    db: AsyncSession,
    deviation_id: uuid.UUID,
    tests: list[HypothesisTestIn],
    user: User | None,
) -> None:
    for existing in await repo.get_hypothesis_tests(db, deviation_id):
        existing.is_deleted = True
        existing.updated_by = _actor_id(user)
    for index, test in enumerate(tests):
        db.add(
            DeviationHypothesisTest(
                deviation_id=deviation_id,
                sample=test.sample,
                hypothesis=test.hypothesis,
                protocol=test.protocol,
                expected=test.expected,
                result=test.result,
                conclusion=test.conclusion,
                tested_by=test.tested_by,
                tested_at=test.tested_at,
                sort_order=index,
                created_by=_actor_id(user),
                updated_by=_actor_id(user),
            )
        )


# ───────────────────────── 偏差：登记 / 编辑 ─────────────────────────


def _validate_dates(
    discovery_date: date, occurrence_date: date | None, due_date: date
) -> None:
    if discovery_date > app_time.today():
        raise AppException(status_code=422, message="发现日期不能晚于今天")
    if occurrence_date is not None and occurrence_date > discovery_date:
        raise AppException(status_code=422, message="发生日期不能晚于发现日期")
    if due_date < discovery_date:
        raise AppException(status_code=422, message="关闭期限不能早于发现日期")


async def create_deviation(
    db: AsyncSession, payload: DeviationCreate, user: User | None
) -> Deviation:
    department_id, department_name = await _resolve_department(
        db, payload.department_id, payload.department_name
    )
    due_date = payload.due_date or _default_due_date(payload.discovery_date)
    _validate_dates(payload.discovery_date, payload.occurrence_date, due_date)

    deviation: Deviation | None = None
    for attempt in range(_MAX_NO_RETRIES):
        candidate = Deviation(
            deviation_no=await _next_deviation_no(db),
            status=DeviationStatus.DRAFT.value,
            discovery_date=payload.discovery_date,
            occurrence_date=payload.occurrence_date,
            due_date=due_date,
            department_id=department_id,
            department_name=department_name,
            group_name=payload.group_name,
            reporter_name=payload.reporter_name,
            qa_person_name=payload.qa_person_name or _actor_name(user),
            description=payload.description,
            emergency_measures=payload.emergency_measures,
            remark=payload.remark,
            why_chain=[],
            repeat_deviation_ids=[],
            created_by=_actor_id(user),
            updated_by=_actor_id(user),
        )
        try:
            # 编号冲突只回滚到 SAVEPOINT，不影响同事务里已完成的其他写入。
            async with db.begin_nested():
                db.add(candidate)
                await db.flush()
        except IntegrityError as exc:
            if "uq_qa_deviations_no" not in str(exc):
                raise
            if attempt < _MAX_NO_RETRIES - 1:
                logger.debug("偏差编号冲突重试 attempt=%d", attempt + 1)
                continue
            raise AppException(message="偏差编号生成失败，请重试") from None
        deviation = candidate
        break
    assert deviation is not None

    await _replace_items(db, deviation.id, payload.items, user)
    await _log_deviation(
        db,
        deviation,
        action="create",
        user=user,
        from_status=None,
        to_status=DeviationStatus.DRAFT.value,
    )
    await _audit(
        db,
        action="deviation.create",
        user=user,
        resource_type="deviation",
        resource_id=deviation.id,
        new_value={"deviation_no": deviation.deviation_no},
    )
    await db.flush()
    return await _get_deviation(db, deviation.id)


async def _validate_repeat_ids(
    db: AsyncSession, deviation: Deviation, ids: list[uuid.UUID]
) -> list[str]:
    unique = [i for i in dict.fromkeys(ids) if i != deviation.id]
    found = {d.id for d in await repo.get_deviations_by_ids(db, unique)}
    missing = [str(i) for i in unique if i not in found]
    if missing:
        raise AppException(
            status_code=422, message=f"关联的重复偏差不存在：{', '.join(missing)}"
        )
    return [str(i) for i in unique]


async def update_deviation(
    db: AsyncSession,
    deviation_id: uuid.UUID,
    payload: DeviationUpdate,
    user: User | None,
) -> Deviation:
    deviation = await _get_deviation(db, deviation_id, for_update=True)
    _ensure_deviation_editable(deviation)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise AppException(message="没有需要更新的字段")
    if "description" in data and not data["description"]:
        raise AppException(status_code=422, message="偏差描述不能为空")

    if "department_id" in data or "department_name" in data:
        id_provided = "department_id" in data
        name_provided = "department_name" in data
        department_id = data.pop("department_id", deviation.department_id)
        department_name = data.pop("department_name", deviation.department_name)
        if name_provided and not id_provided and department_name != deviation.department_name:
            # 只改名称视为手填部门，清掉旧的飞书 ID，避免 ID 与名称快照不一致。
            department_id = None
        department_id, department_name = await _resolve_department(
            db, department_id, department_name
        )
        deviation.department_id = department_id
        deviation.department_name = department_name

    items = data.pop("items", None)
    hypothesis_tests = data.pop("hypothesis_tests", None)
    why_chain = data.pop("why_chain", None)
    repeat_ids = data.pop("repeat_deviation_ids", None)

    new_discovery = data.get("discovery_date", deviation.discovery_date)
    new_occurrence = data.get("occurrence_date", deviation.occurrence_date)
    due_date = deviation.due_date
    if (
        "discovery_date" in data
        and data["discovery_date"] != deviation.discovery_date
        and deviation.extension_count == 0
    ):
        # 只有发现日期真的变化才重算，避免改其他字段时冲掉人工设定的期限。
        due_date = _default_due_date(new_discovery)
    _validate_dates(new_discovery, new_occurrence, due_date)
    deviation.due_date = due_date

    for field, value in data.items():
        setattr(deviation, field, value.value if hasattr(value, "value") else value)
    if why_chain is not None:
        deviation.why_chain = [
            {"question": step.question, "answer": step.answer}
            for step in payload.why_chain or []
        ]
    if repeat_ids is not None:
        deviation.repeat_deviation_ids = await _validate_repeat_ids(
            db, deviation, payload.repeat_deviation_ids or []
        )
    if deviation.capa_initiated is True:
        deviation.capa_not_initiated_reason = None
    if items is not None:
        await _replace_items(db, deviation.id, payload.items or [], user)
    if hypothesis_tests is not None:
        await _replace_hypothesis_tests(
            db, deviation.id, payload.hypothesis_tests or [], user
        )
    deviation.updated_by = _actor_id(user)
    await db.flush()
    await _audit(
        db,
        action="deviation.update",
        user=user,
        resource_type="deviation",
        resource_id=deviation.id,
        extra={"fields": sorted(payload.model_dump(exclude_unset=True).keys())},
    )
    return await _get_deviation(db, deviation.id)


# ───────────────────────── 偏差：流转 / 延期 / 删除 ─────────────────────────


def _investigation_missing(deviation: Deviation) -> list[str]:
    """调查结论字段；提交评估和关闭时都要复核，避免进入评估后被清空。"""
    missing: list[str] = []
    if not (deviation.direct_cause or "").strip():
        missing.append("直接原因")
    if not (deviation.root_cause or "").strip():
        missing.append("根本原因")
    if not deviation.root_cause_category:
        missing.append("根本原因分类")
    if not deviation.why_chain:
        missing.append("5Why 分析")
    return missing


def _missing_before(deviation: Deviation, target: DeviationStatus) -> list[str]:
    """进入目标状态前必须补齐的字段（SOP 各部分的必填项）。"""
    missing: list[str] = []
    if target == DeviationStatus.INVESTIGATING:
        if not (deviation.description or "").strip():
            missing.append("偏差描述")
    elif target == DeviationStatus.ASSESSING:
        missing.extend(_investigation_missing(deviation))
    elif target == DeviationStatus.CLOSED:
        missing.extend(_investigation_missing(deviation))
        if not deviation.quality_impact:
            missing.append("对质量的影响结论")
        if not deviation.classification:
            missing.append("偏差分类")
        if deviation.capa_initiated is None:
            missing.append("是否发起 CAPA")
        elif (
            deviation.capa_initiated is False
            and not (deviation.capa_not_initiated_reason or "").strip()
        ):
            missing.append("不发起 CAPA 的原因")
        if deviation.is_repeat and not deviation.repeat_deviation_ids:
            missing.append("重复偏差关联的事件编号")
    return missing


async def transition_deviation(
    db: AsyncSession,
    deviation_id: uuid.UUID,
    payload: DeviationTransitionIn,
    user: User | None,
) -> Deviation:
    deviation = await _get_deviation(db, deviation_id, for_update=True)
    target = _DEVIATION_ACTION_TARGET[payload.action]
    validate_transition(
        deviation.status, target.value, DEVIATION_TRANSITIONS, DEVIATION_STATUS_LABELS
    )
    missing = _missing_before(deviation, target)
    if missing:
        raise AppException(
            status_code=422,
            message=f"进入「{DEVIATION_STATUS_LABELS[target.value]}」前需补齐：{'、'.join(missing)}",
        )
    if target == DeviationStatus.CLOSED and deviation.capa_initiated is True:
        if not await repo.list_capas_for_deviation(db, deviation.id):
            raise AppException(
                status_code=422,
                message="已勾选发起 CAPA，但尚未创建对应的 CAPA 记录",
            )

    old_status = deviation.status
    now = app_time.now()
    deviation.status = target.value
    if target == DeviationStatus.INVESTIGATING:
        deviation.investigating_at = now
    elif target == DeviationStatus.ASSESSING:
        deviation.assessing_at = now
    elif target == DeviationStatus.CLOSED:
        deviation.closed_at = now
    deviation.updated_by = _actor_id(user)
    await _log_deviation(
        db,
        deviation,
        action=payload.action,
        user=user,
        from_status=old_status,
        to_status=target.value,
        comment=payload.comment,
    )
    await _audit(
        db,
        action=f"deviation.{payload.action}",
        user=user,
        resource_type="deviation",
        resource_id=deviation.id,
        old_value={"status": old_status},
        new_value={"status": target.value},
    )
    await db.flush()
    return await _get_deviation(db, deviation.id)


async def extend_deviation(
    db: AsyncSession,
    deviation_id: uuid.UUID,
    payload: DeviationExtendIn,
    user: User | None,
) -> Deviation:
    deviation = await _get_deviation(db, deviation_id, for_update=True)
    _ensure_deviation_editable(deviation)
    if payload.new_due_date <= deviation.due_date:
        raise AppException(status_code=422, message="新的关闭期限必须晚于当前期限")
    old_due = deviation.due_date
    deviation.due_date = payload.new_due_date
    deviation.extension_count += 1
    deviation.updated_by = _actor_id(user)
    await _log_deviation(
        db,
        deviation,
        action="extend",
        user=user,
        from_status=deviation.status,
        to_status=deviation.status,
        comment=f"关闭期限 {old_due.isoformat()} → {payload.new_due_date.isoformat()}：{payload.reason}",
    )
    await _audit(
        db,
        action="deviation.extend",
        user=user,
        resource_type="deviation",
        resource_id=deviation.id,
        old_value={"due_date": old_due.isoformat()},
        new_value={
            "due_date": payload.new_due_date.isoformat(),
            "reason": payload.reason,
        },
    )
    await db.flush()
    return await _get_deviation(db, deviation.id)


async def delete_deviation(
    db: AsyncSession, deviation_id: uuid.UUID, user: User | None
) -> None:
    deviation = await _get_deviation(db, deviation_id, for_update=True)
    if deviation.status != DeviationStatus.DRAFT.value:
        raise AppException(status_code=409, message="仅登记中的偏差可以删除")
    if await repo.list_capas_for_deviation(db, deviation.id):
        raise AppException(status_code=409, message="偏差已关联 CAPA，不能删除")
    actor = _actor_id(user)
    deviation.is_deleted = True
    deviation.updated_by = actor
    for item in await repo.get_items(db, deviation.id):
        item.is_deleted = True
    for test in await repo.get_hypothesis_tests(db, deviation.id):
        test.is_deleted = True
    attachments = await repo.get_attachments(db, deviation.id)
    for attachment in attachments:
        attachment.is_deleted = True
    await _audit(
        db,
        action="deviation.delete",
        user=user,
        resource_type="deviation",
        resource_id=deviation.id,
        old_value={"deviation_no": deviation.deviation_no},
    )
    await db.flush()
    # 行与对象一起清理，否则软删的附件文件会永久残留在存储里。
    for attachment in attachments:
        await asyncio.to_thread(file_service.delete_file, attachment.storage_key)


# ───────────────────────── 偏差：附件 ─────────────────────────

ATTACHMENT_MAX_SIZE = 20 * 1024 * 1024
_ATTACHMENT_MIME = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _safe_attachment_name(filename: str | None) -> str:
    value = (filename or "attachment").replace("\\", "/").rsplit("/", 1)[-1]
    value = re.sub(r"[^\w.()\-\u4e00-\u9fff ]", "_", value).strip()
    return value[:255] or "attachment"


def _zip_has(data: bytes, member_prefix: str) -> bool:
    if not data.startswith(b"PK"):
        return False
    try:
        with ZipFile(BytesIO(data)) as archive:
            names = set(archive.namelist())
    except (BadZipFile, OSError):
        return False
    return "[Content_Types].xml" in names and any(
        name.startswith(member_prefix) for name in names
    )


def _attachment_magic_ok(extension: str, data: bytes) -> bool:
    if extension == ".pdf":
        return data.startswith(b"%PDF-")
    if extension in {".doc", ".xls"}:
        return data.startswith(_OLE_MAGIC)
    if extension == ".docx":
        return _zip_has(data, "word/")
    if extension == ".xlsx":
        return _zip_has(data, "xl/")
    if extension in {".jpg", ".jpeg"}:
        return data.startswith(b"\xff\xd8\xff")
    if extension == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    return False


def validate_attachment(
    filename: str | None, content_type: str | None, data: bytes
) -> tuple[str, str, str]:
    """返回 (安全文件名, 不带点的扩展名, MIME)。"""
    safe_name = _safe_attachment_name(filename)
    extension = Path(safe_name).suffix.lower()
    if extension not in _ATTACHMENT_MIME:
        raise AppException(
            status_code=422, message="仅支持 PDF、Word、Excel、JPG、PNG 附件"
        )
    if not data:
        raise AppException(status_code=422, message="附件不能为空")
    if len(data) > ATTACHMENT_MAX_SIZE:
        raise AppException(status_code=422, message="附件大小不能超过 20MB")
    if not _attachment_magic_ok(extension, data):
        raise AppException(
            status_code=422, message="附件内容与扩展名不匹配或文件已损坏"
        )
    return safe_name, extension[1:], _ATTACHMENT_MIME[extension]


async def add_attachment(
    db: AsyncSession,
    deviation_id: uuid.UUID,
    *,
    filename: str | None,
    content_type: str | None,
    data: bytes,
    user: User | None,
) -> DeviationAttachment:
    deviation = await _get_deviation(db, deviation_id, for_update=True)
    _ensure_deviation_editable(deviation)
    safe_name, extension, mime = validate_attachment(filename, content_type, data)
    key = f"deviations/{deviation.id}/{uuid.uuid4().hex}.{extension}"
    # MinIO/本地写盘是阻塞调用，放进线程池避免占住事件循环。
    await asyncio.to_thread(file_service.store_object, key, data, mime)
    try:
        attachment = DeviationAttachment(
            deviation_id=deviation.id,
            file_name=safe_name,
            storage_key=key,
            mime_type=mime,
            file_size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            uploaded_by_name=_actor_name(user),
            created_by=_actor_id(user),
            updated_by=_actor_id(user),
        )
        db.add(attachment)
        await db.flush()
    except Exception:
        file_service.cleanup_stored_file(key)
        raise
    await _audit(
        db,
        action="deviation.attachment.add",
        user=user,
        resource_type="deviation",
        resource_id=deviation.id,
        new_value={"file_name": safe_name, "sha256": attachment.sha256},
    )
    # 重新查询以加载 server_default 的 created_at，避免序列化时懒加载。
    stored = await repo.get_attachment(db, deviation.id, attachment.id)
    assert stored is not None
    return stored


async def read_attachment(
    db: AsyncSession, deviation_id: uuid.UUID, attachment_id: uuid.UUID
) -> tuple[DeviationAttachment, bytes, str]:
    attachment = await repo.get_attachment(db, deviation_id, attachment_id)
    if attachment is None:
        raise NotFoundException("附件", str(attachment_id))
    stored = await asyncio.to_thread(file_service.read_object, attachment.storage_key)
    if stored is None:
        raise NotFoundException("附件文件", attachment.file_name)
    data, _ = stored
    return attachment, data, attachment.mime_type


async def delete_attachment(
    db: AsyncSession,
    deviation_id: uuid.UUID,
    attachment_id: uuid.UUID,
    user: User | None,
) -> None:
    deviation = await _get_deviation(db, deviation_id, for_update=True)
    _ensure_deviation_editable(deviation)
    attachment = await repo.get_attachment(db, deviation_id, attachment_id)
    if attachment is None:
        raise NotFoundException("附件", str(attachment_id))
    attachment.is_deleted = True
    attachment.updated_by = _actor_id(user)
    await db.flush()
    await asyncio.to_thread(file_service.delete_file, attachment.storage_key)
    await _audit(
        db,
        action="deviation.attachment.delete",
        user=user,
        resource_type="deviation",
        resource_id=deviation.id,
        old_value={"file_name": attachment.file_name},
    )


# ───────────────────────── 偏差：查询与序列化 ─────────────────────────


def _reported_late(deviation: Deviation) -> bool:
    """只记录发现日期不记录时刻，登记日晚于发现日次日即视为超过 24 小时。"""
    registered_on = deviation.created_at.astimezone(app_time.APP_TZ).date()
    return registered_on > deviation.discovery_date + timedelta(days=1)


def deviation_brief(
    deviation: Deviation, *, today: date | None = None
) -> dict[str, Any]:
    today = today or app_time.today()
    is_open = deviation.status != DeviationStatus.CLOSED.value
    return {
        "id": str(deviation.id),
        "deviation_no": deviation.deviation_no,
        "status": deviation.status,
        "discovery_date": deviation.discovery_date.isoformat(),
        "occurrence_date": (
            deviation.occurrence_date.isoformat() if deviation.occurrence_date else None
        ),
        "due_date": deviation.due_date.isoformat(),
        "days_remaining": (deviation.due_date - today).days if is_open else None,
        "is_overdue": is_open and deviation.due_date < today,
        "reported_late": _reported_late(deviation),
        "department_name": deviation.department_name,
        "group_name": deviation.group_name,
        "reporter_name": deviation.reporter_name,
        "qa_person_name": deviation.qa_person_name,
        "description": deviation.description,
        "classification": deviation.classification,
        "root_cause_category": deviation.root_cause_category,
        "quality_impact": deviation.quality_impact,
        "is_repeat": deviation.is_repeat,
        "capa_initiated": deviation.capa_initiated,
        "extension_count": deviation.extension_count,
        "closed_at": deviation.closed_at.isoformat() if deviation.closed_at else None,
        "created_at": deviation.created_at.isoformat(),
        "updated_at": deviation.updated_at.isoformat(),
    }


def _item_to_dict(item: DeviationItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "category": item.category,
        "name": item.name,
        "batch_no": item.batch_no,
        "handling": item.handling,
    }


def _hypothesis_to_dict(test: DeviationHypothesisTest) -> dict[str, Any]:
    return {
        "id": str(test.id),
        "sample": test.sample,
        "hypothesis": test.hypothesis,
        "protocol": test.protocol,
        "expected": test.expected,
        "result": test.result,
        "conclusion": test.conclusion,
        "tested_by": test.tested_by,
        "tested_at": test.tested_at.isoformat() if test.tested_at else None,
    }


def _log_to_dict(log: DeviationStatusLog | CapaStatusLog) -> dict[str, Any]:
    return {
        "id": str(log.id),
        "action": log.action,
        "from_status": log.from_status,
        "to_status": log.to_status,
        "operator_name": log.operator_name,
        "comment": log.comment,
        "created_at": log.created_at.isoformat(),
    }


def attachment_to_dict(attachment: DeviationAttachment) -> dict[str, Any]:
    return {
        "id": str(attachment.id),
        "file_name": attachment.file_name,
        "mime_type": attachment.mime_type,
        "file_size": attachment.file_size,
        "sha256": attachment.sha256,
        "uploaded_by_name": attachment.uploaded_by_name,
        "created_at": attachment.created_at.isoformat(),
    }


async def list_deviation_page(
    db: AsyncSession, **filters: Any
) -> tuple[list[dict[str, Any]], int]:
    today = app_time.today()
    rows, total = await repo.list_deviations(db, today=today, **filters)
    return [deviation_brief(row, today=today) for row in rows], total


async def deviation_status_summary(db: AsyncSession) -> dict[str, int]:
    counts = await repo.count_deviations_by_status(db)
    return {status.value: counts.get(status.value, 0) for status in DeviationStatus}


async def deviation_detail(db: AsyncSession, deviation_id: uuid.UUID) -> dict[str, Any]:
    deviation = await _get_deviation(db, deviation_id)
    today = app_time.today()
    data = deviation_brief(deviation, today=today)
    data.update(
        {
            "emergency_measures": deviation.emergency_measures,
            "remark": deviation.remark,
            "department_id": deviation.department_id,
            "m1e_personnel": deviation.m1e_personnel,
            "m1e_machine": deviation.m1e_machine,
            "m1e_material": deviation.m1e_material,
            "m1e_method": deviation.m1e_method,
            "m1e_environment": deviation.m1e_environment,
            "m1e_other": deviation.m1e_other,
            "direct_cause": deviation.direct_cause,
            "root_cause": deviation.root_cause,
            "why_chain": deviation.why_chain or [],
            "extended_investigation": deviation.extended_investigation,
            "extended_result": deviation.extended_result,
            "quality_impact_reason": deviation.quality_impact_reason,
            "stability_needed": deviation.stability_needed,
            "stability_note": deviation.stability_note,
            "validation_impact": deviation.validation_impact,
            "validation_note": deviation.validation_note,
            "registration_impact": deviation.registration_impact,
            "registration_note": deviation.registration_note,
            "notify_customer": deviation.notify_customer,
            "customer_note": deviation.customer_note,
            "repeat_deviation_ids": deviation.repeat_deviation_ids or [],
            "capa_not_initiated_reason": deviation.capa_not_initiated_reason,
            "investigating_at": (
                deviation.investigating_at.isoformat()
                if deviation.investigating_at
                else None
            ),
            "assessing_at": deviation.assessing_at.isoformat()
            if deviation.assessing_at
            else None,
            "items": [_item_to_dict(i) for i in await repo.get_items(db, deviation.id)],
            "hypothesis_tests": [
                _hypothesis_to_dict(t)
                for t in await repo.get_hypothesis_tests(db, deviation.id)
            ],
            "logs": [
                _log_to_dict(log)
                for log in await repo.get_status_logs(db, deviation.id)
            ],
            "attachments": [
                attachment_to_dict(a)
                for a in await repo.get_attachments(db, deviation.id)
            ],
            "capas": [
                capa_brief(c)
                for c in await repo.list_capas_for_deviation(db, deviation.id)
            ],
            "repeat_candidates": [
                {
                    "id": str(c.id),
                    "deviation_no": c.deviation_no,
                    "status": c.status,
                    "discovery_date": c.discovery_date.isoformat(),
                    "description": c.description,
                }
                for c in await repo.find_repeat_candidates(db, deviation)
            ],
            "missing_for_next": _missing_for_next(deviation),
        }
    )
    return data


def _missing_for_next(deviation: Deviation) -> list[str]:
    nexts = DEVIATION_TRANSITIONS.get(deviation.status, [])
    if not nexts:
        return []
    return _missing_before(deviation, DeviationStatus(nexts[0]))


# ───────────────────────── CAPA ─────────────────────────


async def _get_capa(
    db: AsyncSession, capa_id: uuid.UUID, *, for_update: bool = False
) -> Capa:
    capa = await repo.get_capa(db, capa_id, for_update=for_update)
    if capa is None:
        raise NotFoundException("CAPA", str(capa_id))
    return capa


def _ensure_capa_editable(capa: Capa) -> None:
    if capa.status == CapaStatus.CLOSED.value:
        raise AppException(status_code=409, message="CAPA 已关闭，不能再修改")


async def _log_capa(
    db: AsyncSession,
    capa: Capa,
    *,
    action: str,
    user: User | None,
    from_status: str | None,
    to_status: str | None,
    comment: str | None = None,
) -> None:
    db.add(
        CapaStatusLog(
            capa_id=capa.id,
            from_status=from_status,
            to_status=to_status,
            action=action,
            operator_id=_actor_id(user),
            operator_name=_actor_name(user),
            comment=comment,
            created_by=_actor_id(user),
            updated_by=_actor_id(user),
        )
    )


async def _replace_actions(
    db: AsyncSession, capa_id: uuid.UUID, actions: list[CapaActionIn], user: User | None
) -> None:
    for existing in await repo.get_capa_actions(db, capa_id):
        existing.is_deleted = True
        existing.updated_by = _actor_id(user)
    for index, action in enumerate(actions):
        actual_date = action.actual_date
        if action.status == CapaActionStatus.DONE and actual_date is None:
            actual_date = app_time.today()
        db.add(
            CapaAction(
                capa_id=capa_id,
                content=action.content,
                action_type=action.action_type.value,
                department_name=action.department_name,
                owner_name=action.owner_name,
                planned_date=action.planned_date,
                actual_date=actual_date,
                status=action.status.value,
                note=action.note,
                sort_order=index,
                created_by=_actor_id(user),
                updated_by=_actor_id(user),
            )
        )


async def create_capa(db: AsyncSession, payload: CapaCreate, user: User | None) -> Capa:
    deviation = await _get_deviation(db, payload.deviation_id, for_update=True)
    if payload.parent_capa_id is not None:
        parent = await _get_capa(db, payload.parent_capa_id)
        if parent.deviation_id != deviation.id:
            raise AppException(
                status_code=422, message="追加 CAPA 必须与上游 CAPA 属于同一偏差"
            )

    base_no = f"CAPA-{deviation.deviation_no}"
    serial = await repo.count_capas_for_deviation(db, deviation.id)
    capa: Capa | None = None
    for attempt in range(_MAX_NO_RETRIES):
        candidate = Capa(
            capa_no=base_no if serial == 0 else f"{base_no}-{serial + 1}",
            deviation_id=deviation.id,
            parent_capa_id=payload.parent_capa_id,
            severity=payload.severity.value,
            status=CapaStatus.PLANNED.value,
            summary=payload.summary,
            responsible_department_name=payload.responsible_department_name,
            planned_completion_date=payload.planned_completion_date,
            effect_method=payload.effect_method.value
            if payload.effect_method
            else None,
            effect_plan=payload.effect_plan,
            effect_due_date=payload.effect_due_date,
            remark=payload.remark,
            created_by=_actor_id(user),
            updated_by=_actor_id(user),
        )
        try:
            async with db.begin_nested():
                db.add(candidate)
                await db.flush()
        except IntegrityError as exc:
            if "uq_qa_capas_no" not in str(exc):
                raise
            serial += 1
            if attempt < _MAX_NO_RETRIES - 1:
                continue
            raise AppException(message="CAPA 编号生成失败，请重试") from None
        capa = candidate
        break
    assert capa is not None

    await _replace_actions(db, capa.id, payload.actions, user)
    # 发起 CAPA 即落实偏差评估里的「是否发起 CAPA」决定。
    if (
        deviation.capa_initiated is not True
        and deviation.status != DeviationStatus.CLOSED.value
    ):
        deviation.capa_initiated = True
        deviation.capa_not_initiated_reason = None
    await _log_capa(
        db, capa, action="create", user=user, from_status=None, to_status=capa.status
    )
    await _audit(
        db,
        action="capa.create",
        user=user,
        resource_type="capa",
        resource_id=capa.id,
        new_value={"capa_no": capa.capa_no, "deviation_no": deviation.deviation_no},
    )
    await db.flush()
    return await _get_capa(db, capa.id)


async def update_capa(
    db: AsyncSession, capa_id: uuid.UUID, payload: CapaUpdate, user: User | None
) -> Capa:
    capa = await _get_capa(db, capa_id, for_update=True)
    _ensure_capa_editable(capa)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise AppException(message="没有需要更新的字段")
    actions = data.pop("actions", None)
    for field, value in data.items():
        setattr(capa, field, value.value if hasattr(value, "value") else value)
    if "effect_conclusion" in data:
        capa.evaluated_at = app_time.now() if capa.effect_conclusion else None
    if actions is not None:
        await _replace_actions(db, capa.id, payload.actions or [], user)
    capa.updated_by = _actor_id(user)
    await db.flush()
    await _audit(
        db,
        action="capa.update",
        user=user,
        resource_type="capa",
        resource_id=capa.id,
        extra={"fields": sorted(payload.model_dump(exclude_unset=True).keys())},
    )
    return await _get_capa(db, capa.id)


async def patch_capa_action(
    db: AsyncSession,
    capa_id: uuid.UUID,
    action_id: uuid.UUID,
    payload: CapaActionPatch,
    user: User | None,
) -> Capa:
    capa = await _get_capa(db, capa_id, for_update=True)
    _ensure_capa_editable(capa)
    action = await repo.get_capa_action(db, capa.id, action_id)
    if action is None:
        raise NotFoundException("CAPA 措施", str(action_id))
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise AppException(message="没有需要更新的字段")
    for field, value in data.items():
        setattr(action, field, value.value if hasattr(value, "value") else value)
    if action.status == CapaActionStatus.DONE.value and action.actual_date is None:
        action.actual_date = app_time.today()
    action.updated_by = _actor_id(user)
    await db.flush()
    await _audit(
        db,
        action="capa.action.update",
        user=user,
        resource_type="capa",
        resource_id=capa.id,
        new_value={"action_id": str(action.id), "status": action.status},
    )
    return await _get_capa(db, capa.id)


async def transition_capa(
    db: AsyncSession, capa_id: uuid.UUID, payload: CapaTransitionIn, user: User | None
) -> Capa:
    capa = await _get_capa(db, capa_id, for_update=True)
    target = _CAPA_ACTION_TARGET[payload.action]
    validate_transition(capa.status, target.value, CAPA_TRANSITIONS, CAPA_STATUS_LABELS)
    actions = await repo.get_capa_actions(db, capa.id)

    if target == CapaStatus.IN_PROGRESS and not actions:
        raise AppException(status_code=422, message="请先填写至少一条 CAPA 措施")
    if target == CapaStatus.COMPLETED:
        unfinished = [a for a in actions if a.status != CapaActionStatus.DONE.value]
        if not actions or unfinished:
            raise AppException(
                status_code=422,
                message=f"还有 {len(unfinished)} 条措施未完成，不能标记措施完成",
            )
    if target == CapaStatus.EFFECT_EVALUATING and not capa.effect_method:
        raise AppException(
            status_code=422, message="请先填写有效性评估方案（评估方式）"
        )
    if target == CapaStatus.CLOSED:
        if capa.effect_conclusion == EffectConclusion.INEFFECTIVE.value:
            raise AppException(
                status_code=422,
                message="有效性评估结论为「无效」，不能关闭；请发起追加 CAPA 并继续跟踪",
            )
        if capa.effect_conclusion != EffectConclusion.EFFECTIVE.value:
            raise AppException(status_code=422, message="请先填写有效性评估结论")
        if not (capa.effect_result or "").strip():
            raise AppException(status_code=422, message="请先填写回顾评估结果")

    old_status = capa.status
    now = app_time.now()
    capa.status = target.value
    if target == CapaStatus.IN_PROGRESS:
        capa.in_progress_at = now
    elif target == CapaStatus.COMPLETED:
        capa.completed_at = now
        if capa.effect_due_date is None and capa.effect_method in _EFFECT_DEFAULT_DAYS:
            latest = max(
                (a.actual_date for a in actions if a.actual_date),
                default=app_time.today(),
            )
            capa.effect_due_date = latest + timedelta(
                days=_EFFECT_DEFAULT_DAYS[capa.effect_method]
            )
    elif target == CapaStatus.EFFECT_EVALUATING:
        capa.evaluating_at = now
    elif target == CapaStatus.CLOSED:
        capa.closed_at = now
        if capa.evaluated_at is None:
            capa.evaluated_at = now
    capa.updated_by = _actor_id(user)
    await _log_capa(
        db,
        capa,
        action=payload.action,
        user=user,
        from_status=old_status,
        to_status=target.value,
        comment=payload.comment,
    )
    await _audit(
        db,
        action=f"capa.{payload.action}",
        user=user,
        resource_type="capa",
        resource_id=capa.id,
        old_value={"status": old_status},
        new_value={"status": target.value},
    )
    await db.flush()
    return await _get_capa(db, capa.id)


def capa_brief(capa: Capa, *, today: date | None = None) -> dict[str, Any]:
    today = today or app_time.today()
    is_open = capa.status != CapaStatus.CLOSED.value
    return {
        "id": str(capa.id),
        "capa_no": capa.capa_no,
        "deviation_id": str(capa.deviation_id),
        "parent_capa_id": str(capa.parent_capa_id) if capa.parent_capa_id else None,
        "severity": capa.severity,
        "status": capa.status,
        "summary": capa.summary,
        "responsible_department_name": capa.responsible_department_name,
        "planned_completion_date": (
            capa.planned_completion_date.isoformat()
            if capa.planned_completion_date
            else None
        ),
        "is_overdue": (
            is_open
            and capa.status in (CapaStatus.PLANNED.value, CapaStatus.IN_PROGRESS.value)
            and capa.planned_completion_date is not None
            and capa.planned_completion_date < today
        ),
        "effect_method": capa.effect_method,
        "effect_due_date": capa.effect_due_date.isoformat()
        if capa.effect_due_date
        else None,
        "effect_conclusion": capa.effect_conclusion,
        "completed_at": capa.completed_at.isoformat() if capa.completed_at else None,
        "closed_at": capa.closed_at.isoformat() if capa.closed_at else None,
        "created_at": capa.created_at.isoformat(),
        "updated_at": capa.updated_at.isoformat(),
    }


def _action_to_dict(action: CapaAction) -> dict[str, Any]:
    return {
        "id": str(action.id),
        "content": action.content,
        "action_type": action.action_type,
        "department_name": action.department_name,
        "owner_name": action.owner_name,
        "planned_date": action.planned_date.isoformat()
        if action.planned_date
        else None,
        "actual_date": action.actual_date.isoformat() if action.actual_date else None,
        "status": action.status,
        "note": action.note,
    }


async def list_capa_page(
    db: AsyncSession, **filters: Any
) -> tuple[list[dict[str, Any]], int]:
    today = app_time.today()
    rows, total = await repo.list_capas(db, **filters)
    deviations = {
        d.id: d
        for d in await repo.get_deviations_by_ids(db, [r.deviation_id for r in rows])
    }
    result = []
    for row in rows:
        data = capa_brief(row, today=today)
        source = deviations.get(row.deviation_id)
        data["deviation_no"] = source.deviation_no if source else None
        result.append(data)
    return result, total


async def capa_status_summary(db: AsyncSession) -> dict[str, int]:
    counts = await repo.count_capas_by_status(db)
    return {status.value: counts.get(status.value, 0) for status in CapaStatus}


async def capa_detail(db: AsyncSession, capa_id: uuid.UUID) -> dict[str, Any]:
    capa = await _get_capa(db, capa_id)
    data = capa_brief(capa)
    deviation = await repo.get_deviation(db, capa.deviation_id)
    parent = (
        await repo.get_capa(db, capa.parent_capa_id) if capa.parent_capa_id else None
    )
    siblings = await repo.list_capas_for_deviation(db, capa.deviation_id)
    data.update(
        {
            "effect_plan": capa.effect_plan,
            "effect_result": capa.effect_result,
            "evaluated_at": capa.evaluated_at.isoformat()
            if capa.evaluated_at
            else None,
            "remark": capa.remark,
            "in_progress_at": capa.in_progress_at.isoformat()
            if capa.in_progress_at
            else None,
            "evaluating_at": capa.evaluating_at.isoformat()
            if capa.evaluating_at
            else None,
            "deviation": (
                {
                    "id": str(deviation.id),
                    "deviation_no": deviation.deviation_no,
                    "status": deviation.status,
                    "description": deviation.description,
                    "department_name": deviation.department_name,
                }
                if deviation
                else None
            ),
            "parent_capa_no": parent.capa_no if parent else None,
            "follow_up_capas": [
                {"id": str(c.id), "capa_no": c.capa_no, "status": c.status}
                for c in siblings
                if c.parent_capa_id == capa.id
            ],
            "actions": [
                _action_to_dict(a) for a in await repo.get_capa_actions(db, capa.id)
            ],
            "logs": [
                _log_to_dict(log)
                for log in await repo.get_capa_status_logs(db, capa.id)
            ],
        }
    )
    return data
