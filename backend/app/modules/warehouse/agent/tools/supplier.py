"""供应商准入登记工具（V3.0 分期C，设计 §4.3）。

``create_supplier_admission``：采购对机器人说「申请准入供应商 XXX」，LLM
收集供应商名称（可选备注）后调用本工具：

- 名录行：supplier_directory 表 create_record（供应商名称 / 审计状态=
  待准入 / 申请日期=今天 / 备注）——表坐标经配置中心 Bitable 连接接入，
  未接入（table_id 空占位未覆盖）时 adapter 报错，本工具捕获转
  「功能未就绪」error（``supplier_directory_unavailable``）；
- QA 确认门：``qc_writeback_enabled`` 开（关 → 只建行不建门，提示待 QA
  在 Base 处理）→ confirm_request 建门（business_type=supplier_admission，
  writeback={审计状态: 准入, 准入日期: @today}，target=qa_confirm_target()，
  与 QA 放行门同开关同目标，质询 Round 2 定案）；同供应商名已有 pending
  门时不重复建（``gate_deduped``）；
- 确认/取消走 gateway scene=biz_confirm 既有后台回写；开关关时确认点击
  被 confirm_request 闸门拒绝（qc_writeback_allowed 纳入管辖）。

「AI 辅助核对」口径：系统只提示不判定（入库比对提醒见 push 事件）；
准入的最终裁量在 Base（1C 加速器定位）。

工具上下文/数据库访问模式与 picking.py 相同：``execute_tool`` 注入
``_ctx``；工具内自开事务（``_db_session`` 注入口），失败返回
``{"error": ...}`` 不中断 Runner。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent.tools.draft_update import map_fields
from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter
from app.modules.warehouse.bitable_schema import (
    WarehouseBitableError,
    validate_write_fields,
)

logger = logging.getLogger(__name__)

# 目标表与业务类型（SUPPLIER_ADMIT_BIZ 定义在 qc_flow——确认闸门共享常量源）
SUPPLIER_DIRECTORY_TABLE = "supplier_directory"
PENDING_STATUS = "待准入"

# 对话收集字段（canonical 键）→ 展示名
SUPPLIER_FIELD_LABELS: dict[str, str] = {
    "supplier_name": "供应商名称",
    "supplier": "供应商",
    "remark": "备注",
}


def _today_ms(today: date | None = None) -> int:
    """当天日期 → 毫秒时间戳（飞书 datetime 写入契约，同 submit._today_ms）。"""
    day = today or date.today()
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000)


# ── 数据库会话注入口（与 picking.py 同模式）──


@asynccontextmanager
async def _production_db() -> AsyncIterator[AsyncSession]:
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        yield session
        await session.commit()


_db_session: Callable[[], AbstractAsyncContextManager[AsyncSession]] = _production_db

# adapter 进程级单例（picking.py 同款；测试经 monkeypatch 注入假件）
_adapter: WarehouseBitableAdapter | None = None


def get_adapter() -> WarehouseBitableAdapter:
    global _adapter
    if _adapter is None:
        _adapter = WarehouseBitableAdapter()
    return _adapter


def _label(key: str) -> str:
    return SUPPLIER_FIELD_LABELS.get(key, key)


async def _pending_admission_exists(
    db: AsyncSession, supplier_name: str
) -> bool:
    """同供应商名是否已有 pending 准入门（payload JSONB containment 查询）。"""
    from sqlalchemy import exists, select

    from app.modules.warehouse.models import WarehouseConfirmRequest
    from app.modules.warehouse.qc_flow import SUPPLIER_ADMIT_BIZ

    stmt = select(
        exists().where(
            WarehouseConfirmRequest.business_type == SUPPLIER_ADMIT_BIZ,
            WarehouseConfirmRequest.status == "pending",
            WarehouseConfirmRequest.is_deleted.is_(False),
            WarehouseConfirmRequest.payload.contains(
                {"supplier_name": supplier_name}
            ),
        )
    )
    return bool(await db.scalar(stmt))


# ── 工具壳（注册表入口；_ctx 由 execute_tool 注入）──


async def create_supplier_admission(
    fields: dict[str, Any], _ctx: dict[str, Any] | None = None
) -> dict[str, Any]:
    """申请供应商准入：名录表建行（待准入）+ QA 确认门（用户说申请准入时调用）。"""
    ctx = _ctx or {}
    open_id = str(ctx.get("open_id") or "")
    if not open_id:
        return {"error": "缺少用户上下文（open_id），无法提交准入申请"}
    if not isinstance(fields, dict) or not fields:
        return {
            "error": "fields 不能为空",
            "hint": f"传 {{字段名: 值}}，必收字段：{_label('supplier_name')}",
        }

    mapped, unknown = map_fields(fields)
    if unknown:
        return {
            "error": f"不支持的字段: {'、'.join(unknown)}",
            "hint": f"可收集字段：{'、'.join(_label(k) for k in SUPPLIER_FIELD_LABELS)}",
        }

    # 供应商名称：「供应商名称」必收；LLM 传「供应商」（receipt 场景同名
    # 别名键）时同义收编
    name = str(
        mapped.get("supplier_name") or mapped.get("supplier") or ""
    ).strip()
    if not name:
        return {
            "status": "incomplete",
            "missing": [_label("supplier_name")],
            "collected": {_label(k): v for k, v in mapped.items() if v is not None},
            "hint": "请补充：供应商名称（向用户追问后再调用本工具，不要猜测）",
        }
    remark = str(mapped.get("remark") or "").strip()

    row_fields: dict[str, Any] = {
        "供应商名称": name,
        "审计状态": PENDING_STATUS,
        "申请日期": _today_ms(),
    }
    if remark:
        row_fields["备注"] = remark

    adapter = get_adapter()
    try:
        validate_write_fields(SUPPLIER_DIRECTORY_TABLE, row_fields)
        created = await adapter.create_record(SUPPLIER_DIRECTORY_TABLE, row_fields)
    except WarehouseBitableError:
        logger.warning(
            "供应商名录表写入失败（坐标未配置或表不可用）: supplier=%r", name
        )
        return {
            "error": (
                "供应商名录功能未就绪：名录表尚未接入或暂时不可用。"
                "请联系管理员在系统配置中心 → Bitable 连接中配置供应商名录表坐标。"
            ),
            "error_code": "supplier_directory_unavailable",
        }
    record_id = str(created.get("record_id") or "")
    if not record_id:
        return {
            "error": "供应商名录建行未返回记录 ID，请稍后重试",
            "error_code": "no_record_id",
        }

    # QA 确认门（与 QA 放行门同开关同目标；关 → 只建行不建门）
    from app.modules.warehouse import confirm_request as cr
    from app.modules.warehouse.qc_flow import (
        SUPPLIER_ADMIT_BIZ,
        qa_confirm_target,
        qc_writeback_allowed,
    )

    gate_created = False
    gate_deduped = False
    if qc_writeback_allowed(SUPPLIER_ADMIT_BIZ):
        try:
            async with _db_session() as db:
                if await _pending_admission_exists(db, name):
                    gate_deduped = True
                else:
                    request = await cr.create_request(
                        db,
                        business_type=SUPPLIER_ADMIT_BIZ,
                        title="供应商准入确认",
                        summary=(
                            f"**供应商** {name}\n"
                            f"**申请备注** {remark or '-'}\n\n"
                            "采购已申请该供应商准入，名录表已生成待准入记录。"
                            "点击「确认」将回写台账：审计状态=准入、准入日期=今天；"
                            "如需拒绝/暂停，请直接在多维表格操作（本卡可忽略）。"
                        ),
                        ref_table=SUPPLIER_DIRECTORY_TABLE,
                        ref_record_ids=[record_id],
                        target=qa_confirm_target(),
                        payload={
                            "supplier_name": name,
                            "record_id": record_id,
                            "requested_by": open_id,
                        },
                        writeback={"审计状态": "准入", "准入日期": "@today"},
                    )
                    sent = await cr.send_request_card(request)
                    if not sent:
                        logger.error(
                            "准入确认卡发送失败: request_no=%s", request.request_no
                        )
                    gate_created = True
        except Exception:  # noqa: BLE001 — 建门失败不回滚已建名录行
            logger.exception("供应商准入门创建失败: supplier=%r", name)
            gate_created = False

    logger.info(
        "供应商准入申请已登记: supplier=%r record_id=%s gate=%s dedup=%s",
        name,
        record_id,
        gate_created,
        gate_deduped,
    )
    if gate_created:
        message = (
            f"已生成「{name}」的待准入名录记录，并发送 QA 确认卡（确认后回写"
            "审计状态=准入、准入日期=今天）。"
        )
    elif gate_deduped:
        message = (
            f"已补录「{name}」的待准入名录记录；该供应商已有待确认的准入申请，"
            "未重复发送确认卡。"
        )
    else:
        message = (
            f"已生成「{name}」的待准入名录记录（台账回写功能当前停用，"
            "待 QA 在多维表格中直接处理）。"
        )
    return {
        "status": "ok",
        "record_id": record_id,
        "supplier_name": name,
        "gate_created": gate_created,
        "gate_deduped": gate_deduped,
        "message": message + " 请提醒用户可在 Base 查看记录状态。",
    }


# ── 注册表（并入 query.TOOL_FUNCS / TOOLS，见 query.py 尾部）──

SUPPLIER_TOOL_FUNCS: dict[str, Callable[..., Any]] = {
    "create_supplier_admission": create_supplier_admission,
}

SUPPLIER_TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_supplier_admission",
            "description": (
                "申请供应商准入（用户说「申请准入供应商 XXX」等时用）：在"
                "供应商名录表生成待准入记录并发 QA 确认卡。返回 error 时"
                "如实转告（名录未接入/已有待确认申请），不要重试硬写。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fields": {
                        "type": "object",
                        "description": (
                            "字段名 → 值。供应商名称 为必收（逐字使用用户"
                            "提供的名称）；备注 选填"
                        ),
                    },
                },
                "required": ["fields"],
            },
        },
    },
]
