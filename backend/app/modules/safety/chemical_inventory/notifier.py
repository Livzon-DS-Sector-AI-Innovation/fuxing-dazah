"""危化品库存预警群通知。

模板 + 部门→分管安全员映射 + @mention，复用隐患督办的 send_group_card 与
IdentityResolver.resolve_safety_officer（DEPT_CONFIG.safety_officer）。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.modules.safety.feishu.identity_resolver import IdentityResolver
from app.modules.safety.feishu.notification import send_group_card
from app.modules.safety.schemas.chemical_inventory import CHEMICAL_DEPARTMENT_LABELS

logger = logging.getLogger(__name__)

# ── 化学库存部门枚举 → 部门中文名（权威映射在 schemas.chemical_inventory）──
DEPARTMENT_LABELS = CHEMICAL_DEPARTMENT_LABELS

# ── 化学库存部门枚举 → identity 标准部门名（用于查 DEPT_CONFIG 的安全员）──
# 注：化学台账部门名与 identity.departments/DEPT_CONFIG 的键不一致，此处做对齐映射；
#     发酵一部/二部共用「发酵工程部」，提炼二期/二部共用「提炼工程二部」，待业务确认。
DEPT_ENUM_TO_IDENTITY: dict[str, str] = {
    "warehouse": "仓储部",
    "extraction_1": "提炼工程一部",
    "extraction_2": "提炼工程二部",
    "extraction_2b": "提炼工程二部",
    "fermentation_1": "发酵工程部",
    "fermentation_2": "发酵工程部",
    "strain": "菌种中心",
    "qc": "质量控制部（QC部）",
    "env": "环保工程中心",
    "purification": "精制工程一部",
    "semi_synth": "提炼半合成工程中心",
    "tech_refine": "提炼技术精进中心",
}

# ── 预警类型 → 中文标签 ──
ALERT_TYPE_LABELS: dict[str, str] = {
    "over_limit": "超量",
    "near_limit": "临限",
    "high_ratio": "高占比",
    "unclassified": "未分类",
    "unit_anomaly": "单位异常",
    "special_storage": "专库违规",
}


def _at(person, open_id: str | None = None) -> str:
    """ResolvedPerson → 飞书卡片 @mention（需安全应用作用域 open_id）。

    ⚠️ ``person.open_id`` 来自 ``identity.users.feishu_open_id``（平台应用同步），
    跨应用无效（99992361 open_id cross app）。调用方应先用
    ``feishu.mention.resolve_open_ids`` 解析出安全应用 open_id 再传入。
    """
    from app.modules.safety.feishu import mention

    if not person:
        return ""
    return mention.at_tag(person.name, open_id)


def build_alert_content(
    warnings: list[Any],
    officer_by_dept: dict[str, Any],
    officer_mention_id: dict[str, str] | None = None,
) -> str:
    """生成预警群通知 Markdown。

    Args:
        officer_by_dept: {部门枚举: ResolvedPerson}
        officer_mention_id: {安全员姓名: 安全应用 open_id}（@ 提及用，可空）
    """
    mention_ids = officer_mention_id or {}
    by_dept: dict[str, list[Any]] = {}
    for r in warnings:
        by_dept.setdefault(r.department, []).append(r)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"📅 {now}",
        f"⚠️ 本次扫描发现 **{len(warnings)} 条预警**，涉及 **{len(by_dept)} 个部门**：",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    for dept_enum, records in sorted(by_dept.items()):
        label = DEPARTMENT_LABELS.get(dept_enum, dept_enum)
        officer = officer_by_dept.get(dept_enum)
        mention = _at(officer, mention_ids.get(officer.name, "") if officer else "")
        lines.append(f"**{label}** {mention}")
        for r in records:
            types = "、".join(ALERT_TYPE_LABELS.get(t, t) for t in (r.risk_note or []))
            if r.total_quantity_t is not None and r.max_limit is not None:
                detail = f"（{r.total_quantity_t} / 上限 {r.max_limit} T）"
            else:
                detail = ""
            lines.append(f"· {r.material_name}：{types}{detail}")
        lines.append("")

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━",
        "👉 请各分管安全员核实库存并整改；整改后在总表更新数量，风险将自动重算。",
    ])
    return "\n".join(lines)


async def notify_warnings(
    db,
    warnings: list[Any],
    chat_id: str,
    *,
    title: str = "危化品库存预警",
) -> str | None:
    """把预警按部门分组，@对应分管安全员，发群卡片。

    Args:
        warnings: risk_flag == "warn" 的 ChemicalInventoryRecord 列表
        chat_id: 飞书群聊 chat_id（未配置则调用方跳过）
    Returns:
        成功返回 message_id，失败/跳过返回 None
    """
    if not chat_id or not warnings:
        return None

    resolver = IdentityResolver(db)
    officer_by_dept: dict[str, Any] = {}
    for dept_enum in {r.department for r in warnings}:
        identity_name = DEPT_ENUM_TO_IDENTITY.get(dept_enum)
        if not identity_name:
            continue
        try:
            officer = await resolver.resolve_safety_officer(identity_name)
            if officer:
                officer_by_dept[dept_enum] = officer
        except Exception:  # noqa: BLE001
            logger.exception("解析部门安全员失败: %s", dept_enum)

    # @ 提及需安全应用作用域 open_id（平台同步的 open_id 跨应用无效）
    from app.modules.safety.feishu import mention

    officer_mention_id = await mention.resolve_open_ids(
        p.name for p in officer_by_dept.values() if p
    )

    content = build_alert_content(warnings, officer_by_dept, officer_mention_id)
    try:
        return await send_group_card(
            chat_id=chat_id,
            title=title,
            content=content,
            header_template="red",
        )
    except Exception:  # noqa: BLE001
        logger.exception("危化品库存预警群通知发送失败")
        return None
