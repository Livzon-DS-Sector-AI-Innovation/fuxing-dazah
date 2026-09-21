"""推送场景确认门接入（V3.0 分期A Ticket 07，验收②）。

stale_lists（超6月/不合格清单）推送发送成功后，自动为「待跟进不合格物料」
（处理日期为空）创建整单确认单并随清单卡送达（质询 Round 1 定案）：
- 确认 → 逐条回写 unqualified_stock.处理日期=今天（毫秒时间戳，Base 日期
  字段写入契约）；处理方式留 Base 人工填（1C 二值定案）；
- 目标 = 推送任务首个目标（整单确认语义：一次业务事件一张确认单）；
- 无待跟进条目不创建；清单卡发送失败不挂确认卡。

注册方式仿 draft_flow SCENE_CONFIG：engine 模块尾部 import 本模块即注册
post-send 钩子（见 engine.SCENE_POST_SEND_HOOKS）。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter
from app.modules.warehouse.bitable_cells import cell_text
from app.modules.warehouse.models import WarehouseConfirmRequest
from app.modules.warehouse.push_center.engine import (
    register_post_send_hook,
)
from app.modules.warehouse.push_center.store import PushTaskView

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")

# 不合格清单回写业务类型（确认单 business_type）
UNQUALIFIED_DISPOSITION = "unqualified_disposition"

# 拉取字段（确认卡摘要 + 待跟进判定用）
_UNQUALIFIED_FIELDS = ["物料名称", "不合格项目", "处理方式", "处理日期"]


# 回写映射：处理日期=确认执行当天（@today 哨兵由 confirm_request 在确认时
# 解析为当天毫秒时间戳，Base date 字段写入契约）
UNQUALIFIED_WRITEBACK = {"处理日期": "@today"}


def _display(value: Any) -> str:
    """单元格值 → 卡片展示文本（规范解析，空值显示 -）。"""
    return cell_text(value) or "-"


async def fetch_unqualified_records(adapter: Any) -> list[dict[str, Any]]:
    """分页拉取不合格物料清单（带 record_id；处理日期为空 = 待跟进）。

    分页/截断防御委托 finished_data.fetch_all_records（分期D 收敛，
    原内联 500×10 循环与之逐字等价）。
    """
    from app.modules.warehouse.finished_data import fetch_all_records

    return await fetch_all_records(adapter, "unqualified_stock", _UNQUALIFIED_FIELDS)


async def stale_lists_confirm_hook(
    db: AsyncSession,
    view: PushTaskView,
    now: datetime,
    *,
    dry_run: bool | None = None,
) -> WarehouseConfirmRequest | None:
    """stale_lists 推送后置钩子：为待跟进不合格物料创建并投递整单确认卡。

    钩子失败不影响清单推送本身（engine 已捕获）；返回创建的确认单
    （未创建返回 None）。
    """
    from app.modules.warehouse import confirm_request as cr
    from app.modules.warehouse.base_mirror import bitable_writeback_enabled

    if not view.targets:
        return None
    # 回写总开关（默认关）：确认门的存在意义是回写 Base，停用期间不建单
    if not bitable_writeback_enabled():
        logger.info("清单确认门跳过：多维表格回写开关关闭")
        return None
    records = await fetch_unqualified_records(WarehouseBitableAdapter())
    # 待跟进 = 处理日期为空（None/空串/空数组/空类型包装，规范解析后为空）
    pending = [
        r
        for r in records
        if not cell_text((r.get("fields") or {}).get("处理日期"))
    ]
    if not pending:
        logger.info("清单确认门跳过：无待跟进（处理日期为空）不合格物料")
        return None

    record_ids = [str(r["record_id"]) for r in pending]
    top_lines = "\n".join(
        f"{i}. {_display((r.get('fields') or {}).get('物料名称'))}"
        f"（{_display((r.get('fields') or {}).get('不合格项目'))}）"
        for i, r in enumerate(pending[:5], start=1)
    )
    request = await cr.create_request(
        db,
        business_type=UNQUALIFIED_DISPOSITION,
        title="不合格物料处理确认",
        summary=(
            f"今日清单中有 **{len(pending)}** 条不合格物料待跟进处理"
            f"（处理日期为空）：\n{top_lines}"
            f"\n\n点击「确认」表示以上条目已跟进处理，将回写台账「处理日期=今天」；"
            f"处理方式请在多维表格中人工填写。"
        ),
        ref_table="unqualified_stock",
        ref_record_ids=record_ids,
        target=view.targets[0],
        payload={
            "task": view.task_name,
            "total": len(pending),
            "items": [
                {"物料名称": _display((r.get("fields") or {}).get("物料名称"))}
                for r in pending[:10]
            ],
        },
        writeback=dict(UNQUALIFIED_WRITEBACK),
    )
    sent = await cr.send_request_card(request, dry_run=dry_run)
    if not sent:
        logger.error(
            "清单确认卡发送失败: request_no=%s target=%s",
            request.request_no, request.target,
        )
    else:
        logger.info(
            "清单确认卡已送达: request_no=%s 待跟进=%d 条",
            request.request_no, len(pending),
        )
    return request


register_post_send_hook("stale_lists", stale_lists_confirm_hook)


# ── V3.0 分期D：成品退货/不合格处理方案门（§4.8④）──

# 确认单业务类型（非 QC 链路，仅受 A 期总开关 bitable_writeback_enabled 管辖）
FINISHED_DISPOSITION_BIZ = "finished_disposition"

# 回写映射：处理确认日期=确认执行当天（@today 哨兵）；处理进度为公式列
# 只读，确认回写走 D 期 API 建列「处理确认日期」（退货/不合格两表各一列）
FINISHED_DISPOSITION_WRITEBACK = {"处理确认日期": "@today"}


async def finished_disposition_confirm_hook(
    db: AsyncSession,
    view: PushTaskView,
    now: datetime,
    *,
    dry_run: bool | None = None,
) -> list[WarehouseConfirmRequest]:
    """成品待处理清单推送后置钩子：按表分单建处理方案确认卡。

    退货汇总表/不合格产品汇总表各一张整单卡（ref_record_ids=各自待处理行，
    处理确认日期为空）；入库台账待处理批次仅清单展示不入门。目标=推送任务
    首个目标；无待处理或开关关闭不建单。
    """
    from app.modules.warehouse import base_mirror
    from app.modules.warehouse import confirm_request as cr
    from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter
    from app.modules.warehouse.finished_data import (
        SOURCE_RETURNS,
        SOURCE_UNQUALIFIED,
        fetch_pending_dispositions,
    )

    if not view.targets:
        return []
    if not base_mirror.bitable_writeback_enabled():
        logger.info("成品处理方案门跳过：多维表格回写开关关闭")
        return []
    pending = await fetch_pending_dispositions(WarehouseBitableAdapter())
    created: list[WarehouseConfirmRequest] = []
    plans = (
        (SOURCE_RETURNS, "finished_returns", "退货"),
        (SOURCE_UNQUALIFIED, "finished_unqualified", "不合格"),
    )
    for source, table_key, label in plans:
        rows = [r for r in pending if r.source == source]
        if not rows:
            continue
        top_lines = "\n".join(
            f"{i}. {r.product_name or '-'}（{r.spec or '-'}）批 {r.batch_no or '-'}｜"
            f"{r.qty if r.qty is not None else '-'}{r.unit}"
            for i, r in enumerate(rows[:5], start=1)
        )
        request = await cr.create_request(
            db,
            business_type=FINISHED_DISPOSITION_BIZ,
            title=f"成品{label}处理方案确认",
            summary=(
                f"今日清单中有 **{len(rows)}** 条成品{label}待处理"
                f"（处理确认日期为空）：\n{top_lines}"
                f"\n\n点击「确认」表示以上条目处理方案已制定，将回写台账"
                f"「处理确认日期=今天」；处理进度请在多维表格中人工跟进。"
            ),
            ref_table=table_key,
            ref_record_ids=[r.record_id for r in rows],
            target=view.targets[0],
            payload={
                "task": view.task_name,
                "total": len(rows),
                "items": [
                    {"产品名称": r.product_name, "批号": r.batch_no} for r in rows[:10]
                ],
            },
            writeback=dict(FINISHED_DISPOSITION_WRITEBACK),
        )
        sent = await cr.send_request_card(request, dry_run=dry_run)
        if not sent:
            logger.error(
                "成品%s确认卡发送失败: request_no=%s target=%s",
                label, request.request_no, request.target,
            )
        else:
            logger.info(
                "成品%s确认卡已送达: request_no=%s 待处理=%d 条",
                label, request.request_no, len(rows),
            )
        created.append(request)
    if not created:
        logger.info("成品处理方案门跳过：无待处理（处理确认日期为空）行")
    return created


register_post_send_hook(
    "finished_disposition_lists", finished_disposition_confirm_hook
)


__all__ = [
    "UNQUALIFIED_DISPOSITION",
    "FINISHED_DISPOSITION_BIZ",
    "fetch_unqualified_records",
    "stale_lists_confirm_hook",
    "finished_disposition_confirm_hook",
]
