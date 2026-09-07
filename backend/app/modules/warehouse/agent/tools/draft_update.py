"""登记草稿对话修改工具（S2 ticket 03 + S3 ticket 01 通用化，spec
Implementation Decisions 5）。

``update_draft``：用户对识别/登记草稿说「把数量改成 200」「批号写错了」时，
LLM 调用本工具把新值写入草稿 ``aligned`` JSONB（**working set**——submit
的写入来源；``recognized`` 保留原始识别/收集值不改写，供审计回溯），随后
status 回 pending_confirm 并重发确认卡片
（pipeline.draft_flow.send_confirm_card）。

- draft_no 缺省：取该用户最近一个 aligned/pending_confirm 的登记草稿
  （receipt/GMP 出库等，``repository.list_actionable_drafts`` 已扩展 aligned
  状态——S1 修5）；LLM 从 Runner 注入的「当前待处理事项」摘要获知 draft_no。
- 权限：仅草稿发起人可修改；仅 scene ∈ draft_flow.SCENE_CONFIG（入库识别/
  GMP 出库/成品出库——S3 ticket 01 通用化）且状态 aligned/pending_confirm
  可改（确认门 handle_action 只认 pending_confirm，语义自洽：确认卡片只在
  pending_confirm 状态发出，修改后重发）。
- 字段名映射：LLM 传业务字段名（数量/厂家批号…）或 canonical 键
  （quantity/vendor_batch_no…）均可；未知字段返回 error 引导（列出可改
  字段），不猜测。数量值自动数字化（"200" → 200）。

工具上下文/数据库访问模式与 plan.py/office.py 相同：``execute_tool`` 注入
``_ctx``（{"session_id", "chat_id", "open_id"}）；工具内自开事务（``_db_session``
注入口），校验失败返回 ``{"error": ...}`` 不中断 Runner。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent import repository
from app.modules.warehouse.agent.pipeline import draft_flow
from app.modules.warehouse.models import WarehouseAgentDraft

logger = logging.getLogger(__name__)

# 可修改状态（与 drafts 状态机一致；created 未对齐、终态不可改）
MUTABLE_STATUSES: tuple[str, ...] = ("aligned", "pending_confirm")

# 数量字段（值自动数字化）
_NUMERIC_KEYS = {"quantity"}

# 业务字段名/别名 → canonical 键（LLM 两种叫法都收）。
# receipt 与 gmp_outbound 字段并集（S3 ticket 01 通用化）：数量/单位两场景
# 同义共用；「批号」仍指入库厂家批号（GMP 批号请用「物料批号」，见提示词）。
FIELD_ALIASES: dict[str, str] = {
    "物料名称": "material_name",
    "品名": "material_name",
    "material_name": "material_name",
    "厂家批号": "vendor_batch_no",
    "批号": "vendor_batch_no",
    "vendor_batch_no": "vendor_batch_no",
    "数量": "quantity",
    "入库数量": "quantity",
    "领用数量": "quantity",
    "quantity": "quantity",
    "单位": "unit",
    "unit": "unit",
    "供应商": "supplier",
    "supplier": "supplier",
    "生产商": "manufacturer",
    "生产厂家": "manufacturer",
    "manufacturer": "manufacturer",
    "车牌": "plate_no",
    "车牌号": "plate_no",
    "plate_no": "plate_no",
    "合同号": "contract_no",
    "合同编号": "contract_no",
    "订单号": "contract_no",
    "contract_no": "contract_no",
    "包装规格": "package_spec",
    "package_spec": "package_spec",
    "生产日期": "produced_at",
    "produced_at": "produced_at",
    "到货时间段": "arrival_period",
    "arrival_period": "arrival_period",
    "备注": "remark",
    "remark": "remark",
    "联系人": "contact",
    "contact": "contact",
    # ── GMP 出库（S3 ticket 01）──
    "物料批号": "material_batch_no",
    "material_batch_no": "material_batch_no",
    "生产批号": "production_batch_no",
    "production_batch_no": "production_batch_no",
    "单据类型": "doc_type",
    "doc_type": "doc_type",
    "领用品种": "category",
    "category": "category",
    "领用部门": "department",
    "部门": "department",
    "department": "department",
    # ── 成品出库（S3 ticket 02）；数量/单位/备注与上面两场景同义共用 ──
    "产品名称": "product_name",
    "product_name": "product_name",
    "产品批号": "product_batch_no",
    "product_batch_no": "product_batch_no",
    "出库量": "quantity",
    "出库数量": "quantity",
    "销售客户": "customer",
    "客户": "customer",
    "customer": "customer",
    "用途": "purpose",
    "purpose": "purpose",
    "快递号": "express_no",
    "快递单号": "express_no",
    "express_no": "express_no",
    "温度计": "thermometer",
    "thermometer": "thermometer",
}

# 引导文案里的可改字段清单（业务名；receipt + gmp_outbound + finished_outbound
# 三场景并集；「品名」在成品语境请用「产品名称」，见提示词）
MODIFIABLE_FIELD_NAMES = (
    "物料名称、厂家批号、数量、单位、供应商、生产商、车牌、合同号、"
    "包装规格、生产日期、到货时间段、备注、联系人、物料批号、生产批号、"
    "单据类型、领用品种、领用部门、产品名称、产品批号、出库量、销售客户、"
    "用途、快递号、温度计"
)

# 确认卡片动作文案（按 scene；重发卡片后的提醒话术）
_SCENE_CONFIRM_LABELS: dict[str, str] = {
    "receipt": "确认入库",
    "gmp_outbound": "确认登记",
    "finished_outbound": "确认登记",
}


# ── 数据库会话注入口（与 plan.py/office.py 同模式）──


@asynccontextmanager
async def _production_db() -> AsyncIterator[AsyncSession]:
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        yield session
        await session.commit()


_db_session: Callable[[], AbstractAsyncContextManager[AsyncSession]] = _production_db


# ── 字段值规范化 ──


def _coerce_value(key: str, value: Any) -> Any:
    """字段新值规范化：数量数字化（"200"/"1,200" → 数字），其余转非空文本。"""
    if key in _NUMERIC_KEYS and not isinstance(value, bool):
        if isinstance(value, (int, float)):
            return value
        text = str(value).strip().replace(",", "")
        try:
            number = float(text)
        except ValueError:
            return str(value).strip()  # 无法数字化按原文保留（submit 校验兜底）
        return int(number) if number.is_integer() else number
    return str(value).strip()


def map_fields(fields: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """LLM 字段 dict → (canonical 映射结果, 未知字段名列表)。"""
    mapped: dict[str, Any] = {}
    unknown: list[str] = []
    for name, value in fields.items():
        key = FIELD_ALIASES.get(str(name).strip())
        if key is None:
            unknown.append(str(name))
            continue
        mapped[key] = _coerce_value(key, value)
    return mapped, unknown


# ── 草稿定位 ──


async def _locate_draft(
    db: AsyncSession, *, draft_no: str | None, open_id: str
) -> WarehouseAgentDraft | dict[str, Any]:
    """定位可修改草稿。返回草稿对象或 ``{"error", "hint"?}``（不抛错）。"""
    if draft_no:
        draft = await repository.get_agent_draft_by_no(db, draft_no=draft_no.strip())
        if draft is None:
            return {"error": f"草稿 {draft_no} 不存在"}
        if draft.created_by_open_id != open_id:
            return {"error": f"草稿 {draft.draft_no} 不属于当前用户，仅发起人可修改"}
    else:
        drafts = await repository.list_actionable_drafts(db, open_id, limit=5)
        draft = next(
            (
                d
                for d in drafts
                if d.scene in draft_flow.SCENE_CONFIG and d.status in MUTABLE_STATUSES
            ),
            None,
        )
        if draft is None:
            return {
                "error": "没有找到可修改的登记草稿（入库识别/GMP 出库/成品出库）",
                "hint": "请先发送送货单照片或说明登记信息创建草稿；"
                "如草稿编号明确可传 draft_no。",
            }
    if draft.scene not in draft_flow.SCENE_CONFIG:
        return {
            "error": (
                f"草稿 {draft.draft_no} 不是登记草稿"
                "（入库识别/GMP 出库/成品出库），不能按登记字段修改"
            )
        }
    expires_at = draft.expires_at
    if expires_at is not None and expires_at < datetime.now(UTC):
        return {"error": f"草稿 {draft.draft_no} 已过期，请重新拍照发起识别"}
    if draft.status not in MUTABLE_STATUSES:
        return {
            "error": (
                f"草稿 {draft.draft_no} 当前状态 {draft.status}，不可修改"
                "（已确认/已提交/已取消/已过期请重新拍照识别）"
            )
        }
    return draft


# ── 工具壳（注册表入口；_ctx 由 execute_tool 注入，见模块注释）──


async def update_draft(
    draft_no: str | None, fields: dict[str, Any], _ctx: dict[str, Any] | None = None
) -> dict[str, Any]:
    """修改登记草稿字段并重发确认卡片（用户说「数量改成 200」时调用）。"""
    ctx = _ctx or {}
    open_id = str(ctx.get("open_id") or "")
    chat_id = str(ctx.get("chat_id") or "") or None
    if not open_id:
        return {"error": "缺少用户上下文（open_id），无法修改草稿"}
    if not isinstance(fields, dict) or not fields:
        return {
            "error": "fields 不能为空",
            "hint": f"传 {{字段名: 新值}}，可改字段：{MODIFIABLE_FIELD_NAMES}",
        }

    mapped, unknown = map_fields(fields)
    if unknown:
        return {
            "error": f"不支持的字段: {'、'.join(unknown)}",
            "hint": f"可改字段：{MODIFIABLE_FIELD_NAMES}",
        }
    if not mapped:
        return {"error": "没有可应用的字段修改"}

    try:
        async with _db_session() as db:
            located = await _locate_draft(db, draft_no=draft_no, open_id=open_id)
            if isinstance(located, dict):  # {"error": ...}
                return located
            draft = located
            aligned = dict(draft.aligned or {})
            aligned.update(mapped)
            draft.aligned = aligned  # JSONB 重新赋值才触发 UPDATE
            await db.flush()
            # 状态回 pending_confirm + 重发确认卡片
            # （aligned→pending_confirm 首发或 pending_confirm→pending_confirm 重发，
            #   迁移合法性由 draft_flow 状态机校验）
            await draft_flow.send_confirm_card(
                db, draft, chat_id=chat_id, open_id=open_id
            )
            updated = {k: draft.aligned.get(k) for k in mapped}
    except Exception as exc:  # noqa: BLE001 — 修改失败不中断 Runner
        logger.exception("登记草稿修改失败: draft_no=%r", draft_no)
        return {"error": f"草稿修改失败: {type(exc).__name__}: {exc}"}

    confirm_label = _SCENE_CONFIRM_LABELS.get(draft.scene, "确认")
    logger.info(
        "登记草稿字段已更新: draft_no=%s scene=%s fields=%s",
        draft.draft_no,
        draft.scene,
        list(mapped),
    )
    return {
        "status": draft.status,
        "draft_no": draft.draft_no,
        "updated": updated,
        "message": (
            f"已更新草稿 {draft.draft_no} 并重发确认卡片（10 分钟内有效），"
            f"请提醒用户到新卡片上核对后点「{confirm_label}」。"
        ),
    }


# ── 注册表（并入 query.TOOL_FUNCS / TOOLS，见 query.py 尾部）──

DRAFT_UPDATE_TOOL_FUNCS: dict[str, Callable[..., Any]] = {
    "update_draft": update_draft,
}

DRAFT_UPDATE_TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "update_draft",
            "description": (
                "修改登记草稿的字段（入库识别/GMP 出库/成品出库；用户说"
                "「把数量改成 200」「批号写错了」等时用）。修改后系统重发"
                "确认卡片，用户在新卡片上核对后确认提交。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "draft_no": {
                        "type": "string",
                        "description": (
                            "草稿编号（如 WR20260907-001，见当前待处理事项）；"
                            "省略时修改该用户最近一张可修改的登记草稿"
                        ),
                    },
                    "fields": {
                        "type": "object",
                        "description": (
                            "字段名 → 新值（一次可改多个）。入库识别草稿：数量/"
                            "厂家批号/单位/供应商/生产商/车牌/合同号/物料名称/"
                            "包装规格/生产日期/到货时间段/备注/联系人；GMP 出库"
                            "草稿：物料批号/数量/单位/生产批号/单据类型/领用品种/"
                            "领用部门；成品出库草稿：产品名称/产品批号/出库量/"
                            "单位/销售客户/用途/快递号/温度计/备注；数量传纯数字"
                        ),
                    },
                },
                "required": ["fields"],
            },
        },
    },
]
