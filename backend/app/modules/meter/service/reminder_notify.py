"""检定到期飞书通知：卡片构建与发送编排。"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import today as time_today
from app.modules.meter import repository as repo

logger = logging.getLogger(__name__)

_CALIBRATION_RANGE_LABELS: dict[str, str] = {
    "due_today": "⚠️ 今天到期",
    "due_7d": "📅 未来 7 天到期",
    "due_30d": "📅 未来 30 天到期",
    "due_90d": "📅 未来 90 天到期",
}


def _build_reminder_card(
    department_name: str,
    groups: dict[str, list[dict[str, Any]]],
) -> str:
    """构建飞书卡片 markdown 正文。空窗口自动隐藏。"""
    lines = [
        f"**📋 仪表到期提醒 — {department_name}**",
        "",
    ]

    for key in ("due_today", "due_7d", "due_30d", "due_90d"):
        items = groups.get(key, [])
        if not items:
            continue  # 空窗口不显示
        label = _CALIBRATION_RANGE_LABELS[key]
        lines.append(f"**{label}**：{len(items)} 台")
        lines.append("")
        for item in items:
            lines.append(
                f"器具名称：{item.get('instrument_name', '-')}\n"
                f"器具编号：{item.get('serial_number') or '-'}\n"
                f"位置信息：{item.get('location') or '-'}"
            )
            lines.append("")
        lines.append("")

    return "\n".join(lines)


async def send_calibration_reminders(db: AsyncSession) -> dict[str, Any]:
    """扫描所有开启提醒的部门，发送检定到期飞书通知。

    在每个部门的通知中，按 4 个时间节点分组展示标准器具和探测器的到期记录。
    通知发送失败不影响其他部门的处理。
    """
    from app.core.config import get_settings
    from app.platform.integrations.feishu.notification import send_user_card

    settings = get_settings()
    if not settings.METER_CALIBRATION_AUTO_NOTIFY_ENABLED:
        logger.info("全局自动提醒开关已关闭，跳过发送")
        return {"sent": 0, "skipped": 0, "errors": 0}

    depts = await repo.get_notifiable_departments(db)
    if not depts:
        logger.info("没有需要发送提醒的部门")
        return {"sent": 0, "skipped": 0, "errors": 0}

    # 预加载 identity.users 的 name → feishu_user_id 映射（user_id 跨应用有效）
    from sqlalchemy import select as sa_select

    from app.platform.identity.models import User

    name_to_user_id: dict[str, str] = {}
    users_result = await db.execute(
        sa_select(User.name, User.feishu_user_id).where(
            User.is_deleted == False,  # noqa: E712
            User.feishu_user_id.isnot(None),
            User.feishu_user_id != "",
        )
    )
    for row in users_result.all():
        name_to_user_id[row[0]] = row[1]

    today = time_today()
    sent = 0
    skipped = 0
    errors = 0

    for dept in depts:
        heads_list: list[dict[str, str]] = dept.heads or []  # type: ignore[assignment]
        if not heads_list:
            skipped += 1
            continue

        # 查询标准器具 + 探测器到期记录
        inst_groups = await repo.list_instruments_due_grouped(db, dept.name)
        det_groups = await repo.list_gas_detectors_due_grouped(db, dept.name)

        # 合并两个数据源，按 4 节点分组
        merged: dict[str, list[dict[str, Any]]] = {
            "due_today": [],
            "due_7d": [],
            "due_30d": [],
            "due_90d": [],
        }

        for key in merged:
            for inst in inst_groups.get(key, []):
                # 跳过检定单位为"计量室"或已停用的器具
                if inst.calibration_unit == "计量室":
                    continue
                if inst.status == "停用":
                    continue
                days = (inst.next_calibration_date - today).days if inst.next_calibration_date else None
                merged[key].append({
                    "source": "instrument",
                    "serial_number": inst.serial_number,
                    "instrument_name": inst.instrument_name,
                    "location": inst.location,
                    "next_calibration_date_str": inst.next_calibration_date.isoformat() if inst.next_calibration_date else None,
                    "days_until_due": days,
                })
            for det in det_groups.get(key, []):
                # 跳过检测单位为"计量室"或已停用的探测器
                if det.detection_unit == "计量室":
                    continue
                if det.status == "停用":
                    continue
                days = (det.next_calibration_date - today).days if det.next_calibration_date else None
                merged[key].append({
                    "source": "gas_detector",
                    "serial_number": det.product_number,
                    "instrument_name": det.instrument_name,
                    "location": det.installation_location,
                    "next_calibration_date_str": det.next_calibration_date.isoformat() if det.next_calibration_date else None,
                    "days_until_due": days,
                })

        total_items = sum(len(v) for v in merged.values())
        if total_items == 0:
            skipped += 1
            continue

        # 构建并发送卡片（给每个负责人各发一份）
        content = _build_reminder_card(dept.name, merged)
        title = f"📋 仪表到期提醒 - {dept.name}"

        all_ok = True
        for head in heads_list:
            head_name = head.get("name", "未知")
            # 优先使用 user_id（应用无关），其次回退到 open_id
            feishu_id = name_to_user_id.get(head_name, "")
            receive_id_type: str = "user_id"
            if not feishu_id:
                feishu_id = head.get("feishu_open_id", "").strip()
                receive_id_type = "open_id"
            if not feishu_id:
                # 负责人无法解析为飞书 ID：视为未送达，避免该部门被误计为 sent
                all_ok = False
                logger.warning(
                    "检定到期提醒负责人无飞书 ID: 部门=%s, 负责人=%s",
                    dept.name, head_name,
                )
                continue
            ok = await send_user_card(
                open_id=feishu_id,
                title=title,
                content=content,
                receive_id_type=receive_id_type,
            )
            if not ok:
                all_ok = False
                logger.error(
                    "检定到期提醒发送失败: 部门=%s, 负责人=%s",
                    dept.name, head_name,
                )

        if all_ok:
            sent += 1
            logger.info(
                "检定到期提醒已发送: 部门=%s, 负责人数=%d, 共 %d 条",
                dept.name, len(heads_list), total_items,
            )
        else:
            errors += 1

    logger.info(
        "检定到期提醒发送完成: sent=%d, skipped=%d, errors=%d",
        sent, skipped, errors,
    )
    return {"sent": sent, "skipped": skipped, "errors": errors}


# ═══════════════════════════════════════════
# Excel 台账导入
# ═══════════════════════════════════════════

# 列头匹配：标准化后的列名 → DB 字段名
