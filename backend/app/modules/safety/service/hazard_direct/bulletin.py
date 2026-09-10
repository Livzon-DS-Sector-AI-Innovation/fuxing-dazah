"""④ 隐患督办通报（周四 08:30）— 直读多维表格。

改造前：读 DB（``get_hazards_for_notification``）→ 渲染 → 推群。
改造后：读 **多维表格**（``督办等级`` 为红色/一般预警、且未关闭非整改中）→ 渲染 → 推群。
渲染格式与原实现保持一致（部门分组、只列红色预警明细、底部部门汇总）。

「未更新进展」标记不再落库，改为调用 ``progress_track.compute_marks`` 现算
（Redis 跟踪进展内容变化时间）。
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from app.modules.safety.service.hazard_direct import bitable_repo, progress_track

logger = logging.getLogger(__name__)

# 隐患等级英文 → 中文（与旧实现同口径）
HAZARD_LEVEL_CN: dict[str, str] = {
    "general": "一般",
    "serious": "较大",
    "major": "重大",
}
EXCLUDED_DEPARTMENTS: tuple[str, ...] = ("AI创新部",)


async def _fetch_targets(client: Any) -> list[dict[str, Any]]:
    """取通报目标：督办等级为红色/一般预警的记录（后续再按状态/部门过滤）。"""
    def cond(name: str, op: str, value: list[str]) -> dict[str, Any]:
        return {"field_name": name, "operator": op, "value": value}

    records: list[dict[str, Any]] = await client.list_all_records(
        filter_info={
            "conjunction": "or",
            "conditions": [
                cond(bitable_repo.F_SUPERVISION, "is", ["红色预警"]),
                cond(bitable_repo.F_SUPERVISION, "is", ["一般预警"]),
            ],
        },
        page_size=500,
        strict=True,
    )
    return records


def _dept_name(view: bitable_repo.HazardView) -> str:
    from app.modules.safety.service.hazard_supervision import DEPT_NORMALIZE

    raw = (view.department or "").strip()
    if not raw:
        return "未分配部门"
    return DEPT_NORMALIZE.get(raw, raw)


def _level_label(level: str | None) -> str:
    return HAZARD_LEVEL_CN.get(level or "", level or "-")


async def _load_person_open_ids(names: list[str]) -> dict[str, str]:
    """责任人姓名 → @ 提及用 open_id（安全应用作用域，跨应用修正）。

    注意：``identity.users.feishu_open_id`` 是平台应用同步的，对安全应用无效
    （99992361 open_id cross app），统一走 ``feishu.mention`` 重新解析。
    """
    from app.modules.safety.feishu import mention

    return await mention.resolve_open_ids(names)


def _record_link(view: bitable_repo.HazardView, app_token: str, table_id: str) -> str:
    if not (view.record_id and app_token and table_id):
        return ""
    url = (
        f"https://j0eukrlohu.feishu.cn/base/{app_token}"
        f"?table={table_id}&record={view.record_id}"
    )
    return f"[📋 查看记录]({url})"


async def build_bulletin() -> tuple[str, dict[str, Any]]:
    """生成督办通报 Markdown（不推送）。"""
    from app.modules.safety.bitable_config.store import store
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient
    from app.modules.safety.service.responsible_mapping import (
        effective_responsible_person,
    )

    client = SafetyBitableClient()
    records = await _fetch_targets(client)
    views: list[bitable_repo.HazardView] = []
    for rec in records:
        view = bitable_repo.to_view(rec)
        if view.rectification_status in ("closed", "in_progress"):
            continue  # 已关闭 / 整改中不通报
        if (view.department or "") in EXCLUDED_DEPARTMENTS:
            continue
        if bitable_repo.is_audit_record(view.raw):
            continue  # 外审记录不统计（当前主表不含，防御性过滤）
        desc = (view.description or "").strip()
        if not desc or desc == "待AI填写":
            continue  # 异常占位记录
        views.append(view)

    now = datetime.now().strftime("%Y-%m-%d")
    stats: dict[str, Any] = {"total": len(views), "urgent": 0, "warning": 0, "marked": 0}
    if not views:
        return (
            f"【隐患督办通报】\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 {now}\n\n"
            f"✅ **今日无红色预警/一般预警隐患**\n"
        ), stats

    # 未更新进展标记（现算，不落库）
    marks = await progress_track.compute_marks(views)
    for view in views:
        view.supervision_progress_status = marks.get(view.record_id)

    # 责任人 → open_id
    persons = {
        effective_responsible_person(
            view.department, view.rectification_responsible_person_name
        )
        for view in views
    }
    persons.discard("")
    person_open_id = await _load_person_open_ids(list(persons))

    conn = store.get_connection("hazard", "hazard")
    app_token = conn.app_token if conn and conn.status != "disabled" else ""
    table_id = conn.table_id if conn and conn.status != "disabled" else ""

    def _person_at(name: str) -> str:
        from app.modules.safety.feishu import mention

        return mention.at_tag(name, person_open_id.get(name, ""))

    def _full_desc(view: bitable_repo.HazardView) -> str:
        return (view.description or "(无描述)").replace("\n", " ").replace("\r", " ")

    urgent_by_dept: dict[str, list[bitable_repo.HazardView]] = defaultdict(list)
    dept_warning_count: dict[str, int] = defaultdict(int)
    departments: set[str] = set()
    for view in views:
        dept = _dept_name(view)
        departments.add(dept)
        if view.supervision_level == "红色预警":
            urgent_by_dept[dept].append(view)
        else:
            dept_warning_count[dept] += 1

    sorted_depts = sorted(
        departments,
        key=lambda d: (len(urgent_by_dept.get(d, [])), dept_warning_count.get(d, 0)),
        reverse=True,
    )

    dept_persons: dict[str, list[str]] = {}
    for dept, items in urgent_by_dept.items():
        seen: list[str] = []
        for view in items:
            person = effective_responsible_person(
                view.department, view.rectification_responsible_person_name
            )
            if person and person not in seen:
                seen.append(person)
        if seen:
            dept_persons[dept] = seen

    total_urgent = sum(len(v) for v in urgent_by_dept.values())
    total_warning = sum(dept_warning_count.values())
    total_no_progress = sum(
        1 for v in views
        if v.supervision_progress_status == progress_track.PROGRESS_STATUS_NOT_UPDATED
    )
    stats.update(
        urgent=total_urgent, warning=total_warning, marked=total_no_progress
    )

    parts: list[str] = ["【隐患督办通报】", "━━━━━━━━━━━━━━━━━━━━", f"📅 {now}", ""]
    parts.append(
        f"🔴 红色预警 **{total_urgent}** 条  ·  "
        f"🟡 一般预警 **{total_warning}** 条  ·  "
        f"涉及 **{len(sorted_depts)}** 个部门"
    )
    if total_no_progress:
        parts.append(f"⚠️ 未更新进展 **{total_no_progress}** 条")
    parts.append("")

    for dept in sorted_depts:
        items = urgent_by_dept.get(dept, [])
        if not items:
            continue
        count_str = f"（{len(items)}条）" if len(items) > 1 else ""
        mentions = "　".join(_person_at(p) for p in dept_persons.get(dept, []))
        dept_head = f"**{dept}{count_str}**"
        if mentions:
            dept_head += f"　{mentions}"
        parts.append(dept_head)

        for idx, view in enumerate(items, 1):
            days = (
                (datetime.now(UTC).date() - view.discovered_at.date()).days
                if view.discovered_at else 0
            )
            level_label = _level_label(view.hazard_level_manual or view.hazard_level)
            if level_label not in ("-",) and not level_label.endswith("隐患"):
                level_label += "隐患"
            inspection = (view.inspection_category or "-").replace(", ", "、").replace(",", "、")
            link = _record_link(view, app_token, table_id)
            no_progress_flag = (
                "　⚠️**未更新进展**"
                if view.supervision_progress_status
                == progress_track.PROGRESS_STATUS_NOT_UPDATED else ""
            )
            parts.append(f"**{idx}.** {_full_desc(view)}")
            parts.append(
                f"等级：{level_label}｜检查类型：{inspection}｜{days}天{no_progress_flag}"
            )
            if link:
                parts.append(link)
        parts.append("")

    parts.append("━━━━━━━━━━━━━━━━━━━━")
    parts.append("📌 各部门未关闭隐患数量汇总")
    parts.append("━━━━━━━━━━━━━━━━━━━━")
    for dept in sorted_depts:
        ug = len(urgent_by_dept.get(dept, []))
        wn = dept_warning_count.get(dept, 0)
        segs: list[str] = []
        if ug:
            segs.append(f"红色预警 {ug} 条")
        if wn:
            segs.append(f"一般预警 {wn} 条")
        parts.append(f"**{dept}**：{'　+　'.join(segs)}")
    parts.append("")

    return "\n".join(parts), stats


async def send_bulletin(chat_id: str | None = None) -> dict[str, Any]:
    """生成并推送督办通报到群聊。"""
    from app.modules.safety.feishu.notification import send_group_card

    content, stats = await build_bulletin()
    if not chat_id:
        logger.warning("④ 未配置推送群聊，仅生成不推送")
        stats["sent"] = False
        return stats
    try:
        ok = await send_group_card(
            chat_id=chat_id, title="隐患督办通报", content=content
        )
        stats["sent"] = bool(ok)
        if ok:
            logger.info("④ 督办通报已发送: %s", stats)
        else:
            logger.error("④ 督办通报发送失败: %s", stats)
    except Exception:
        logger.exception("④ 督办通报推送异常")
        stats["sent"] = False
    return stats
