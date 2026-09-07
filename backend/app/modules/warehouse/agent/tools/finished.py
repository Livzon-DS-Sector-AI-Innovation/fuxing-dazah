"""成品出库对话登记工具（S3 ticket 02，spec Implementation Decisions 2/3）。

``create_finished_outbound_draft``：成品仓管员对机器人说出库信息（如
「硫酸黏菌素 批号 TEST-X2609 出库 225000 十亿，客户 can，快递 SF123456」），
LLM 从对话收集字段后调用本工具（与 GMP ``create_gmp_draft`` 同模式）：

- 缺必收字段（产品名称/产品批号/出库量/单位/销售客户——scene 配置
  ``SCENE_CONFIG["finished_outbound"].required_fields``）→ 返回 ``missing``
  + hint，LLM 向用户追问后重调（不猜、不硬写）；
- 单选适配：产品名称/单位必须命中选项集（bitable_schema，运行时刷新），
  未命中返回 error 引导核对（不猜测）；用途缺省「销售」（在选项集内才
  生效）；用途/温度计为软校验单选（选集未命中附 warning，submit 侧降级
  跳过）；快递号/备注自由收集透传；
- 齐全 → draft_flow.create_dialog_draft（scene=finished_outbound，fields
  即 aligned，无识别/对齐步骤）→ send_confirm_card 确认卡片 → 返回
  draft_no。确认后的写入由 ConfirmService 回调 submit_outbound 完成
  （pipeline/submit.py）。

注意：快递号在成品出库台账为附件字段（type 17，写入需 file_token），
文本快递单号无法写入 Base——收集值保留在草稿/确认卡片/回执/推送卡片中
（快递推送链使用），submit 侧降级标注人工补填（见
submit.SUBMIT_FINISHED_EXPRESS_ENABLED 开关注释）。

工具上下文/数据库访问模式与 gmp.py/draft_update.py 相同：``execute_tool``
注入 ``_ctx``（{"session_id", "chat_id", "open_id"}）；工具内自开事务
（``_db_session`` 注入口），校验失败返回 ``{"error": ...}`` 不中断 Runner。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent.pipeline import draft_flow
from app.modules.warehouse.agent.pipeline.submit import (
    SUBMIT_FINISHED_EXPRESS_ENABLED,
)
from app.modules.warehouse.agent.tools.draft_update import map_fields
from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter
from app.modules.warehouse.bitable_schema import (
    FIELD_TYPE_SELECT,
    FieldMeta,
    get_table_fields,
)

logger = logging.getLogger(__name__)

# 目标表（spec：成品出库写成品出库台账）
FINISHED_OUTBOUND_TABLE = "finished_outbound"

# 用途默认值（spec 决策 2：缺省按「销售」；须在选项集内才生效）
FINISHED_DEFAULT_PURPOSE = "销售"

# 对话收集字段（canonical 键）→ 展示名（追问/结果回显共用文案）
FINISHED_FIELD_LABELS: dict[str, str] = {
    "product_name": "产品名称",
    "product_batch_no": "产品批号",
    "quantity": "出库量",
    "unit": "单位",
    "customer": "销售客户",
    "purpose": "用途",
    "express_no": "快递号",
    "thermometer": "温度计",
    "remark": "备注",
}

# 软校验的单选字段（canonical 键 → Base 字段名；选项集未命中降级为
# warning，不阻断登记——submit 侧 _select_or_skip 同口径跳过）
FINISHED_SOFT_SELECT_FIELDS: dict[str, str] = {
    "purpose": "用途",
    "thermometer": "温度计",
}


# ── 数据库会话注入口（与 gmp.py/draft_update.py 同模式）──


@asynccontextmanager
async def _production_db() -> AsyncIterator[AsyncSession]:
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        yield session
        await session.commit()


_db_session: Callable[[], AbstractAsyncContextManager[AsyncSession]] = _production_db

# adapter 进程级单例（pipeline.submit 同款；测试经 monkeypatch 注入假件）
_adapter: WarehouseBitableAdapter | None = None


def get_adapter() -> WarehouseBitableAdapter:
    global _adapter
    if _adapter is None:
        _adapter = WarehouseBitableAdapter()
    return _adapter


async def _finished_table_fields() -> dict[str, FieldMeta]:
    """finished_outbound 字段元数据（运行时选项集优先，静态快照兜底）。

    产品名称/单位/用途/温度计均为单选且 Base 侧可能调整选项——先
    refresh_table_fields 拉最新选项集（bitable_schema TTL 缓存内直用），
    刷新失败回落静态快照（登记主链路不因选项集刷新抖动中断）。
    """
    try:
        await get_adapter().refresh_table_fields(FINISHED_OUTBOUND_TABLE)
    except Exception:  # noqa: BLE001 — 刷新失败回落静态快照，不阻断
        logger.warning("finished_outbound 选项集刷新失败，回落静态快照", exc_info=True)
    return get_table_fields(FINISHED_OUTBOUND_TABLE)


# ── 字段校验/适配（纯逻辑，便于单测）──


def _match_option(meta: FieldMeta | None, text: str) -> str | None:
    """单选值适配：大小写归一匹配选项集（命中返回选项原值）；未命中 None。

    未收录字段/非单选/空选项集放行原值（bitable_schema 契约：避免常量
    滞后误杀；submit 侧 validate_write_fields 为最后防线）。
    """
    if meta is None or meta.type != FIELD_TYPE_SELECT:
        return text
    options: tuple[str, ...] = meta.options
    if not options:
        return text
    if text in options:
        return text
    lowered = text.lower()
    for opt in options:
        if opt.lower() == lowered:
            return opt
    return None


def _label(key: str) -> str:
    return FINISHED_FIELD_LABELS.get(key, key)


# ── 工具壳（注册表入口；_ctx 由 execute_tool 注入）──


async def create_finished_outbound_draft(
    fields: dict[str, Any], _ctx: dict[str, Any] | None = None
) -> dict[str, Any]:
    """创建成品出库登记草稿并发确认卡片（用户说成品出库信息时调用）。"""
    ctx = _ctx or {}
    open_id = str(ctx.get("open_id") or "")
    chat_id = str(ctx.get("chat_id") or "") or None
    if not open_id:
        return {"error": "缺少用户上下文（open_id），无法创建登记草稿"}
    if not isinstance(fields, dict) or not fields:
        return {
            "error": "fields 不能为空",
            "hint": (
                f"传 {{字段名: 值}}，必收字段：{FINISHED_FIELD_LABELS['product_name']}、"
                f"{FINISHED_FIELD_LABELS['product_batch_no']}、"
                f"{FINISHED_FIELD_LABELS['quantity']}、{FINISHED_FIELD_LABELS['unit']}、"
                f"{FINISHED_FIELD_LABELS['customer']}"
            ),
        }

    mapped, unknown = map_fields(fields)
    if unknown:
        return {
            "error": f"不支持的字段: {'、'.join(unknown)}",
            "hint": f"可收集字段：{'、'.join(_label(k) for k in FINISHED_FIELD_LABELS)}",
        }

    # 1. 必收字段（scene 配置）：缺失列 missing 让 LLM 追问，不猜不硬写
    required = draft_flow.SCENE_CONFIG[
        draft_flow.FINISHED_OUTBOUND_SCENE
    ].required_fields
    missing = [
        _label(key)
        for key in required
        if mapped.get(key) is None or not str(mapped.get(key)).strip()
    ]
    if missing:
        return {
            "status": "incomplete",
            "missing": missing,
            "collected": {_label(k): v for k, v in mapped.items() if v is not None},
            "hint": f"请补充：{'、'.join(missing)}（向用户追问后再调用本工具，不要猜测或编造）",
        }

    table_fields = await _finished_table_fields()

    # 2. 产品名称（必收单选）：必须命中选项集——不在时引导核对，不猜测
    name = str(mapped["product_name"]).strip()
    adapted_name = _match_option(table_fields.get("产品名称"), name)
    if adapted_name is None:
        return {
            "error": (
                f"产品名称 {name} 不在系统产品列表中，请让用户核对产品名称"
                "（不要猜测或自动改写）"
            ),
            "error_code": "product_not_found",
        }
    mapped["product_name"] = adapted_name

    # 3. 单位（必收单选）：大小写归一（KG→kg）；不在选项集 error 引导
    unit = str(mapped["unit"]).strip()
    unit_meta = table_fields.get("单位")
    adapted_unit = _match_option(unit_meta, unit)
    if adapted_unit is None:
        unit_options = (
            "、".join(unit_meta.options) if unit_meta and unit_meta.options else ""
        )
        return {
            "error": (
                f"单位 {unit} 不合法（可选：{unit_options or 'kg、十亿、g'}），"
                "请向用户核对后重试"
            ),
            "error_code": "unit_invalid",
        }
    mapped["unit"] = adapted_unit

    # 4. 用途：缺省「销售」（选项集收录该选项才生效，避免常量滞后硬写非法值）
    purpose = mapped.get("purpose")
    if purpose is None or not str(purpose).strip():
        purpose_meta = table_fields.get("用途")
        if (
            purpose_meta is not None
            and purpose_meta.options
            and FINISHED_DEFAULT_PURPOSE in purpose_meta.options
        ):
            mapped["purpose"] = FINISHED_DEFAULT_PURPOSE

    # 5. 用途/温度计（软校验单选）：选集未命中附 warning（不阻断）；快递号
    #    为附件字段——提前告知需人工补填（不阻断登记）
    warnings: list[str] = []
    if mapped.get("express_no") and not SUBMIT_FINISHED_EXPRESS_ENABLED:
        warnings.append("快递号需在 Base 人工补填（附件字段暂不支持自动写入）")
    for key, field_name in FINISHED_SOFT_SELECT_FIELDS.items():
        value = mapped.get(key)
        if value is None:
            continue
        text = str(value).strip()
        meta = table_fields.get(field_name)
        adapted = _match_option(meta, text)
        if adapted is not None:
            mapped[key] = adapted  # 归一为选项原值（如大小写差异）
        elif meta is not None and meta.options:
            warnings.append(
                f"{FINISHED_FIELD_LABELS[key]}「{text}」不在系统选项列表，"
                "提交时需人工在 Base 补填"
            )
            mapped[key] = text

    # 6. 齐全 → 对话草稿（created→aligned）→ 确认卡片
    try:
        async with _db_session() as db:
            draft = await draft_flow.create_dialog_draft(
                db,
                scene=draft_flow.FINISHED_OUTBOUND_SCENE,
                fields=mapped,
                open_id=open_id,
                chat_id=chat_id,
            )
            await draft_flow.send_confirm_card(
                db, draft, chat_id=chat_id, open_id=open_id
            )
            draft_no = draft.draft_no
            status = draft.status
    except Exception as exc:  # noqa: BLE001 — 创建失败不中断 Runner
        logger.exception("成品出库登记草稿创建失败: open_id=%r", open_id)
        return {"error": f"成品出库登记草稿创建失败: {type(exc).__name__}: {exc}"}

    logger.info(
        "成品出库登记草稿已创建: draft_no=%s fields=%s warnings=%s",
        draft_no,
        sorted(mapped),
        warnings,
    )
    return {
        "status": status,
        "draft_no": draft_no,
        "fields": mapped,
        "warnings": warnings,
        "message": (
            f"已创建成品出库登记草稿 {draft_no} 并发送确认卡片（10 分钟内有效），"
            "请提醒用户核对后点「确认登记」。"
        ),
    }


# ── 注册表（并入 query.TOOL_FUNCS / TOOLS，见 query.py 尾部）──

FINISHED_TOOL_FUNCS: dict[str, Callable[..., Any]] = {
    "create_finished_outbound_draft": create_finished_outbound_draft,
}

FINISHED_TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_finished_outbound_draft",
            "description": (
                "创建成品出库登记草稿（用户对机器人说成品出库信息时用，"
                "如「硫酸黏菌素 批号 X2609 出库 225000 十亿，客户 can，"
                "快递 SF123456」）。必收字段缺失时返回 missing，请向用户"
                "追问后再调用；创建成功后系统发送确认卡片，用户点「确认"
                "登记」才写入台账。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fields": {
                        "type": "object",
                        "description": (
                            "字段名 → 值。产品名称（须与系统产品列表一致）、"
                            "产品批号（逐字使用用户提供的批号）、出库量"
                            "（纯数字）、单位（kg/十亿/g）、销售客户 为必收；"
                            "用途（缺省销售）、快递号、温度计（已开启/未开启/"
                            "无）、备注 选填"
                        ),
                    },
                },
                "required": ["fields"],
            },
        },
    },
]
