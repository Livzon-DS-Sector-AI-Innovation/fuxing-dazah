"""新员工信息收集（飞书机器人表单卡片 → HR 审核合并档案）。

数据流：HR 发起 → 平台 send_user_card 私发表单卡片 → 员工飞书内提交 →
平台 WS 长连接 card.action.trigger（payload 附 _form_value/_open_id，见
平台 event_handler）→ 本模块回调 upsert 收集记录 → HR 审核：
- 采纳：先写飞书 Base 源表（员工档案唯一权威源，同步链路拉回；绕开
  同步启用时 employees 全表只读的限制），再按相同值预更新本地档案；
- 驳回：记录原因并重发新卡片（同一记录状态回滚为 sent，可重填）。

字段范围 = Employee 已有字段核心集（一期决策，无加列）。
"""

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.employee_sync.config import load_config
from app.modules.hr.employee_sync.mapping import COLUMN_MAP
from app.modules.hr.models import Employee, EmployeeInfoCollection

logger = logging.getLogger(__name__)

# 卡片提交按钮的 action 标识（平台注册表 key）
CARD_ACTION = "employee_info_submit"


# ═══════════════════════════════════════════════════════════════
# 自填字段定义（卡片控件 + 校验）
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True, slots=True)
class FillField:
    field: str          # Employee ORM 字段
    label: str          # 卡片上显示的中文标签
    kind: str           # input / textarea / select / date
    required: bool = True
    options: tuple[str, ...] = ()

    @property
    def is_date(self) -> bool:
        return self.kind == "date"


FILL_FIELDS: tuple[FillField, ...] = (
    FillField("id_card", "身份证号", "input"),
    FillField("phone", "联系电话", "input"),
    FillField("education", "学历", "select",
              options=("博士研究生", "硕士研究生", "本科", "大专", "中专", "高中", "其他")),
    FillField("degree_type", "学位类型", "select",
              options=("博士", "硕士", "学士", "无")),
    FillField("school", "毕业院校", "input"),
    FillField("major", "专业", "input"),
    FillField("graduation_date", "毕业时间", "date", required=False),
    FillField("native_place", "籍贯", "input", required=False),
    FillField("ethnicity", "民族", "input", required=False),
    FillField("marital_status", "婚姻状况", "select", required=False,
              options=("未婚", "已婚", "离异", "丧偶")),
    FillField("household_type", "户籍类型", "input", required=False),
    FillField("current_address", "现居住地址", "textarea", required=False),
    FillField("emergency_contact_name", "紧急联系人姓名", "input"),
    FillField("emergency_contact_phone", "紧急联系人电话", "input"),
    FillField("emergency_contact_relation", "紧急联系人关系", "input", required=False),
)
_FIELD_MAP = {f.field: f for f in FILL_FIELDS}
_FIELD_LABELS = {f.field: f.label for f in FILL_FIELDS}

_RE_ID_CARD = re.compile(r"^\d{17}[\dXx]$")
_RE_PHONE = re.compile(r"^1\d{10}$")


def _validate_form(form_value: dict[str, Any]) -> list[str]:
    """校验员工提交值，返回错误提示列表（空 = 通过）。"""
    errors: list[str] = []
    for f in FILL_FIELDS:
        raw = (form_value.get(f.field) or "").strip() if isinstance(form_value.get(f.field), str) else form_value.get(f.field)
        val = (raw or "").strip() if isinstance(raw, str) else raw
        if not val:
            if f.required:
                errors.append(f"「{f.label}」未填写")
            continue
        if f.field == "id_card" and not _RE_ID_CARD.match(str(val)):
            errors.append("身份证号应为 18 位（结尾可为 X）")
        if f.field in ("phone", "emergency_contact_phone") and not _RE_PHONE.match(str(val)):
            errors.append(f"「{f.label}」应为 11 位手机号")
        if f.is_date:
            try:
                date.fromisoformat(str(val)[:10])
            except ValueError:
                errors.append(f"「{f.label}」日期格式不正确")
    return errors


