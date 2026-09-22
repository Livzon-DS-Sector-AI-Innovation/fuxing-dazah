"""成品入库对话登记工具（V3.0 §4.6）。

``create_finished_receipt_draft``：仓管员对机器人说入库信息（如「成品入库
达托霉素 批号 DA2609001 100kg」），LLM 收集字段后调用本工具（成品出库
create_finished_outbound_draft 同模式）：

- 缺必收字段（产品名称/产品批号/入库数量/单位——scene 配置
  ``SCENE_CONFIG["finished_receipt"].required_fields``）→ 返回 ``missing``
  + hint，LLM 向用户追问后重调（不猜、不硬写）；
- 入库日期缺省提交日（submit 侧兜底，工具层不强制）；品规/生产日期/
  有效期/生产车间/库区位置/备注选填（车间写备注前缀——「入库车间」列
  lookup 只读，grilling 拍板 1）；
- 单选适配：产品名称/品规/单位经选项集大小写归一（运行时刷新，D 期
  快照选项集为空时放行、提交侧 validate 兜底）；质量状态不收集——提交
  侧恒写「待检」（grilling 拍板 2）；
- 齐全 → draft_flow.create_dialog_draft（scene=finished_receipt）→
  send_confirm_card → 返回 draft_no。确认后的写入由 ConfirmService 回调
  submit_finished_receipt 完成（pipeline/submit.py）。

图片识别入口（成品入库单照片）不走本工具：gateway 图片链经单据分类
预判派发 recognize_finished_receipt（recognizer.py），落到同一 scene 草稿。

工具上下文/数据库访问模式与 finished.py 相同：``execute_tool`` 注入
``_ctx``；工具内自开事务（``_db_session`` 注入口），失败返回
``{"error": ...}`` 不中断 Runner。
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
from app.modules.warehouse.bitable_schema import FieldMeta

logger = logging.getLogger(__name__)

# 对话收集字段（canonical 键）→ 展示名（追问/结果回显共用文案）
FINISHED_RECEIPT_FIELD_LABELS: dict[str, str] = {
    "product_name": "产品名称",
    "product_batch_no": "产品批号",
    "quantity": "入库数量",
    "unit": "单位",
    "receipt_date": "入库日期",
    "receipt_type": "入库类型",
    "spec": "品规",
    "produced_at": "生产日期",
    "expiry": "有效期",
    "workshop": "生产车间",
    "storage_location": "库区位置",
    "remark": "备注",
}


# ── 数据库会话注入口（与 finished.py 同模式）──


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


async def _finished_receipt_table_fields() -> dict[str, FieldMeta]:
    """finished_receipt 字段元数据（运行时选项集优先，静态快照兜底）。"""
    try:
        await get_adapter().refresh_table_fields("finished_receipt")
    except Exception:  # noqa: BLE001 — 刷新失败回落静态快照，不阻断
        logger.warning("finished_receipt 选项集刷新失败，回落静态快照", exc_info=True)
    from app.modules.warehouse.bitable_schema import get_table_fields

    return get_table_fields("finished_receipt")


def _label(key: str) -> str:
    return FINISHED_RECEIPT_FIELD_LABELS.get(key, key)


# ── 工具壳（注册表入口；_ctx 由 execute_tool 注入）──


async def create_finished_receipt_draft(
    fields: dict[str, Any], _ctx: dict[str, Any] | None = None
) -> dict[str, Any]:
    """创建成品入库登记草稿并发确认卡片（用户说成品入库信息时调用）。"""
    ctx = _ctx or {}
    open_id = str(ctx.get("open_id") or "")
    chat_id = str(ctx.get("chat_id") or "") or None
    if not open_id:
        return {"error": "缺少用户上下文（open_id），无法创建登记草稿"}
    if not isinstance(fields, dict) or not fields:
        return {
            "error": "fields 不能为空",
            "hint": (
                f"传 {{字段名: 值}}，必收字段：{FINISHED_RECEIPT_FIELD_LABELS['product_name']}、"
                f"{FINISHED_RECEIPT_FIELD_LABELS['product_batch_no']}、"
                f"{FINISHED_RECEIPT_FIELD_LABELS['quantity']}、"
                f"{FINISHED_RECEIPT_FIELD_LABELS['unit']}（入库类型选填："
                "正常入库/返工入库/退货入库，缺省正常入库）"
            ),
        }

    mapped, unknown = map_fields(fields)
    if unknown:
        return {
            "error": f"不支持的字段: {'、'.join(unknown)}",
            "hint": f"可收集字段：{'、'.join(_label(k) for k in FINISHED_RECEIPT_FIELD_LABELS)}",
        }

    # 1. 必收字段（scene 配置）：缺失列 missing 让 LLM 追问，不猜不硬写
    required = draft_flow.SCENE_CONFIG[
        draft_flow.FINISHED_RECEIPT_SCENE
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

    # 2. 单选适配（产品名称/品规/单位）：大小写归一；D 期快照选项集为空时
    #    放行（提交侧运行时刷新 + validate 兜底），非法值在提交侧降级标注
    table_fields = await _finished_receipt_table_fields()
    warnings: list[str] = []
    for key, base_field in (
        ("product_name", "产品名称"),
        ("spec", "品规"),
        ("unit", "单位"),
    ):
        value = mapped.get(key)
        if value is None:
            continue
        text = str(value).strip()
        meta = table_fields.get(base_field)
        if meta is not None and meta.options and text not in meta.options:
            lowered = text.lower()
            matched = next(
                (opt for opt in meta.options if opt.lower() == lowered), None
            )
            if matched is not None:
                mapped[key] = matched
            else:
                warnings.append(
                    f"{_label(key)}「{text}」不在系统选项列表，提交时将降级为"
                    "人工在 Base 补填"
                )

    # 3. 齐全 → 对话草稿（created→aligned）→ 确认卡片
    try:
        async with _db_session() as db:
            draft = await draft_flow.create_dialog_draft(
                db,
                scene=draft_flow.FINISHED_RECEIPT_SCENE,
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
        logger.exception("成品入库登记草稿创建失败: open_id=%r", open_id)
        return {"error": f"成品入库登记草稿创建失败: {type(exc).__name__}: {exc}"}

    logger.info(
        "成品入库登记草稿已创建: draft_no=%s fields=%s warnings=%s",
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
            f"已创建成品入库登记草稿 {draft_no} 并发送确认卡片（10 分钟内有效），"
            "请提醒用户核对后点「确认入库」。"
        ),
    }


# ── 注册表（并入 query.TOOL_FUNCS / TOOLS，见 query.py 尾部）──

FINISHED_RECEIPT_TOOL_FUNCS: dict[str, Callable[..., Any]] = {
    "create_finished_receipt_draft": create_finished_receipt_draft,
}

FINISHED_RECEIPT_TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_finished_receipt_draft",
            "description": (
                "创建成品入库登记草稿（用户对机器人说成品入库信息时用，"
                "如「成品入库 达托霉素 批号 DA2609001 100kg」）。必收字段："
                "产品名称、产品批号（逐字使用用户提供值）、入库数量（纯数字）、"
                "单位（kg/十亿/g）；缺失时返回 missing，请向用户追问后再调用。"
                "选填：入库日期（缺省今天）、入库类型（正常入库/返工入库/退货"
                "入库，用户说退货/返工入库时传入）、品规、生产日期、有效期、"
                "生产车间（写入备注）、库区位置、备注。创建成功后系统发送确认"
                "卡片，用户点「确认入库」才写入台账。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fields": {
                        "type": "object",
                        "description": (
                            "字段名 → 值。产品名称、产品批号、入库数量（纯数字）、"
                            "单位 为必收；入库日期/入库类型（正常入库/返工入库/"
                            "退货入库）/品规/生产日期/有效期/生产车间/"
                            "库区位置/备注 选填。质量状态无需提供（系统默认待检，"
                            "退货入库自动联动退货）"
                        ),
                    },
                },
                "required": ["fields"],
            },
        },
    },
]
