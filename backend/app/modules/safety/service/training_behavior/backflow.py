"""链4：隐患表三违回流单轮——读 hazard 域全量，幂等建违章档案行。

设计：docs/DESIGN-教育培训与行为管控域-AI参与式管理设计-20261022.md 链4
（回流 A 入口）；行构造复用 seed_data.plan_backfill（幂等键=关联隐患编号）。
消费方：scheduled.py 单轮 interval 任务。
"""

from __future__ import annotations

import logging
from typing import Any

from app.modules.safety.service.bitable_direct import fields as bd_fields
from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.bitable_direct.errors import BitableConfigError
from app.modules.safety.service.training_behavior import seed_data
from app.modules.safety.service.training_behavior.common import Opener

logger = logging.getLogger(__name__)

_HAZARD_READ_FIELDS = (
    seed_data.HAZARD_NO, seed_data.HAZARD_CATEGORY_AI,
    seed_data.HAZARD_DESC_AI, seed_data.HAZARD_DESC, seed_data.HAZARD_DATE,
)


async def run_backflow_round(*, opener: Opener | None = None) -> dict[str, Any]:
    """单轮回流：新三违作业行 → 违章档案初始行（违章人/定性留待人工）。

    任一域未接入时软跳过（status=not_connected），不抛出——回流是增益任务，
    不能因域未点亮拖垮调度轮。
    """
    open_client = opener or bd_reader.resolve_client
    try:
        hazard_client = open_client("hazard", "hazard")
        violation_client = open_client("training_behavior", "violation")
    except BitableConfigError as exc:
        logger.info("三违回流跳过（域未接入）: %s", exc)
        return {"status": "not_connected", "created": 0}

    hazard_records = await hazard_client.list_all_records(
        field_names=list(_HAZARD_READ_FIELDS), page_size=500, strict=True
    )
    existing = await violation_client.list_all_records(
        field_names=["关联隐患编号"], strict=True
    )
    existing_nos = {
        no
        for r in existing
        if (no := bd_fields.text(r.get("fields") or {}, "关联隐患编号"))
    }
    plan = seed_data.plan_backfill(hazard_records, existing_nos)
    for row in plan:
        await violation_client.create_record(fields=row)
    if plan:
        logger.info("三违回流：新建违章档案 %s 条", len(plan))
    return {"status": "ok", "created": len(plan), "existing": len(existing_nos)}