def _clean_form(form_value: dict[str, Any]) -> dict[str, Any]:
    """白名单过滤 + 字符串去空白，返回 {orm字段: 值}。"""
    cleaned: dict[str, Any] = {}
    for f in FILL_FIELDS:
        val = form_value.get(f.field)
        if val is None:
            continue
        if isinstance(val, str):
            val = val.strip()
            if not val:
                continue
        cleaned[f.field] = str(val)[:10] if f.is_date else val
    return cleaned


# ═══════════════════════════════════════════════════════════════
# 卡片构造
# ═══════════════════════════════════════════════════════════════

def _label(text: str) -> dict:
    return {"tag": "plain_text", "content": text}


def _build_fill_card(collection: EmployeeInfoCollection, employee: Employee,
                     *, reject_reason: str | None = None) -> dict:
    """构造信息登记表单卡片（schema 2.0 form 容器，按钮 value 带任务定位）。"""
    elements: list[dict] = []
    if reject_reason:
        elements.append({
            "tag": "markdown",
            "content": f"**上次提交被驳回**：{reject_reason}\n请核对后重新填写提交。",
        })
    elements.append({
        "tag": "markdown",
        "content": (
            f"**{employee.name}** 您好，请完善个人档案信息（带 * 为必填）。\n"
            "信息仅人事审核人员可见，用于建立员工档案。"
        ),
    })
    form_elements: list[dict] = []
    for f in FILL_FIELDS:
        label_text = f.label + (" *" if f.required else "")
        # 统一用 input 组件：卡片 2.0 的 select_static / date_picker 不支持
        # label 属性（服务端解析卡片 JSON 直接拒绝，ErrCode 200621），
        # 选项值/日期格式放 placeholder 提示，值域由后端 _validate_form 把关
        placeholder: dict | None = None
        if f.kind == "select":
            placeholder = _label(f"填：{' / '.join(f.options)}")
        elif f.kind == "date":
            placeholder = _label("格式 2020-06-30，可不填" if not f.required else "格式 2020-06-30")
        form_elements.append({
            "tag": "input", "name": f.field, "label": _label(label_text),
            "required": f.required,
            "placeholder": placeholder,
            "max_length": 18 if f.field == "id_card" else (32 if f.kind == "date" else 120 if f.kind == "textarea" else 64),
        })
    form_elements.append({
        "tag": "button", "action_type": "form_submit", "name": "submit",
        "text": {"tag": "lark_md", "content": "**提交**"}, "type": "primary",
        "value": {"action": CARD_ACTION, "collection_id": str(collection.id)},
    })
    elements.append({"tag": "form", "name": "employee_info_form", "elements": form_elements})
    return {
        "schema": "2.0",
        "header": {"title": _label("新员工信息登记"), "template": "blue"},
        "body": {"elements": elements},
    }


def _build_submitted_notice(name: str) -> dict:
    """提交后私发的确认卡片（旧表单卡片保留可改可重交，覆盖语义）。"""
    return {
        "schema": "2.0",
        "header": {"title": _label("信息已提交"), "template": "green"},
        "body": {"elements": [{
            "tag": "markdown",
            "content": (
                f"**{name}** 您好，信息已收到，等待人事确认。\n\n"
                "- 如需修改，可直接在原表单卡片修改后重新提交（以最后一次为准）\n"
                "- 若被驳回，会重新收到填写卡片并附驳回原因"
            ),
        }]},
    }


async def _send_card(open_id: str, card: dict) -> bool:
    from app.platform.integrations.feishu.notification import send_user_card

    try:
        return await send_user_card(open_id, card=card)
    except Exception as e:  # noqa: BLE001
        logger.warning("发送信息收集卡片失败 open_id=%s: %s", open_id, e)
        return False


# ═══════════════════════════════════════════════════════════════
# 发起收集
# ═══════════════════════════════════════════════════════════════

