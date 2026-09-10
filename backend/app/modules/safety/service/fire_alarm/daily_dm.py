"""消防报警日报私发 — 一卡一条 DM 给报警部门负责人 + 分管安全员。

用户确认（2026-08-28）：
- 固定模板 v2（见 build_alarm_card docstring：③ 整改建议（AI）、🔗 [查看记录](url)）
- 独立定时任务「消防报警日报私发」每日 17:00 触发（scheduler.py 注册；
  service 入口 run_daily_fire_alarm_dm：同步 → 生成复用/补齐 AI 分析 → 本模块私发）
- 开关 SAFETY_FIRE_ALARM_DAILY_DM_ENABLED 默认 false（未开启直接跳过，不阻塞其他任务）

参照「未更新进展」催办卡（feishu/progress_card.py）：
- 一卡一条，red header，DM 到人（收件人即本人，正文不 @）

身份链路（cross-app open_id 问题，scripts/tmp/_send_dunning_to_persons.py 已验证）：
- 收件人名单 = DEPT_CONFIG（leader / safety_officer 人工维护权威名单），部门名先
  DEPT_NORMALIZE 归一化；未命中配置时负责人回退记录自带 department_leader_name
  （安全员无回退：部门暂未配置安全员则本条只发给负责人）
- union_id：姓名 → identity.users.email → contact batch_get_id（≤50 条/批）
  → receive_id_type=union_id 发送（identity.users 的 open_id 跨应用不可用）
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.feishu.dept_config import DEPARTMENT_CONFIG
from app.modules.safety.feishu.notification import send_user_card
from app.modules.safety.service.hazard_supervision import DEPT_NORMALIZE

logger = logging.getLogger(__name__)

# 私发开关（默认关；确认后再置 true，17:00 随日报自动私发）
DM_ENABLED = os.getenv("SAFETY_FIRE_ALARM_DAILY_DM_ENABLED", "false").lower() == "true"

# 卡片 header 标题颜色（参照「未更新进展」卡：red）
HEADER_TEMPLATE = "red"

# 私发追加收件人规则：部门（DEPT_NORMALIZE 归一化后）→ {role: name}。
# 用户确认（2026-08-31）：提炼工程一部除现有推送人员外，同步推送给分管领导吴志华；
# 卡片不区分收件人角色，推送内容与现有收件人完全一致。
EXTRA_DM_RECIPIENTS: dict[str, dict[str, str]] = {
    "提炼工程一部": {"分管领导": "吴志华"},
}

# batch_get_id 单批上限（飞书 contact API 限制 50 条/批）
_BATCH_GET_ID_LIMIT = 50

_BASE_URL = "https://j0eukrlohu.feishu.cn/base"


def _record_link(record: Any) -> str:
    """查看记录链接（模板：🔗 [查看记录](url)）。"""
    rid = getattr(record, "feishu_record_id", "") or ""
    if not rid:
        return "🔗 查看记录（无原表链接）"
    from app.modules.safety.service.fire_alarm.renderer import _fire_conn_tokens

    app_token, table_id = _fire_conn_tokens()
    return f"🔗 [查看记录]({_BASE_URL}/{app_token}?table={table_id}&record={rid})"


def build_alarm_card(
    record: Any, leader_name: str | None = None,
) -> tuple[str, dict]:
    """构建一卡一条的报警卡片（模板 v2），返回 (markdown 正文, 卡片 dict)。

    模板：
      **{部门}** ｜ 🚨 **{报警类型}**｜{报警性质}
      ⏰ 报警时间：{M/D HH:MM}
      📍 部位：{楼栋}{部位}
      ① **报警原因**：{原因}
      ② **原因分析（AI）**：{AI}
      ③ **整改建议（AI）**：{AI}
      部门负责人：{姓名}
      🔗 [查看记录](url)

    - 收件人即本人：不 @ 收件人；部门负责人行展示生效负责人姓名
      （DEPT_CONFIG 优先，调用方传入；未传取记录自带字段）
    - 无楼栋/部位显示「待确认」；AI 字段/原因缺失时对应行省略
    """
    dept = getattr(record, "department", "") or "部门待确认"
    place = f"{getattr(record, 'building', '') or ''}{getattr(record, 'location', '') or ''}"
    place = place or "待确认"
    from app.modules.safety.service.fire_alarm.service import _bj  # UTC → 北京时间

    lines = [
        f"**{dept}** ｜ 🚨 **{getattr(record, 'alarm_type', '') or '?'}**"
        f"｜{getattr(record, 'alarm_nature', '') or '?'}",
        f"⏰ 报警时间：{_bj(getattr(record, 'alarm_time', None))}",
        f"📍 部位：{place}",
    ]
    cause = (getattr(record, "cause_description", "") or "").strip()
    if cause:
        lines.append(f"① **报警原因**：{cause[:100]}")
    reason = (getattr(record, "ai_reason_analysis", "") or "").strip()
    if reason:
        lines.append(f"② **原因分析（AI）**：{reason[:120]}")
    direction = (getattr(record, "ai_rectification_direction", "") or "").strip()
    if direction:
        lines.append(f"③ **整改建议（AI）**：{direction[:80]}")
    effective_leader = (leader_name or "").strip() or (
        getattr(record, "department_leader_name", "") or ""
    )
    if effective_leader:
        lines.append(f"部门负责人：{effective_leader}")
    lines.append(_record_link(record))
    content = "\n".join(lines)

    card = {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"🚨 消防报警 · {dept}"},
            "template": HEADER_TEMPLATE,
        },
        "body": {"elements": [{"tag": "markdown", "content": content}]},
    }
    return content, card


def dept_recipients(record: Any) -> dict[str, str]:
    """按部门解析收件人（role → 姓名）；DEPT_CONFIG 优先，负责人回退记录自带字段。

    EXTRA_DM_RECIPIENTS 命中时追加该部门额外收件人（如提炼工程一部 → 分管领导
    吴志华）；卡片不分角色，追加人与现有收件人收到内容完全一致的卡片。

    Returns:
        {"部门负责人": "张三", "分管安全员": "李四", ...}；均无/未配置时返回空 dict。
    """
    dept = getattr(record, "department", "") or ""
    normalized = DEPT_NORMALIZE.get(dept, dept)
    cfg = DEPARTMENT_CONFIG.get(normalized, {})
    out: dict[str, str] = {}
    leader = (cfg.get("leader") or "").strip() or (
        (getattr(record, "department_leader_name", "") or "").strip()
    )
    if leader:
        out["部门负责人"] = leader
    officer = (cfg.get("safety_officer") or "").strip()
    if officer:
        out["分管安全员"] = officer
    for role, name in EXTRA_DM_RECIPIENTS.get(normalized, {}).items():
        if name and name not in out.values():
            out[role] = name
    return out


def collect_recipient_plans(
    records: list[Any],
) -> list[tuple[Any, dict[str, str]]]:
    """每条报警 → 收件人计划（record, {role: name}）。"""
    return [(r, dept_recipients(r)) for r in records]


async def load_identity_emails(session: AsyncSession, names: set[str]) -> dict[str, str]:
    """identity.users 姓名 → 邮箱（batch_get_id 查 union_id 的前置）。"""
    if not names:
        return {}
    result = await session.execute(
        text(
            "SELECT name, email FROM identity.users "
            "WHERE name = ANY(:names) AND is_deleted = false"
        ),
        {"names": list(names)},
    )
    return {row[0]: row[1] for row in result.fetchall() if row[1]}


async def resolve_union_ids(token: str, emails: set[str]) -> dict[str, str]:
    """contact batch_get_id 邮箱 → union_id（≤50 条/批，跨应用 DM 用 union_id）。"""
    email_to_uid: dict[str, str] = {}
    email_list = sorted(emails)
    async with httpx.AsyncClient(timeout=30) as http:
        for i in range(0, len(email_list), _BATCH_GET_ID_LIMIT):
            batch = email_list[i:i + _BATCH_GET_ID_LIMIT]
            resp = await http.post(
                "https://open.feishu.cn/open-apis/contact/v3/users/batch_get_id",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                params={"user_id_type": "union_id"},
                json={"emails": batch},
            )
            data = resp.json()
            if not isinstance(data, dict) or data.get("code", 0) != 0:
                logger.warning("batch_get_id 失败: %s", data.get("msg") if isinstance(data, dict) else "?")
                continue
            for item in data.get("data", {}).get("user_list", []):
                email = item.get("email", "")
                uid = item.get("user_id", "")
                if email and uid:
                    email_to_uid[email] = uid
    return email_to_uid


async def send_daily_alarm_dms(
    session: AsyncSession, records: list[Any],
) -> dict[str, int]:
    """按「一卡一条」私发窗口内报警给部门负责人 + 分管安全员。

    Args:
        session: DB session（查 identity.users 邮箱）
        records: 窗口报警记录（17:00 与群日报同窗口；调用方查询传入，便于测试注入）

    Returns:
        {"sent", "skipped", "errors", "unresolved"}：
        sent=发送成功卡片数；skipped=发送返回失败；
        errors=异常条数；unresolved=收件人未解析到 union_id 条数
        （开关关闭时返回 {"disabled": 1, ...全 0}）
    """
    if not DM_ENABLED:
        logger.info("消防报警日报私发已关闭 (SAFETY_FIRE_ALARM_DAILY_DM_ENABLED=false)")
        return {"disabled": 1, "sent": 0, "skipped": 0, "errors": 0, "unresolved": 0}
    if not records:
        logger.info("消防报警日报私发：窗口内无报警记录")
        return {"sent": 0, "skipped": 0, "errors": 0, "unresolved": 0}

    plans = collect_recipient_plans(records)
    names = {name for _, roles in plans for name in roles.values() if name}
    name_to_email = await load_identity_emails(session, names)
    missing_email = names - set(name_to_email)
    if missing_email:
        logger.warning("身份表未找到邮箱（跳过收件）: %s", "、".join(sorted(missing_email)))

    from app.modules.safety.feishu.client import get_safety_feishu_client, get_safety_tenant_token

    client = await get_safety_feishu_client()
    token = await get_safety_tenant_token(client)
    email_to_uid = await resolve_union_ids(token, set(name_to_email.values()))

    sent = skipped = errors = unresolved = 0
    for record, roles in plans:
        leader_name = roles.get("部门负责人")
        for role, name in roles.items():
            email = name_to_email.get(name, "")
            uid = email_to_uid.get(email, "") if email else ""
            if not uid:
                unresolved += 1
                logger.warning("收件人未解析 union_id: role=%s name=%s dept=%s", role, name, getattr(record, "department", "?"))
                continue
            try:
                content, card = build_alarm_card(record, leader_name=leader_name)
                title = card["header"]["title"]["content"]
                ok = await send_user_card(
                    open_id=uid, title=title, content=content,
                    id_type="union_id", header_template=HEADER_TEMPLATE,
                )
                if ok:
                    sent += 1
                    logger.info("消防报警私发成功: record_id=%s %s=%s", getattr(record, "id", "?"), role, name)
                else:
                    skipped += 1
                    logger.warning("消防报警私发失败: record_id=%s %s=%s", getattr(record, "id", "?"), role, name)
            except Exception:
                errors += 1
                logger.exception("消防报警私发异常: record_id=%s %s=%s", getattr(record, "id", "?"), role, name)

    logger.info("消防报警日报私发完成: sent=%d skipped=%d errors=%d unresolved=%d", sent, skipped, errors, unresolved)
    return {"sent": sent, "skipped": skipped, "errors": errors, "unresolved": unresolved}
