"""链5：违章→定向培训触发单轮（要点卡生成 + 培训行创建 + 推送开关默认关）。

判定口径（spec 链5 节）：处理方式=停工培训 或 违章等级∈{严重,重大}，
且「定向培训」列为空。幂等与自愈（双键互备，消除卡死窗口）：
- 主幂等键=违章行「定向培训」非空（含人工已闭环记录）；
- 自愈键=培训表已存在 关联违章编号=违章行 record_id 的行——标记缺失时
  只补写标记（AI 不重跑、不重复建行），覆盖"培训行已建但标记写失败"窗口。

写序：先建培训行再写标记——create 失败=下轮重试（无孤儿）；标记写失败=
下轮走自愈路径。每轮批上限 BATCH_LIMIT 条（AI 逐条串行，防止整轮无上限）。

推送开关 SAFETY_TB_RETRAINING_PUSH_ENABLED（app_config 注册，env/DB/配置页
三通道可翻，默认关）：关=不调任何发送函数，内容全部落表可审；审核通过后
置 True 即启用，无需发版。

消费方：scheduled.py S6 单轮（backflow 之后，后台派发执行）。
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from app.modules.safety.ai_violation_retraining import (
    ViolationRetrainingError,
    ViolationRetrainingInput,
    ViolationRetrainingPlugin,
)
from app.modules.safety.service.bitable_direct import fields as bd_fields
from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.bitable_direct.errors import BitableConfigError
from app.modules.safety.service.training_behavior.common import Opener, bj_today

logger = logging.getLogger(__name__)

PUSH_SWITCH_KEY = "SAFETY_TB_RETRAINING_PUSH_ENABLED"
_PUSH_CHAT_KEY = "SAFETY_TB_RETRAINING_PUSH_CHAT_ID"

_TRAINING_HANDLING = "停工培训"
_TRAINING_LEVELS = ("严重", "重大")
_PENDING_PREFIX = "已生成待推送"
# 每轮处理上限：AI 逐条串行，5 条≈数十秒级；积压由后续轮自然排空
BATCH_LIMIT = 5

_VIOLATION_READ_FIELDS = (
    "违章日期", "违章人员", "所属单位", "违章类别", "违章等级",
    "违章描述", "处理方式", "状态", "关联隐患编号", "定向培训",
)


def default_push_enabled() -> bool:
    """推送开关：app_config store（env/DB/配置页可翻），默认关。"""
    from app.modules.safety.app_config.store import store

    return store.get_bool(PUSH_SWITCH_KEY, False)


def needs_training(fields: dict[str, Any]) -> bool:
    handling = bd_fields.select(fields, "处理方式")
    level = bd_fields.select(fields, "违章等级")
    if handling == _TRAINING_HANDLING:
        return True
    return level in _TRAINING_LEVELS


async def run_retraining_round(
    *,
    opener: Opener | None = None,
    ai_service: Any = None,
    push_enabled: Callable[[], bool] | None = None,
    send_card: Callable[..., Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """单轮触发：需培训违章生成要点卡并建培训行；单行失败逐行降级不阻断。

    Returns: {"status": ok|not_connected, "generated": n, "repaired": r,
              "pushed": m, "failed": k, "deferred": 超批上限延后条数}
    """
    open_client = opener or bd_reader.resolve_client
    try:
        violation_client = open_client("training_behavior", "violation")
        training_client = open_client("training_behavior", "training")
    except BitableConfigError as exc:
        logger.info("定向培训触发跳过（域未接入）: %s", exc)
        return {"status": "not_connected", "generated": 0}

    if ai_service is None:
        from app.modules.safety.service.config import create_ai_service

        ai_service = create_ai_service("text")
    plugin = ViolationRetrainingPlugin(ai_service)
    is_push_on = (push_enabled or default_push_enabled)()

    records = await violation_client.list_all_records(
        field_names=list(_VIOLATION_READ_FIELDS), strict=True
    )
    training_rows = await training_client.list_all_records(
        field_names=["关联违章编号"], strict=True
    )
    linked_ids = {
        link
        for r in training_rows
        if (link := bd_fields.text(r.get("fields") or {}, "关联违章编号"))
    }

    pending: list[tuple[str, dict[str, Any]]] = []
    repairable: list[tuple[str, dict[str, Any]]] = []
    for record in records:
        fields = record.get("fields") or {}
        record_id = str(record.get("record_id") or "")
        if not record_id or bd_fields.text(fields, "定向培训"):
            continue
        if not needs_training(fields):
            continue
        if record_id in linked_ids:
            repairable.append((record_id, fields))  # 培训行在、标记丢：补标记
        else:
            pending.append((record_id, fields))

    deferred = max(0, len(pending) - BATCH_LIMIT)
    generated = repaired = pushed = failed = 0
    today = bj_today().isoformat()

    for record_id, fields in repairable:
        try:
            await violation_client.update_record(
                record_id=record_id,
                fields={"定向培训": f"已生成待推送（{today}·自培训行修复）"},
            )
            repaired += 1
        except Exception as exc:
            failed += 1
            logger.warning("定向培训标记修复失败（%s）: %s", record_id, exc)

    for record_id, fields in pending[:BATCH_LIMIT]:
        try:
            output = await plugin.generate(ViolationRetrainingInput(
                description=bd_fields.text(fields, "违章描述") or "",
                category=bd_fields.select(fields, "违章类别"),
                level=bd_fields.select(fields, "违章等级"),
                handling=bd_fields.select(fields, "处理方式"),
                department=bd_fields.select(fields, "所属单位"),
                person_name=bd_fields.person(fields, "违章人员"),
                hazard_no=bd_fields.text(fields, "关联隐患编号"),
            ))
        except ViolationRetrainingError as exc:
            failed += 1
            logger.warning("要点卡生成失败（%s）: %s", record_id, exc)
            continue

        card = output.card_markdown
        desc = bd_fields.text(fields, "违章描述") or record_id
        try:
            # 先建培训行：失败=无标记留痕，下轮整体重试
            await training_client.create_record(fields={
                "培训名称": f"定向培训：{desc[:30]}",
                "培训类别": "专项培训",
                "状态": "未开始",
                "关联违章编号": record_id,
                "备注": card,
            })
        except Exception as exc:
            failed += 1
            logger.warning("定向培训行创建失败（%s）: %s", record_id, exc)
            continue
        try:
            await violation_client.update_record(
                record_id=record_id,
                fields={"定向培训": f"{_PENDING_PREFIX}（{today}）\n{card}"},
            )
        except Exception as exc:
            # 培训行已建：下轮自愈路径补标记，此处不算失败
            logger.warning(
                "定向培训标记写入失败（%s），下轮自愈: %s", record_id, exc
            )
        generated += 1

        if is_push_on:
            sender = send_card or _default_send_card
            try:
                await sender(
                    card_markdown=card,
                    summary=output.summary,
                    description=desc,
                    record_id=record_id,
                )
                pushed += 1
            except Exception as exc:  # 推送失败不影响闭环落表
                logger.warning("要点卡推送失败（%s）: %s", record_id, exc)

    if generated or repaired or failed or deferred:
        logger.info(
            "定向培训触发：生成 %s（修复 %s，推送 %s，失败 %s，延后 %s）",
            generated, repaired, pushed, failed, deferred,
        )
    return {
        "status": "ok", "generated": generated, "repaired": repaired,
        "pushed": pushed, "failed": failed, "deferred": deferred,
    }


async def _default_send_card(**kwargs: Any) -> None:
    """推送出口（占位）：开关开且群已配时记录待发事实，真实发送随启用批接入。"""
    from app.modules.safety.app_config.store import store

    chat_id = store.get_str(_PUSH_CHAT_KEY, None)
    if not chat_id:
        logger.warning(
            "推送开关已开但 %s 未配置，要点卡仅落表（record=%s）",
            _PUSH_CHAT_KEY, kwargs.get("record_id"),
        )
        return
    logger.info(
        "要点卡推送出口为占位（未实发，chat=%s record=%s；真实发送随启用批接入）",
        chat_id, kwargs.get("record_id"),
    )