async def _resolve_open_id(session: AsyncSession, employee: Employee) -> str | None:
    """优先员工档案 open_id（源表员工账号列），缺失时按姓名查 identity.users。"""
    if employee.feishu_open_id:
        return employee.feishu_open_id
    from app.modules.hr.feishu_review_service import _lookup_open_id

    return await _lookup_open_id(employee.name)


async def create_collections(
    session: AsyncSession, employee_ids: list[UUID], operator: str,
) -> dict:
    """批量发起信息收集：解析 open_id → 私发表单卡片 → 建任务记录。

    id 预生成（不依赖 flush），发送成功才落库——失败不污染事务，
    避免 rollback 误伤本轮已成功的记录。
    """
    created, skipped = 0, []
    for emp_id in employee_ids:
        employee = (await session.execute(
            select(Employee).where(Employee.id == emp_id, Employee.is_deleted.is_(False))
        )).scalar_one_or_none()
        if employee is None:
            skipped.append({"employee_id": str(emp_id), "reason": "员工不存在"})
            continue
        active = (await session.execute(
            select(EmployeeInfoCollection).where(
                EmployeeInfoCollection.employee_id == emp_id,
                EmployeeInfoCollection.status.in_(("sent", "submitted")),
                EmployeeInfoCollection.is_deleted.is_(False),
            )
        )).scalar_one_or_none()
        if active is not None:
            skipped.append({"name": employee.name, "reason": "已有进行中的收集任务"})
            continue
        open_id = await _resolve_open_id(session, employee)
        if not open_id:
            skipped.append({"name": employee.name, "reason": "未找到飞书账号（open_id），请先在源表补「员工账号」"})
            continue
        collection = EmployeeInfoCollection(
            id=uuid.uuid4(), employee_id=employee.id, open_id=open_id, status="sent",
        )
        if not await _send_card(open_id, _build_fill_card(collection, employee)):
            skipped.append({"name": employee.name, "reason": "卡片发送失败（机器人不可用或无权限）"})
            continue
        session.add(collection)
        created += 1
    await session.commit()
    return {"created": created, "skipped": skipped}


# ═══════════════════════════════════════════════════════════════
# 卡片提交回调（平台注册制）
# ═══════════════════════════════════════════════════════════════

async def handle_card_submit(payload: dict[str, Any], user_id: str) -> dict | None:
    """表单卡片提交回调：校验身份与字段 → upsert 待审核记录。

    平台 event_handler 在 payload 附加 _form_value（表单值）与 _open_id（提交人）。
    返回 toast dict 由平台转 P2CardActionTriggerResponse 回给飞书。
    """
    from app.core.database import async_session_factory

    def toast(kind: str, content: str) -> dict:
        return {"toast": {"type": kind, "content": content}}

    form_value = payload.get("_form_value") or {}
    open_id = payload.get("_open_id") or ""
    collection_id = payload.get("collection_id") or ""
    if not collection_id:
        return toast("error", "卡片数据缺失，请联系人事重新发送")

    async with async_session_factory() as session:
        collection = (await session.execute(
            select(EmployeeInfoCollection).where(
                EmployeeInfoCollection.id == UUID(collection_id),
                EmployeeInfoCollection.is_deleted.is_(False),
            )
        )).scalar_one_or_none()
        if collection is None or collection.status not in ("sent", "submitted"):
            return toast("error", "该信息收集任务不存在或已结束")
        # 防代填：提交人必须是卡片接收人
        if open_id and open_id != collection.open_id:
            return toast("error", "请使用收到卡片的飞书账号填写提交")

        errors = _validate_form(form_value)
        if errors:
            return toast("error", "；".join(errors[:3]))

        employee = (await session.execute(
            select(Employee).where(Employee.id == collection.employee_id)
        )).scalar_one_or_none()
        if employee is None:
            return toast("error", "员工档案不存在，请联系人事")

        collection.form_data = _clean_form(form_value)
        collection.status = "submitted"
        collection.submitted_at = datetime.now(timezone.utc)
        collection.reject_reason = None
        await session.commit()

    await _send_card(open_id, _build_submitted_notice(employee.name))
    return toast("success", "已提交，等待人事确认")


