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
    """分页拉取不合格物料清单（带 record_id；处理日期为空 = 待跟进）。"""
    records: list[dict[str, Any]] = []
    page_token: str | None = None
    for _ in range(10):  # 分页上限防御（每页 500，>5000 条截断）
        page = await adapter.search_records_page(
            "unqualified_stock",
            filter_json=None,
            field_names=_UNQUALIFIED_FIELDS,
            limit=500,
            page_token=page_token,
        )
        records.extend(page.get("records") or [])
        page_token = page.get("page_token")
        if not page_token:
            break
    return records


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

    if not view.targets:
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

__all__ = [
    "UNQUALIFIED_DISPOSITION",
    "fetch_unqualified_records",
    "stale_lists_confirm_hook",
]
