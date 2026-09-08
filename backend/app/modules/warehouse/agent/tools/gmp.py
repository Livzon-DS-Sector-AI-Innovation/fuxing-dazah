"""GMP 出库对话登记工具（S3 ticket 01，spec Implementation Decisions 1）。

``create_gmp_draft``：质量部用户对机器人说出库信息（如「三氯甲烷
10423-260601 出库 25kg，生产批号 MA-ET-2026-050A，领用部门提炼工程一部」），
LLM 从对话收集字段后调用本工具：

- 缺必收字段（物料批号/领用数量/单位/生产批号——scene 配置
  ``SCENE_CONFIG["gmp_outbound"].required_fields``）→ 返回 ``missing`` +
  hint，LLM 向用户追问后重调（不猜、不硬写）；
- 单选适配：物料批号/单位必须命中选项集（bitable_schema，运行时刷新——
  静态快照批号仅 50 条而 Base 实测 1700+，直接用会误杀合法批号），未命中
  返回 error 引导核对（不猜测）；单据类型默认「出库」（合法值 出库|退库）；
  领用部门/领用品种为自由收集（选集未命中仅附 warning，submit 侧降级）；
- 齐全 → draft_flow.create_dialog_draft（scene=gmp_outbound，fields 即
  aligned，无识别/对齐步骤）→ send_confirm_card 确认卡片 → 返回 draft_no。
  确认后的写入由 ConfirmService 回调 submit_gmp 完成（pipeline/submit.py）。

注意：物料名称是 gmp_outbound 的 lookup 字段（拒写），收集值仅用于确认
卡片展示，不进入提交映射（submit._GMP_FIELD_MAP 无此键）。

工具上下文/数据库访问模式与 draft_update.py 相同：``execute_tool`` 注入
``_ctx``（{"session_id", "chat_id", "open_id"}）；工具内自开事务
（``_db_session`` 注入口），校验失败返回 ``{"error": ...}`` 不中断 Runner。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent.pipeline import draft_flow
from app.modules.warehouse.agent.tools.draft_update import map_fields
from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter
from app.modules.warehouse.bitable_schema import (
    FIELD_TYPE_SELECT,
    FieldMeta,
    get_table_fields,
)

logger = logging.getLogger(__name__)

# 目标表（spec：GMP 出库写 GMP 物料出库总账）
GMP_OUTBOUND_TABLE = "gmp_outbound"

# 单据类型合法值与默认值（spec 决策 1：默认出库；退库差异化处理留 V1.1）
GMP_DOC_TYPES: tuple[str, ...] = ("出库", "退库")
GMP_DEFAULT_DOC_TYPE = "出库"

# 对话收集字段（canonical 键）→ 展示名（追问/结果回显共用文案）
GMP_FIELD_LABELS: dict[str, str] = {
    "material_batch_no": "物料批号",
    "material_name": "物料名称（仅展示，不写入台账）",
    "quantity": "领用数量",
    "unit": "单位",
    "production_batch_no": "生产批号",
    "doc_type": "单据类型",
    "category": "领用品种",
    "department": "领用部门",
}

# 自由收集的单选字段（canonical 键 → Base 字段名；选项集未命中降级为
# warning，不阻断登记——submit 侧 _select_or_skip 同口径跳过）
GMP_SOFT_SELECT_FIELDS: dict[str, str] = {
    "category": "领用品种",
    "department": "领用部门",
}


# ── 数据库会话注入口（与 draft_update.py 同模式）──


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


async def _gmp_table_fields() -> dict[str, FieldMeta]:
    """gmp_outbound 字段元数据（运行时选项集优先，静态快照兜底）。

    静态快照物料批号选项仅 50 条而 Base 实测 1700+（快照滞后会误杀合法
    批号）——先 refresh_table_fields 拉最新选项集（bitable_schema TTL 缓存
    内直用），刷新失败回落静态快照（登记主链路不因选项集刷新抖动中断）。
    """
    try:
        await get_adapter().refresh_table_fields(GMP_OUTBOUND_TABLE)
    except Exception:  # noqa: BLE001 — 刷新失败回落静态快照，不阻断
        logger.warning("gmp_outbound 选项集刷新失败，回落静态快照", exc_info=True)
    return get_table_fields(GMP_OUTBOUND_TABLE)


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
    return GMP_FIELD_LABELS.get(key, key)


# ── 工具壳（注册表入口；_ctx 由 execute_tool 注入）──


async def create_gmp_draft(
    fields: dict[str, Any], _ctx: dict[str, Any] | None = None
) -> dict[str, Any]:
    """创建 GMP 出库登记草稿并发确认卡片（用户说出库信息时调用）。"""
    ctx = _ctx or {}
    open_id = str(ctx.get("open_id") or "")
    chat_id = str(ctx.get("chat_id") or "") or None
    if not open_id:
        return {"error": "缺少用户上下文（open_id），无法创建登记草稿"}
    if not isinstance(fields, dict) or not fields:
        return {
            "error": "fields 不能为空",
            "hint": f"传 {{字段名: 值}}，必收字段：{GMP_FIELD_LABELS['material_batch_no']}、{GMP_FIELD_LABELS['quantity']}、{GMP_FIELD_LABELS['unit']}、{GMP_FIELD_LABELS['production_batch_no']}",
        }

    mapped, unknown = map_fields(fields)
    if unknown:
        return {
            "error": f"不支持的字段: {'、'.join(unknown)}",
            "hint": f"可收集字段：{'、'.join(_label(k) for k in GMP_FIELD_LABELS)}",
        }

    # 1. 必收字段（scene 配置）：缺失列 missing 让 LLM 追问，不猜不硬写
    required = draft_flow.SCENE_CONFIG[draft_flow.GMP_OUTBOUND_SCENE].required_fields
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

    table_fields = await _gmp_table_fields()

    # 2. 单据类型：默认出库；非法值 error（合法集固定）
    doc_type = str(mapped.get("doc_type") or "").strip() or GMP_DEFAULT_DOC_TYPE
    if doc_type not in GMP_DOC_TYPES:
        return {
            "error": f"单据类型 {doc_type} 不合法（可选：{'、'.join(GMP_DOC_TYPES)}）",
            "hint": "单据类型缺省按「出库」处理；如需退库请用户明确说明",
        }
    mapped["doc_type"] = doc_type

    # 3. 物料批号（必收单选）：必须命中选项集——不在时引导核对，不猜测
    batch = str(mapped["material_batch_no"]).strip()
    adapted_batch = _match_option(table_fields.get("物料批号"), batch)
    if adapted_batch is None:
        return {
            "error": (
                f"物料批号 {batch} 不在系统批号列表中，请让用户核对批号"
                "（不要猜测或自动改写）"
            ),
            "error_code": "batch_not_found",
        }
    mapped["material_batch_no"] = adapted_batch

    # 4. 单位（必收单选）：大小写归一（Kg→kg）；不在选项集 error 引导
    unit = str(mapped["unit"]).strip()
    unit_meta = table_fields.get("单位")
    adapted_unit = _match_option(unit_meta, unit)
    if adapted_unit is None:
        unit_options = (
            "、".join(unit_meta.options) if unit_meta and unit_meta.options else ""
        )
        return {
            "error": (
                f"单位 {unit} 不合法（可选：{unit_options or 'kg、瓶、L'}），"
                "请向用户核对后重试"
            ),
            "error_code": "unit_invalid",
        }
    mapped["unit"] = adapted_unit

    # 5. 领用部门/领用品种（自由收集单选）：选集未命中附 warning（不阻断）
    warnings: list[str] = []
    for key, field_name in GMP_SOFT_SELECT_FIELDS.items():
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
                f"{GMP_FIELD_LABELS[key]}「{text}」不在系统选项列表，"
                "提交时需人工在 Base 补填"
            )
            mapped[key] = text

    # 6. 齐全 → 对话草稿（created→aligned）→ 确认卡片
    try:
        async with _db_session() as db:
            draft = await draft_flow.create_dialog_draft(
                db,
                scene=draft_flow.GMP_OUTBOUND_SCENE,
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
        logger.exception("GMP 登记草稿创建失败: open_id=%r", open_id)
        return {"error": f"GMP 登记草稿创建失败: {type(exc).__name__}: {exc}"}

    logger.info(
        "GMP 登记草稿已创建: draft_no=%s fields=%s warnings=%s",
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
            f"已创建 GMP 出库登记草稿 {draft_no} 并发送确认卡片（10 分钟内有效），"
            "请提醒用户核对后点「确认登记」。"
        ),
    }


# ── 注册表（并入 query.TOOL_FUNCS / TOOLS，见 query.py 尾部）──

GMP_TOOL_FUNCS: dict[str, Callable[..., Any]] = {
    "create_gmp_draft": create_gmp_draft,
}

GMP_TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_gmp_draft",
            "description": (
                "创建 GMP 物料出库登记草稿（用户对机器人说出库/领用信息时用，"
                "如「三氯甲烷 10423-260601 出库 25kg，生产批号 MA-ET-2026-050A」）。"
                "必收字段缺失时返回 missing，请向用户追问后再调用；创建成功后"
                "系统发送确认卡片，用户点「确认登记」才写入台账。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fields": {
                        "type": "object",
                        "description": (
                            "字段名 → 值。物料批号（逐字使用用户提供的批号，"
                            "禁止增删后缀或任何改写）、"
                            "领用数量（纯数字）、单位（kg/瓶/L）、生产批号 为必收；"
                            "物料名称（仅展示）、单据类型（缺省出库）、领用品种、"
                            "领用部门 选填"
                        ),
                    },
                },
                "required": ["fields"],
            },
        },
    },
]