def register_feishu_callbacks() -> None:
    """main.py 启动接线：注册卡片提交 action 到平台分发注册表。"""
    from app.platform.integrations.feishu.event_handler import register_card_action_handler

    register_card_action_handler(CARD_ACTION, handle_card_submit)


# ═══════════════════════════════════════════════════════════════
# 列表与差异对比
# ═══════════════════════════════════════════════════════════════

def _fmt_current(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _build_diff(employee: Employee, form_data: dict[str, Any] | None) -> list[dict]:
    """逐字段对比：档案现值 vs 员工填写。"""
    diff = []
    for f in FILL_FIELDS:
        submitted = (form_data or {}).get(f.field)
        current = getattr(employee, f.field, None)
        # 身份证等敏感值完整返回（HR 审核需要核对）
        diff.append({
            "field": f.field,
            "label": f.label,
            "current": _fmt_current(current),
            "submitted": _fmt_current(submitted),
        })
    return diff


async def list_collections(session: AsyncSession, status: str | None = None) -> list[dict]:
    stmt = (
        select(EmployeeInfoCollection, Employee)
        .join(Employee, Employee.id == EmployeeInfoCollection.employee_id)
        .where(EmployeeInfoCollection.is_deleted.is_(False))
        .order_by(EmployeeInfoCollection.updated_at.desc())
    )
    if status:
        stmt = stmt.where(EmployeeInfoCollection.status == status)
    rows = (await session.execute(stmt)).all()
    return [{
        "id": str(c.id),
        "employee_id": str(e.id),
        "employee_name": e.name,
        "employee_number": e.employee_number,
        "department": e.department,
        "position": e.position,
        "status": c.status,
        "form_data": c.form_data,
        "diff": _build_diff(e, c.form_data),
        "reject_reason": c.reject_reason,
        "submitted_at": c.submitted_at.isoformat() if c.submitted_at else None,
        "reviewed_by": c.reviewed_by,
        "reviewed_at": c.reviewed_at.isoformat() if c.reviewed_at else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    } for c, e in rows]


# ═══════════════════════════════════════════════════════════════
# 审核：采纳（写源表）与驳回（重发卡片）
# ═══════════════════════════════════════════════════════════════

def _sync_creds() -> tuple[str | None, str | None]:
    """员工档案同步独立应用凭证（未配置返回 None，平台层回落全局）。"""
    from app.core.config import get_settings

    s = get_settings()
    return (
        s.HR_EMPLOYEE_SYNC_FEISHU_APP_ID or None,
        s.HR_EMPLOYEE_SYNC_FEISHU_APP_SECRET or None,
    )


def _match_source_column(field: str, available_cols: set[str]) -> str | None:
    """ORM 字段 → 源表实际列名（COLUMN_MAP 候选列按源表列集合自适配）。"""
    for col, f in COLUMN_MAP.items():
        if f == field and col in available_cols:
            return col
    return None


def _to_bitable_value(field: str, value: Any) -> Any:
    """ORM 值 → Base 写入格式（日期字段转毫秒时间戳）。"""
    fill = _FIELD_MAP.get(field)
    if fill and fill.is_date:
        d = date.fromisoformat(str(value)[:10])
        return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)
    return value


