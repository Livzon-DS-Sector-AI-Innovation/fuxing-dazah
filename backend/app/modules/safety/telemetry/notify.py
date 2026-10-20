"""报警通知出口：飞书群卡 + 安全速递格子（facilities-p2 票 02）。

单卡批量：一轮多台设备命中合并一张卡（@安管 + 各设备责任部门负责人），
绝不逐条轰炸（与校验任务合并通知同一铁律）。速递格子 key=telemetry_alarm：
当日监控报警口径（新增报警 + 未闭环计数）。
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.app_config.store import store as _app_config_store
from app.modules.safety.feishu.daily_digest import DigestCell, upsert_daily_digest
from app.modules.safety.feishu.notification import send_group_card
from app.modules.safety.models import TelemetryAlarmRecord

logger = logging.getLogger(__name__)

DIGEST_KEY = "telemetry_alarm"

# @安管收报人：与 scheduler.ALERT_NOTIFY_OPEN_ID 单点同步（延迟 import
# 避免模块级拉起整个 scheduler）
def _alert_notify_open_id() -> str:
    from app.modules.safety.scheduler import ALERT_NOTIFY_OPEN_ID

    return ALERT_NOTIFY_OPEN_ID

_FALLBACK_CHAT_ID = "oc_f05532603bd7682fc520929c01aca88d"


def alarm_chat_id() -> str:
    """报警目标群：SAFETY_TELEMETRY_ALARM_CHAT_ID → 回落一期批次卡群。"""
    value = _app_config_store.get_str("SAFETY_TELEMETRY_ALARM_CHAT_ID", "")
    if value:
        return value
    return _app_config_store.get_str(
        "SAFETY_FACILITY_NOTICE_CHAT_ID", _FALLBACK_CHAT_ID,
    )


def _bj_today() -> date:
    return (datetime.now(UTC) + timedelta(hours=8)).date()


def _at(open_id: str | None, name: str | None = None) -> str:
    if open_id:
        return f'<at user_id="{open_id}"></at>'
    return name or ""


def build_alarm_card(
    alarms: list[TelemetryAlarmRecord],
    *,
    owner_by_equipment: dict[str, tuple[str | None, str | None]] | None = None,
) -> tuple[str, str, list[dict] | None]:
    """报警群卡（纯函数）：标题 / 正文 markdown / 按钮元素。

    owner_by_equipment：设备编号 → (负责人 open_id, 负责人姓名)。
    按钮元素：底部「值班确认」一键 ack 本轮全部 firing（resolve 须填处置
    说明，指引到 Web 监控子区操作）。
    """
    owners = owner_by_equipment or {}
    alert_open_id = _alert_notify_open_id()
    level_label = {"alarm": "🔴 报警", "warning": "🟡 预警"}
    lines: list[str] = []
    seen_equipment: set[str] = set()
    for a in alarms:
        lines.append(
            f"- **{a.equipment_no}** {a.metric} {a.value:g}"
            f"（{level_label.get(a.level, a.level)}）{a.rule_desc}"
            f"｜{a.recorded_at.strftime('%H:%M')}"
        )
        seen_equipment.add(a.equipment_no)
    title = f"特种设备监控报警 {len(alarms)} 条"
    mention_md = " ".join(
        [_at(alert_open_id)]
        + [_at(oid, name) for (oid, name) in owners.values() if oid]
    )
    content = "\n".join(
        [
            f"**本轮命中 {len(alarms)} 条规则**，请及时确认处置：",
            *lines,
            "",
            mention_md,
            "",
            "处置完成后请到「安全管理 → 设备设施管理 → 特种设备 → 监控」填写处置说明闭环。",
        ]
    )
    firing_ids = [str(a.id) for a in alarms if a.status == "firing"]
    if firing_ids:
        elements = [{
            "tag": "action",
            "actions": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": "✅ 值班确认（本轮全部）"},
                "type": "primary",
                "value": {
                    "scope": "telemetry_alarm",
                    "action": "ack_all",
                    "alarm_ids": firing_ids,
                },
            }],
        }]
    return title, content, elements


async def _open_alarm_count(session: AsyncSession) -> int:
    return int(
        await session.scalar(
            select(func.count(TelemetryAlarmRecord.id)).where(
                TelemetryAlarmRecord.is_deleted.is_(False),
                TelemetryAlarmRecord.status != "resolved",
            )
        )
        or 0
    )


async def _resolve_department_owners(
    session: AsyncSession,
    equipment_info: dict[str, dict[str, Any]] | None,
    equipments: list[str],
) -> dict[str, tuple[str | None, str | None]]:
    """设备 → (负责人 open_id, 姓名)：equipment_info 提供 department，走
    IdentityResolver 部门负责人解析（复用一期口径；失败退化纯文本姓名）。"""
    if not equipment_info:
        return {}
    try:
        from app.modules.safety.feishu.identity_resolver import IdentityResolver

        resolver = IdentityResolver(session)
    except Exception:
        logger.warning("报警卡负责人解析器不可用，@ 仅安管", exc_info=True)
        return {}
    out: dict[str, tuple[str | None, str | None]] = {}
    for eq in equipments:
        department = (equipment_info.get(eq) or {}).get("department")
        if not department:
            continue
        try:
            person = await resolver.resolve_department_leader(department)
        except Exception:
            person = None
        if person is not None:
            out[eq] = (getattr(person, "open_id", None), getattr(person, "name", None))
    return out


class TelemetryAlarmNotifier:
    """真实报警通知：一轮命中合并单卡发目标群 + 速递格子并入。

    发送失败只告警不抛（fail-open：报警已落库，通知可补）。
    """

    def __init__(
        self,
        *,
        sender: Any = None,
        digest: Any = None,
        chat_id: str | None = None,
        equipment_info: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._sender = sender or send_group_card
        self._digest = digest or upsert_daily_digest
        self._chat_id = chat_id
        self._equipment_info = equipment_info

    async def on_alarms(
        self, session: AsyncSession, alarms: list[TelemetryAlarmRecord]
    ) -> None:
        if not alarms:
            return
        equipment_info = self._equipment_info or {}
        owners = await _resolve_department_owners(
            session, equipment_info, [a.equipment_no for a in alarms]
        )
        title, content, elements = build_alarm_card(
            alarms, owner_by_equipment=owners
        )
        chat = self._chat_id or alarm_chat_id()
        try:
            await self._sender(chat, title, content, elements, header_template="red")
        except Exception:
            logger.warning("遥测报警群卡发送失败（不中断）", exc_info=True)

        try:
            open_count = await _open_alarm_count(session)
            firing = sum(1 for a in alarms if a.status == "firing")
            await self._digest(
                _bj_today(),
                DIGEST_KEY,
                DigestCell(
                    tag_color="red",
                    tag_text="监控报警",
                    title="特种设备监控报警",
                    stats=(
                        f"本轮新增 **{firing}** 条｜未闭环 **{open_count}** 条"
                    ),
                    zone="锅炉群抄表读数超限即时报警（处置见报警列表）",
                    detail="\n".join(f"- {a.rule_desc}（{a.equipment_no}）" for a in alarms[:10]),
                ),
            )
        except Exception:
            logger.warning("遥测报警速递格子写入失败（不中断）", exc_info=True)


class NoopNotifier:
    """空通知（测试注入）。"""

    async def on_alarms(
        self, session: AsyncSession, alarms: list[TelemetryAlarmRecord]
    ) -> None:
        return None