async def approve_collection(session: AsyncSession, collection_id: UUID, reviewer: str) -> dict:
    """采纳：写飞书 Base 源表（权威源）→ 同值预更新本地档案 → 任务完结。

    员工账号列顺带回填 open_id（源表该列当前全空，回填后消息推送不再依赖姓名反查）。
    """
    from app.platform.integrations.feishu import bitable as pb

    collection = (await session.execute(
        select(EmployeeInfoCollection).where(
            EmployeeInfoCollection.id == collection_id,
            EmployeeInfoCollection.is_deleted.is_(False),
        )
    )).scalar_one_or_none()
    if collection is None:
        raise ValueError("收集任务不存在")
    if collection.status != "submitted":
        raise ValueError("仅「已提交待审核」的任务可采纳")
    employee = (await session.execute(
        select(Employee).where(Employee.id == collection.employee_id)
    )).scalar_one()
    if not employee.feishu_record_id:
        raise ValueError(f"{employee.name} 无源表记录ID（feishu_record_id），无法定位源表行；请先执行一次员工同步")

    cfg = await load_config(session)
    if not cfg.is_ready:
        raise ValueError("员工档案同步未启用或未配置源表，无法合并")

    app_id, app_secret = _sync_creds()
    fields_meta = await pb.list_fields(
        cfg.app_token, cfg.source_table_id, app_id=app_id, app_secret=app_secret,
    )
    available = {f["field_name"] for f in fields_meta}

    payload_fields: dict[str, Any] = {}
    skipped_cols: list[str] = []
    written_orm_fields: set[str] = set()
    for field, value in (collection.form_data or {}).items():
        col = _match_source_column(field, available)
        if col is None:
            skipped_cols.append(_FIELD_LABELS.get(field, field))
            continue
        payload_fields[col] = _to_bitable_value(field, value)
        written_orm_fields.add(field)
    # 员工账号列回填 open_id（人员字段格式 {"id": ...}）
    account_col = _match_source_column("feishu_open_id", available)
    if account_col and collection.open_id:
        payload_fields[account_col] = {"id": collection.open_id}
    if not payload_fields:
        raise ValueError("源表中没有可写入的对应列，请联系管理员核对源表列名")

    await pb.update_record(
        cfg.app_token, cfg.source_table_id, employee.feishu_record_id,
        payload_fields, app_id=app_id, app_secret=app_secret,
    )

    # 源表写入成功后，同值预更新本地档案（与下轮同步结果一致，HR 免手动同步）
    for field in written_orm_fields:
        value = collection.form_data[field]
        fill = _FIELD_MAP.get(field)
        setattr(employee, field, date.fromisoformat(str(value)[:10]) if fill and fill.is_date else value)

    collection.status = "approved"
    collection.reviewed_by = reviewer
    collection.reviewed_at = datetime.now(timezone.utc)
    await session.commit()

    await _send_card(collection.open_id, {
        "schema": "2.0",
        "header": {"title": _label("信息已确认"), "template": "green"},
        "body": {"elements": [{"tag": "markdown", "content": "你的人事档案信息已确认归档，无需其他操作。"}]},
    })
    result = {"written_fields": len(payload_fields)}
    if skipped_cols:
        result["skipped_fields"] = skipped_cols
    return result


async def reject_collection(
    session: AsyncSession, collection_id: UUID, reason: str, reviewer: str,
) -> None:
    """驳回：记录原因 → 重发新表单卡片（原因置顶）→ 任务状态回滚 sent 待重填。"""
    collection = (await session.execute(
        select(EmployeeInfoCollection).where(
            EmployeeInfoCollection.id == collection_id,
            EmployeeInfoCollection.is_deleted.is_(False),
        )
    )).scalar_one_or_none()
    if collection is None:
        raise ValueError("收集任务不存在")
    if collection.status != "submitted":
        raise ValueError("仅「已提交待审核」的任务可驳回")
    employee = (await session.execute(
        select(Employee).where(Employee.id == collection.employee_id)
    )).scalar_one()

    collection.status = "sent"  # 回滚待重填（唯一索引约束下同一记录复用）
    collection.reject_reason = reason
    collection.reviewed_by = reviewer
    collection.reviewed_at = datetime.now(timezone.utc)
    await session.flush()

    if not await _send_card(collection.open_id, _build_fill_card(collection, employee, reject_reason=reason)):
        await session.rollback()
        raise ValueError("驳回卡片发送失败，请稍后重试（机器人不可用）")
    await session.commit()
