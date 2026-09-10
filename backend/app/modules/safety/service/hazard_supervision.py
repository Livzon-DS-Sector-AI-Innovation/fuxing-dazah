"""隐患督办 Service — 等级计算 + 批量更新 + 通知推送.

核心功能:
1. calculate_supervision_level() — 单条隐患的督办等级判定（纯函数）
2. calculate_all_open() — 每日 07:30 计算督办等级（只扫描会变化的记录：未关闭/整改中残留/已关闭未置 closed）
3. send_notifications() — 每周四 08:30 读取已计算结果并推送通知

等级判定规则（优先级从高到低）：
0. 整改状态 = 已关闭 → closed（最高优先级，不可覆盖）
1. 隐患等级（人工）= 较大/重大 → 红色预警（不受天数限制）
2. 检查日期(discovered_at)距今 >30天 → 红色预警
3. ≤30天 → 一般预警
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.modules.safety.bitable_config.store import store
from app.modules.safety.feishu.notification import send_group_card, send_user_card
from app.modules.safety.models import HazardReport
from app.modules.safety.service.responsible_mapping import effective_responsible_person

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════

# 通知接收人（固定为许康福）
NOTIFY_OPEN_ID = "ou_495039d6335d347b07ff92ad982b3b4e"
# 每日督办通报群聊 — 安全AI创新交流群
BULLETIN_CHAT_ID = "oc_f05532603bd7682fc520929c01aca88d"

# 通知开关
NOTIFICATION_ENABLED = os.getenv("SAFETY_SUPERVISION_NOTIFICATION_ENABLED", "false").lower() == "true"
TEST_MODE = os.getenv("SAFETY_SUPERVISION_TEST_MODE", "true").lower() == "true"

# 等级中文标签映射
LEVEL_LABELS = {
    "红色预警": "红色预警",
    "一般预警": "一般预警",
    "closed": "已关闭",
}
LEVEL_EMOJI = {
    "红色预警": "🔴",
    "一般预警": "🟡",
}
# 隐患等级英文 → 中文
HAZARD_LEVEL_CN = {
    "general": "一般",
    "serious": "较大",
    "major": "重大",
}
# 部门名称标准化 — 仅处理缩写展开（纯字符串替换，不做组织归属推断）
# 组织归属推断由责任人反查 identity.users 完成（数据修复脚本）
DEPT_NORMALIZE: dict[str, str] = {
    "提炼六部": "提炼工程六部",
    "环保": "环保工程中心",
    "环保危废": "环保工程中心",
    "环保重点项目": "环保工程中心",
    "发酵车间": "发酵工程部",
    "设备工程部, 项目部": "设备工程部",
    "设备工程部项目部": "设备工程部",
}


# ═══════════════════════════════════════════════════════════════
# 等级计算（纯函数，所有入口复用）
# ═══════════════════════════════════════════════════════════════

def calculate_supervision_level(hazard: HazardReport) -> str:
    """计算单条隐患的督办等级。

    规则（优先级从高到低）：
    0. 整改状态为已关闭 → closed（最高优先级，不可被任何条件覆盖）
    1. 隐患等级（人工）为较大/重大 → 红色预警（不受天数限制）
    2. 检查日期（discovered_at）距今 >30天 → 红色预警
    3. ≤30天 → 一般预警
    """
    # 规则 0（最高优先级）：同步整改状态
    if hazard.rectification_status == "closed" or hazard.status == "closed":
        return "closed"

    # 规则 1：隐患等级（人工）为较大/重大 → 红色预警
    # 督办判定只取 hazard_level_manual（人工），忽略 AI 判定的 hazard_level
    # DB 兼容英文（serious/major）与中文（较大隐患/重大隐患）两种存储值
    if hazard.hazard_level_manual in ("serious", "major", "较大隐患", "重大隐患"):
        return "红色预警"

    # 规则 2-3：按存在天数分级（以检查日期 discovered_at 起算）
    if hazard.discovered_at is None:
        return "一般预警"

    days = (date.today() - hazard.discovered_at.date()).days

    if days > 30:
        return "红色预警"
    return "一般预警"


# 「未更新进展」标记值（supervision_progress_status 为 NULL 表示正常）
PROGRESS_STATUS_NOT_UPDATED = "未更新进展"
# 距上次进展更新超过多少天打标记（与周四通报节奏对齐，7 天）
PROGRESS_STALE_DAYS = 7

# 不参与督办的测试部门（测试记录，不计算/不通报/不通知）
EXCLUDED_TEST_DEPARTMENTS: tuple[str, ...] = ("AI创新部",)


def _is_audit_source(hazard: HazardReport) -> bool:
    """是否外审记录（notes._audit_source 非空）。

    外审记录的源表不同步「目前进展」字段，参与进展检查会导致误标。
    """
    try:
        notes = json.loads(hazard.notes) if hazard.notes else {}
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(notes, dict) and bool(notes.get("_audit_source"))


def compute_progress_status_at_bulletin(hazard: HazardReport, now: datetime | None = None) -> str | None:
    """通报时计算「未更新进展」标记（不再每日计算）。

    规则（仅督办中红色/一般预警、未关闭、非外审的隐患参与）：
    - 曾有进展更新（progress_note_updated_at 非空）→ 距上次更新 > PROGRESS_STALE_DAYS → 标记
    - 无进展内容（progress_note 为空）→ 按检查日期(discovered_at)起算，距今 > PROGRESS_STALE_DAYS
      仍无任何进展 → 标记（防止"从未更新"的存量/空值记录被漏过）
    - 其余情况 → 返回 None（不标记，调用方需清除旧标记）

    Args:
        hazard: 隐患记录（只读，不就地修改）
        now: 当前时间（测试注入用，缺省 UTC now）

    Returns:
        str | None: 应写入 supervision_progress_status 的值
    """
    if hazard.supervision_level not in ("红色预警", "一般预警"):
        return None
    if _is_audit_source(hazard):
        return None
    if hazard.rectification_status == "closed" or hazard.status == "closed":
        return None
    # 整改中不督办（本次规则：不标记整改中）
    if hazard.rectification_status == "in_progress":
        return None

    base = now if now is not None else datetime.now(UTC)
    updated = hazard.progress_note_updated_at
    progress = (hazard.progress_note or "").strip()

    if updated is not None:
        # 曾经更新过进展 → 按上次更新时间判断超期
        if base - updated > timedelta(days=PROGRESS_STALE_DAYS):
            return PROGRESS_STATUS_NOT_UPDATED
        return None

    if progress:
        # 有进展内容但无更新时间戳（异常）：不标记，避免误标
        return None

    # 从未填写任何进展 → 按检查日期起算，距今 > 阈值则标记
    if hazard.discovered_at is not None:
        if base - hazard.discovered_at > timedelta(days=PROGRESS_STALE_DAYS):
            return PROGRESS_STATUS_NOT_UPDATED
    return None


# ═══════════════════════════════════════════════════════════════
# HazardSupervisionService
# ═══════════════════════════════════════════════════════════════

class HazardSupervisionService:
    """隐患督办服务。

    供调度器和测试脚本使用，实例化时传入 AsyncSession。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── 07:30 全量计算 ────────────────────────────────────────

    async def calculate_all_open(self) -> tuple[dict[str, int], list[HazardReport]]:
        """全量计算督办等级（含双端同步）。

        处理范围：只扫描「会变化」的未删除隐患，避免每次重复扫全表：
          ① 未关闭非整改中 → 按规则重算（天数/人工等级会变化）
          ② 整改中但仍有督办等级残留 → 清空为 NULL
          ③ 已关闭但督办等级未置 closed → 补置 closed（双端同步）
        已关闭且督办等级已是 closed 的记录不再进入扫描集。
        等级判定：
          - 整改中(in_progress)：不督办，督办等级置空
          - 已关闭(closed)：督办等级置 closed
          - 未关闭其他状态：按 calculate_supervision_level 计算

        Returns:
            (stats, changed_hazards): stats 含计数统计，changed_hazards 为等级变化的记录列表
        """
        stmt = (
            select(HazardReport)
            .where(
                HazardReport.is_deleted == False,  # noqa: E712
                or_(
                    # ① 未关闭非整改中 → 按规则重算（天数/人工等级会变化）
                    and_(
                        HazardReport.rectification_status != "closed",
                        HazardReport.rectification_status != "in_progress",
                        HazardReport.status != "closed",
                    ),
                    # ② 整改中但仍有督办等级残留 → 清空为 NULL
                    and_(
                        HazardReport.rectification_status == "in_progress",
                        HazardReport.supervision_level.isnot(None),
                    ),
                    # ③ 已关闭但督办等级未置 closed → 补置（双端同步）
                    and_(
                        or_(
                            HazardReport.rectification_status == "closed",
                            HazardReport.status == "closed",
                        ),
                        HazardReport.supervision_level.is_distinct_from("closed"),
                    ),
                ),
                # 排除异常占位记录（描述为空/待AI填写，属人工误创建/删除）
                HazardReport.description.isnot(None),
                HazardReport.description != "",
                HazardReport.description != "待AI填写",
                # 排除测试部门（AI创新部等，测试记录不参与督办计算）
                or_(
                    HazardReport.department.is_(None),
                    HazardReport.department.notin_(EXCLUDED_TEST_DEPARTMENTS),
                ),
            )
            .order_by(HazardReport.department, HazardReport.discovered_at)
        )
        result = await self.session.execute(stmt)
        hazards = list(result.scalars().all())

        stats = {
            "total": len(hazards),
            "changed": 0,
            "红色预警": 0,
            "一般预警": 0,
            "closed": 0,
            "(空)": 0,
            "to_红色预警": 0,
            "to_一般预警": 0,
            "to_closed": 0,
            "to_空值": 0,
        }
        changed_hazards: list[HazardReport] = []

        for hazard in hazards:
            old_level = hazard.supervision_level
            if hazard.rectification_status == "in_progress":
                # 整改中：不督办，督办等级置空
                new_level = None
            elif hazard.rectification_status == "closed" or hazard.status == "closed":
                # 已关闭 → closed
                new_level = "closed"
            else:
                # 未关闭 → 按规则计算
                new_level = calculate_supervision_level(hazard)

            if new_level != old_level:
                hazard.supervision_level = new_level
                stats["changed"] += 1
                changed_hazards.append(hazard)
                # 追踪变化方向
                if new_level == "红色预警":
                    stats["to_红色预警"] += 1
                elif new_level == "一般预警":
                    stats["to_一般预警"] += 1
                elif new_level == "closed":
                    stats["to_closed"] += 1
                else:
                    stats["to_空值"] += 1

        # 全局分布：独立统计所有未删除隐患的督办等级，保证汇总数字真实
        # （扫描集只含待处理记录，已关闭且等级为 closed 的 1351 条不再进入扫描集）
        dist_stmt = (
            select(HazardReport.supervision_level, func.count())
            .where(
                HazardReport.is_deleted == False,  # noqa: E712
                # 与扫描集一致的异常占位排除
                HazardReport.description.isnot(None),
                HazardReport.description != "",
                HazardReport.description != "待AI填写",
                # 与扫描集一致的测试部门排除
                or_(
                    HazardReport.department.is_(None),
                    HazardReport.department.notin_(EXCLUDED_TEST_DEPARTMENTS),
                ),
            )
            .group_by(HazardReport.supervision_level)
        )
        dist_rows = await self.session.execute(dist_stmt)
        dist_counts = {row[0]: row[1] for row in dist_rows.all()}
        stats["红色预警"] = dist_counts.get("红色预警", 0)
        stats["一般预警"] = dist_counts.get("一般预警", 0)
        stats["closed"] = dist_counts.get("closed", 0)
        stats["(空)"] = dist_counts.get(None, 0)

        if stats["changed"] > 0:
            await self.session.commit()
            logger.info(
                "督办等级批量计算完成: total=%d changed=%d (→红色预警=%d →一般预警=%d →已关闭=%d →空值=%d)",
                stats["total"], stats["changed"],
                stats["to_红色预警"], stats["to_一般预警"],
                stats["to_closed"], stats["to_空值"],
            )
        else:
            logger.info("督办等级批量计算完成: total=%d 无变化", stats["total"])

        # 双端同步：无论每日定时还是手动触发，计算结果都推回 Bitable
        # 保证平台 DB 与多维表格「督办等级」字段一致
        if changed_hazards:
            await self.push_changed_to_bitable(changed_hazards)

        return stats, changed_hazards

    # ── 推回 Bitable ──────────────────────────────────────────

    async def push_changed_to_bitable(
        self, changed_hazards: list[HazardReport] | None = None,
    ) -> int:
        """将 supervision_level 发生变化的记录推回 Bitable（仅推督办等级字段）。

        Args:
            changed_hazards: calculate_all_open() 返回的变化记录列表。
                             为 None 时不做任何推送。

        Returns:
            成功推送的记录数
        """
        if not changed_hazards:
            return 0

        import asyncio
        import os

        import httpx

        from app.modules.safety.feishu.bitable_handler import SUPERVISION_LEVEL_REVERSE

        conn = store.get_connection("hazard", "hazard")
        if conn is None or conn.status == "disabled":
            logger.warning("Bitable 主表连接未配置/停用，跳过督办等级推回")
            return 0
        app_token = conn.app_token
        table_id = conn.table_id
        app_id = os.getenv("SAFETY_FEISHU_APP_ID", "")
        app_secret = os.getenv("SAFETY_FEISHU_APP_SECRET", "")

        # Get fresh token
        async with httpx.AsyncClient(timeout=30) as http:
            r = await http.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
            token = r.json()["tenant_access_token"]

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        base = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"

        pushed = 0
        for hazard in changed_hazards:
            if not hazard.feishu_record_id:
                continue
            # 外审记录不回写主表 Bitable（外审源表可能没有「督办等级」字段，且 record_id 不属于主表）
            try:
                import json as _json
                _notes = _json.loads(hazard.notes) if hazard.notes else {}
            except (_json.JSONDecodeError, TypeError):
                _notes = {}
            if isinstance(_notes, dict) and _notes.get("_audit_source"):
                continue
            # 整改中(空值) → 清空 Bitable 督办等级字段；有值 → 写入对应标签
            if hazard.supervision_level is None:
                bt_fields = {"督办等级": None}
            else:
                label = SUPERVISION_LEVEL_REVERSE.get(hazard.supervision_level, hazard.supervision_level or "")
                bt_fields = {"督办等级": label}
            try:
                async with httpx.AsyncClient(timeout=30) as http:
                    resp = await http.put(
                        f"{base}/{hazard.feishu_record_id}",
                        headers=headers,
                        json={"fields": bt_fields},
                    )
                    if resp.json().get("code") == 0:
                        pushed += 1
                await asyncio.sleep(0.3)
            except Exception:
                logger.exception("推回 Bitable 失败: hazard_id=%s", hazard.id)

        logger.info("督办等级推回 Bitable 完成: pushed=%d/%d", pushed, len(changed_hazards))
        return pushed

    # ── 07:30 计算结果群汇报 ──────────────────────────────────

    async def send_calculation_summary(self, stats: dict[str, int]) -> bool:
        """将 07:30 的计算结果汇总发送到「安全AI创新交流群」。

        Args:
            stats: calculate_all_open() 的返回值

        Returns:
            True if send succeeded
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        content = (
            f"【督办等级计算完成】\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 {now}\n\n"
            f"扫描未关闭隐患：**{stats['total']}** 条\n"
            f"等级变化：**{stats['changed']}** 条\n\n"
            f"变化明细：\n"
            f"  → 红色预警：{stats['to_红色预警']} 条\n"
            f"  → 一般预警：{stats['to_一般预警']} 条\n"
            f"  → 已关闭：{stats['to_closed']} 条\n\n"
            f"当前分布：\n"
            f"  🔴 红色预警：{stats.get('红色预警', 0)} 条\n"
            f"  🟡 一般预警：{stats.get('一般预警', 0)} 条\n"
            f"  已关闭：{stats.get('closed', 0)} 条\n"
        )

        try:
            result = await send_user_card(
                open_id=NOTIFY_OPEN_ID,
                title="督办等级计算完成",
                content=content,
            )
            if result:
                logger.info("督办计算结果已发送(测试): stats=%s", stats)
            return bool(result)
        except Exception:
            logger.exception("推送计算结果失败（测试模式）")
            return False

    # ── 08:30 督办通报 ────────────────────────────────────────

    @staticmethod
    def _dept_name(h: HazardReport) -> str:
        """获取责任部门名称，非标准名称自动归一化为 identity.departments 标准名称。"""
        raw = h.department or ""
        if not raw:
            return "未分配部门"
        return DEPT_NORMALIZE.get(raw, raw)

    @staticmethod
    def _level_label(level: str | None) -> str:
        """隐患等级英文 → 中文。"""
        return HAZARD_LEVEL_CN.get(level or "", level or "-")

    async def build_bulletin_content(self) -> str:
        """生成每日督办通报的 Markdown 内容（供 Agent 工具和群推送共用）。

        仅列出红色预警隐患的具体清单（一般预警只计数、不列明细）：
        部门标题统一展示条数与责任人（@ 一次），条目内不再重复责任人；
        条目紧凑连续无空行，附多维表格记录链接。

        Returns:
            完整的 Markdown 格式通报文本
        """

        hazards = await self.get_hazards_for_notification()
        now = datetime.now().strftime("%Y-%m-%d")

        if not hazards:
            return (
                f"【隐患督办通报】\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📅 {now}\n\n"
                f"✅ **今日无红色预警/一般预警隐患**\n"
            )

        # 批量加载责任人 → open_id 映射（用有效责任人：部门映射覆盖后）
        persons = {
            effective_responsible_person(h.department, h.rectification_responsible_person_name)
            for h in hazards
        }
        persons.discard("")
        person_open_id: dict[str, str] = {}
        if persons:
            # @ 提及需「安全应用作用域」open_id（平台同步的 open_id 跨应用无效）
            from app.modules.safety.feishu import mention

            person_open_id = await mention.resolve_open_ids(persons)

        # Bitable 链接（延迟读 store：改表 ID 后通报链接立即用新值）
        conn = store.get_connection("hazard", "hazard")
        app_token = conn.app_token if conn and conn.status != "disabled" else ""
        table_id = conn.table_id if conn and conn.status != "disabled" else ""

        def _person_at(name: str) -> str:
            """责任人 → @mention 或纯文本。"""
            from app.modules.safety.feishu import mention

            return mention.at_tag(name, person_open_id.get(name, ""))

        def _record_link(h: HazardReport) -> str:
            """多维表格记录链接。

            外审记录 → 从 notes._audit_source 读取源 Bitable
            主表记录 → store（hazard/hazard 连接，延迟读取）
            """
            import json as _json

            rid = h.feishu_record_id or ""
            if not rid:
                return ""

            # 尝试从 notes 取外审来源信息
            try:
                notes_obj = _json.loads(h.notes) if h.notes else {}
            except (_json.JSONDecodeError, TypeError):
                notes_obj = {}
            audit_src = notes_obj.get("_audit_source", {}) if isinstance(notes_obj, dict) else {}

            if audit_src.get("type") == "bitable":
                src_app = audit_src.get("app_token", "")
                src_table = audit_src.get("table_id", "")
                if src_app and src_table:
                    url = (
                        f"https://j0eukrlohu.feishu.cn/base/{src_app}"
                        f"?table={src_table}&record={rid}"
                    )
                    return f"[📋 查看记录]({url})"

            # 主表记录（notes 中无 _audit_source）
            if app_token and table_id:
                url = (
                    f"https://j0eukrlohu.feishu.cn/base/{app_token}"
                    f"?table={table_id}&record={rid}"
                )
                return f"[📋 查看记录]({url})"

            return ""

        def _full_desc(h: HazardReport) -> str:
            """完整显示隐患描述（换行转空格，避免破坏通报卡片排版）。"""
            return (h.description or "(无描述)").replace("\n", " ").replace("\r", " ")

        # 按部门分组（仅红色预警列明细；一般预警只在底部汇总计数，不单独展示）
        urgent_by_dept: dict[str, list[HazardReport]] = defaultdict(list)
        dept_warning_count: dict[str, int] = defaultdict(int)
        departments: set[str] = set()

        for h in hazards:
            dept = self._dept_name(h)
            departments.add(dept)
            if h.supervision_level == "红色预警":
                urgent_by_dept[dept].append(h)
            else:
                dept_warning_count[dept] += 1

        # 部门排序：红色预警数降序 → 一般预警数降序
        sorted_depts = sorted(
            departments,
            key=lambda d: (len(urgent_by_dept.get(d, [])), dept_warning_count.get(d, 0)),
            reverse=True,
        )

        # 每部门红色预警条目的有效责任人（去重，部门标题统一艾特一次，条目内不再重复展示）
        dept_persons: dict[str, list[str]] = {}
        for dept, items in urgent_by_dept.items():
            seen: list[str] = []
            for h in items:
                p = effective_responsible_person(h.department, h.rectification_responsible_person_name)
                if p and p not in seen:
                    seen.append(p)
            if seen:
                dept_persons[dept] = seen

        total_urgent = sum(len(v) for v in urgent_by_dept.values())
        total_warning = sum(dept_warning_count.values())
        total_no_progress = sum(1 for h in hazards if h.supervision_progress_status == PROGRESS_STATUS_NOT_UPDATED)

        parts: list[str] = []

        # ── 头部 ──
        parts.append("【隐患督办通报】")
        parts.append("━━━━━━━━━━━━━━━━━━━━")
        parts.append(f"📅 {now}")
        parts.append("")
        parts.append(
            f"🔴 红色预警 **{total_urgent}** 条  ·  "
            f"🟡 一般预警 **{total_warning}** 条  ·  "
            f"涉及 **{len(sorted_depts)}** 个部门"
        )
        if total_no_progress:
            parts.append(f"⚠️ 未更新进展 **{total_no_progress}** 条")
        parts.append("")

        # ── 红色预警明细（按部门：部门标题统一艾特责任人，条目紧凑连续、无空行）──
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

            for idx, h in enumerate(items, 1):
                desc = _full_desc(h)
                days = (date.today() - h.discovered_at.date()).days if h.discovered_at else 0
                # 展示优先用人工等级（与督办判定一致），缺失时回退 AI 等级
                level_label = self._level_label(h.hazard_level_manual or h.hazard_level)
                if level_label not in ("-",) and not level_label.endswith("隐患"):
                    level_label += "隐患"
                # Bitable 多选字段以逗号分隔存储，展示转为顿号
                inspection = (h.inspection_category or "-").replace(", ", "、").replace(",", "、")
                link = _record_link(h)
                no_progress_flag = (
                    "　⚠️**未更新进展**"
                    if h.supervision_progress_status == PROGRESS_STATUS_NOT_UPDATED else ""
                )
                parts.append(f"**{idx}.** {desc}")
                parts.append(
                    f"等级：{level_label}｜检查类型：{inspection}｜{days}天{no_progress_flag}"
                )
                if link:
                    parts.append(link)
            parts.append("")

        # ── 底部部门汇总 ──
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

        return "\n".join(parts)

    async def apply_progress_marks_at_bulletin(self) -> dict[str, int]:
        """通报前计算并落库「未更新进展」标记（仅通报时执行，不再每日计算）。

        规则（见 compute_progress_status_at_bulletin）：
        - 督办中（红色/一般预警）非外审、未关闭：
          · 曾更新进展但 >7 天未更新 → 标记
          · 从未更新（progress_note 为空）且检查日期距今 >7 天 → 标记
        - 非督办中 / 外审 / 已关闭 / 整改中：清除标记（不再参与）
        只更新标记值发生变化的记录，避免无意义写库。

        Returns:
            {"marked": 新增标记数, "cleared": 清除标记数}
        """
        stmt = (
            select(HazardReport)
            .where(
                HazardReport.is_deleted == False,  # noqa: E712
                or_(
                    HazardReport.supervision_level.in_(["红色预警", "一般预警"]),
                    HazardReport.supervision_progress_status == PROGRESS_STATUS_NOT_UPDATED,
                ),
            )
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        now = datetime.now(UTC)
        marked = cleared = 0
        changed_ids: list[str] = []
        for h in rows:
            new_status = compute_progress_status_at_bulletin(h, now)
            if h.supervision_progress_status != new_status:
                h.supervision_progress_status = new_status
                if new_status == PROGRESS_STATUS_NOT_UPDATED:
                    marked += 1
                else:
                    cleared += 1
                changed_ids.append(str(h.id))
        if changed_ids:
            await self.session.flush()
            logger.info(
                "通报时进展标记落库: marked=%d cleared=%d ids=%s",
                marked, cleared, ",".join(changed_ids[:20]),
            )
        return {"marked": marked, "cleared": cleared}

    async def send_supervision_bulletin(self, chat_id: str | None = None) -> bool:
        """发送隐患督办通报（默认安全AI创新交流群）。

        通报前先计算并落库「未更新进展」标记（仅在通报时计算，不再每日计算）。
        发送目标唯一来源：调度器配置（DB 播种/覆写），不再回退代码默认群。
        Returns:
            True if send succeeded
        """
        effective_chat_id = chat_id
        # ── 通报时计算「未更新进展」标记并落库 ──
        await self.apply_progress_marks_at_bulletin()
        await self.session.commit()

        content = await self.build_bulletin_content()
        try:
            result = await send_group_card(
                chat_id=effective_chat_id,
                title="隐患督办通报",
                content=content,
            )
            if result:
                logger.info("督办通报已发送(群聊)")
            return bool(result)
        except Exception:
            logger.exception("推送督办通报失败")
            return False

    # ── 督办催办卡片（未更新进展 → 卡片内提交）───────────────

    async def get_progress_dunning_hazards(self) -> list[HazardReport]:
        """查询需要催办进展的隐患（supervision_progress_status == 未更新进展）。

        排除已关闭记录、外审记录、整改中（整改中不督办不催办）。
        """
        stmt = (
            select(HazardReport)
            .where(
                HazardReport.is_deleted == False,  # noqa: E712
                HazardReport.supervision_progress_status == PROGRESS_STATUS_NOT_UPDATED,
                HazardReport.rectification_status != "closed",
                HazardReport.status != "closed",
                HazardReport.rectification_status != "in_progress",
                # 排除异常占位记录与标记残留的外审记录
                HazardReport.description.isnot(None),
                HazardReport.description != "",
                HazardReport.description != "待AI填写",
                or_(
                    HazardReport.notes.is_(None),
                    HazardReport.notes.notlike("%_audit_source%"),
                ),
            )
            .order_by(HazardReport.discovered_at.asc())  # oldest first
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def send_progress_dunning(self, chat_id: str) -> dict[str, int]:
        """向群发送「未更新进展」催办卡片（一卡一隐患，责任人可在卡片内提交进展）。

        每次发送都是当前已标记隐患的快照；已提交进展的隐患标记已被清除，
        下次触发自然不会再发（自愈，无需额外去重）。

        Args:
            chat_id: 飞书群聊 chat_id（如 "oc_xxx"），目标群由调用方指定。

        Returns:
            {"sent": int, "skipped": int, "errors": int}
        """

        from app.modules.safety.feishu.progress_card import build_progress_card

        hazards = await self.get_progress_dunning_hazards()
        if not hazards:
            logger.info("督办催办：当前无「未更新进展」隐患，不发卡")
            return {"sent": 0, "skipped": 0, "errors": 0}

        # 批量加载责任人 → open_id 映射（与 build_bulletin_content 同模式）
        persons = {
            effective_responsible_person(h.department, h.rectification_responsible_person_name)
            for h in hazards if effective_responsible_person(h.department, h.rectification_responsible_person_name)
        }
        person_open_id: dict[str, str] = {}
        if persons:
            from app.modules.safety.feishu import mention

            person_open_id = await mention.resolve_open_ids(persons)

        sent = skipped = errors = 0
        for h in hazards:
            eff_name = effective_responsible_person(h.department, h.rectification_responsible_person_name)
            open_id = person_open_id.get(eff_name or "", "")
            try:
                content, elements = build_progress_card(h, open_id)
                ok = await send_group_card(
                    chat_id=chat_id,
                    title="⏰ 督办催办 · 未更新进展",
                    content=content,
                    elements=elements,
                    header_template="red",
                )
                if ok:
                    sent += 1
                    logger.info(
                        "催办卡片已发送: hazard_id=%s hazard_no=%s",
                        h.id, h.hazard_no,
                    )
                else:
                    skipped += 1
                    logger.warning("催办卡片发送失败: hazard_id=%s", h.id)
            except Exception:
                errors += 1
                logger.exception("催办卡片发送异常: hazard_id=%s", h.id)

        logger.info(
            "督办催办完成: chat_id=%s sent=%d skipped=%d errors=%d",
            chat_id, sent, skipped, errors,
        )
        return {"sent": sent, "skipped": skipped, "errors": errors}

    async def send_progress_dunning_dm(self, open_id: str) -> dict[str, int]:
        """向个人 DM 发送「未更新进展」催办卡片（一卡一隐患，红色 + 提交按钮）。

        与群发 send_progress_dunning 同款卡片（build_progress_card），卡片内
        「提交进展」按钮对责任人 open_id 生效；发送对象（open_id）由调度器
        个人目标配置指定（默认许康福）。已提交进展的隐患标记清除，自愈不重发。
        """

        from app.modules.safety.feishu.progress_card import build_progress_card

        hazards = await self.get_progress_dunning_hazards()
        if not hazards:
            logger.info("督办催办 DM：当前无「未更新进展」隐患，不发卡")
            return {"sent": 0, "skipped": 0, "errors": 0}

        # 责任人 → open_id（卡片内提交按钮对责任人生效，与群发同模式）
        persons = {
            effective_responsible_person(h.department, h.rectification_responsible_person_name)
            for h in hazards if effective_responsible_person(h.department, h.rectification_responsible_person_name)
        }
        person_open_id: dict[str, str] = {}
        if persons:
            from app.modules.safety.feishu import mention

            person_open_id = await mention.resolve_open_ids(persons)

        sent = skipped = errors = 0
        for h in hazards:
            eff_name = effective_responsible_person(h.department, h.rectification_responsible_person_name)
            oid_for_at = person_open_id.get(eff_name or "", "")
            try:
                content, elements = build_progress_card(h, oid_for_at)
                ok = await send_user_card(
                    open_id=open_id,
                    title="⏰ 督办催办 · 未更新进展",
                    content=content,
                    elements=elements,
                    header_template="red",
                )
                if ok:
                    sent += 1
                    logger.info("催办卡片 DM 已发送: hazard_id=%s open_id=%s", h.id, open_id)
                else:
                    skipped += 1
                    logger.warning("催办卡片 DM 发送失败: hazard_id=%s", h.id)
            except Exception:
                errors += 1
                logger.exception("催办卡片 DM 发送异常: hazard_id=%s", h.id)

        logger.info(
            "督办催办 DM 完成: open_id=%s sent=%d skipped=%d errors=%d",
            open_id, sent, skipped, errors,
        )
        return {"sent": sent, "skipped": skipped, "errors": errors}

    # ── 08:30 通知（个人 DM）───────────────────────────────────

    async def get_hazards_for_notification(self) -> list[HazardReport]:
        """查询需要督办的隐患（红色预警 + 一般预警）。

        排除已关闭记录（关闭的统一置 closed，不应再出现在通报/通知中）。

        Returns:
            未关闭且 supervision_level IN ('红色预警', '一般预警') 的隐患列表
        """
        stmt = (
            select(HazardReport)
            .where(
                HazardReport.is_deleted == False,  # noqa: E712
                HazardReport.rectification_status != "closed",
                # 整改中不通报（仅通报未关闭），防状态更新与计算的时间差残留
                HazardReport.rectification_status != "in_progress",
                HazardReport.status != "closed",
                HazardReport.supervision_level.in_(["红色预警", "一般预警"]),
                # 排除异常占位记录（描述为空/待AI填写，属人工误创建/删除）
                HazardReport.description.isnot(None),
                HazardReport.description != "",
                HazardReport.description != "待AI填写",
                # 排除测试部门（AI创新部等，测试记录不通报/不通知）
                or_(
                    HazardReport.department.is_(None),
                    HazardReport.department.notin_(EXCLUDED_TEST_DEPARTMENTS),
                ),
                # 通报不统计外审隐患（外审记录含 _audit_source 标记）
                or_(
                    HazardReport.notes.is_(None),
                    HazardReport.notes.notlike("%_audit_source%"),
                ),
            )
            .order_by(
                HazardReport.supervision_level.desc(),  # 红色预警 > 一般预警 alphabetically
                HazardReport.discovered_at.asc(),        # oldest first
            )
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def send_notifications(self) -> dict[str, int]:
        """发送督办通知（08:30 触发）。

        读取已计算好的 supervision_level，对红色预警和一般预警记录发送通知。
        测试模式下全部发给许康福。

        Returns:
            dict with keys: urgent_sent, warning_sent, skipped, errors
        """
        if not NOTIFICATION_ENABLED:
            logger.info("督办通知已关闭 (SAFETY_SUPERVISION_NOTIFICATION_ENABLED=false)")
            return {"红色预警_sent": 0, "一般预警_sent": 0, "skipped": 0, "errors": 0, "disabled": 1}

        hazards = await self.get_hazards_for_notification()

        stats = {"红色预警_sent": 0, "一般预警_sent": 0, "skipped": 0, "errors": 0}

        for hazard in hazards:
            try:
                level = hazard.supervision_level
                # 只通知红色预警，一般预警不单独通知（在通报中汇总即可）
                if level != "红色预警":
                    stats["skipped"] += 1
                    continue

                if TEST_MODE:
                    await self._send_test_notification(hazard, level)
                else:
                    await self._send_production_notification(hazard, level)

                stats["红色预警_sent"] += 1

            except Exception:
                logger.exception("发送督办通知失败: hazard_id=%s", hazard.id)
                stats["errors"] += 1

        logger.info(
            "督办通知发送完成: 红色预警=%d skipped=%d errors=%d",
            stats["红色预警_sent"],
            stats["skipped"], stats["errors"],
        )
        return stats

    async def _send_test_notification(self, hazard: HazardReport, level: str) -> None:
        """测试模式：发送红色预警通知到许康福。"""
        days = (date.today() - hazard.discovered_at.date()).days if hazard.discovered_at else 0
        emoji = LEVEL_EMOJI.get(level, "")
        label = LEVEL_LABELS.get(level, level)
        # 展示优先用人工等级（与督办判定一致），缺失时回退 AI 等级
        level_cn = HAZARD_LEVEL_CN.get(
            hazard.hazard_level_manual or hazard.hazard_level or "",
            hazard.hazard_level_manual or hazard.hazard_level or "-",
        )
        discovered = hazard.discovered_at.strftime("%Y-%m-%d") if hazard.discovered_at else "-"

        # Bitable 记录链接
        import json as _json

        rid = hazard.feishu_record_id or ""
        link_line = ""

        # 优先从 notes._audit_source 取外审来源
        try:
            notes_obj = _json.loads(hazard.notes) if hazard.notes else {}
        except (_json.JSONDecodeError, TypeError):
            notes_obj = {}
        audit_src = notes_obj.get("_audit_source", {}) if isinstance(notes_obj, dict) else {}

        if audit_src.get("type") == "bitable":
            src_app = audit_src.get("app_token", "")
            src_table = audit_src.get("table_id", "")
            if src_app and src_table:
                bitable_url = (
                    f"https://j0eukrlohu.feishu.cn/base/{src_app}"
                    f"?table={src_table}&record={rid}"
                )
                link_line = f"\n📋 [查看隐患记录]({bitable_url})"
        else:
            # 主表记录（notes 中无 _audit_source）；凭证延迟读 store
            conn = store.get_connection("hazard", "hazard")
            app_token = conn.app_token if conn and conn.status != "disabled" else ""
            table_id = conn.table_id if conn and conn.status != "disabled" else ""
            if app_token and table_id and rid:
                bitable_url = (
                    f"https://j0eukrlohu.feishu.cn/base/{app_token}"
                    f"?table={table_id}&record={rid}"
                )
                link_line = f"\n📋 [查看隐患记录]({bitable_url})"

        content = (
            f"{emoji} **[{label}]** {hazard.description or '(无描述)'}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"部门：{hazard.department or '-'}\n"
            f"责任人：{effective_responsible_person(hazard.department, hazard.rectification_responsible_person_name) or '-'}\n"
            f"检查日期：{discovered}\n"
            f"检查类型：{hazard.inspection_category or '-'}\n"
            f"存在天数：**{days} 天**\n"
            f"隐患等级：{level_cn}"
            f"{link_line}"
        )

        await send_user_card(
            open_id=NOTIFY_OPEN_ID,
            title=f"督办通知 — {label}",
            content=content,
        )

    async def _send_production_notification(self, hazard: HazardReport, level: str) -> None:
        """生产模式：通过 IdentityResolver 路由到真实人员。

        当前占位，后续实现时按通知策略路由：
        - 红色预警 → 责任人 + 部门负责人 + 分管领导
        - 一般预警 → 责任人 + 部门安全员
        """
        # TODO: 生产模式下通过 IdentityResolver 解析真实通知目标
        logger.debug(
            "生产模式通知（未实现）: hazard_id=%s level=%s dept=%s person=%s",
            hazard.id, level, hazard.department,
            hazard.rectification_responsible_person_name,
        )


# ═══════════════════════════════════════════════════════════════
# 模块级辅助函数（供调度器使用）
# ═══════════════════════════════════════════════════════════════

async def run_daily_supervision_calculation() -> dict[str, int] | None:
    """07:30 全量计算 + 推回 Bitable + 群汇报。

    供调度器调用，内部管理独立的 session。
    说明：calculate_all_open() 内部已推回 Bitable（双端同步），此处不再重复调用。
    """
    try:
        async with async_session_factory() as session:
            service = HazardSupervisionService(session)
            stats, changed = await service.calculate_all_open()
            await service.send_calculation_summary(stats)
            return stats
    except Exception:
        logger.exception("07:30 督办计算任务失败")
        return None


async def run_daily_supervision_bulletin(chat_id: str | None = None) -> bool | None:
    """08:30 督办通报（群聊卡片）。

    读取已计算的督办等级，按部门分组列出红色预警/一般预警清单并推送。
    供调度器调用，内部管理独立的 session。chat_id 覆写优先，缺省回退默认群。
    """
    try:
        async with async_session_factory() as session:
            service = HazardSupervisionService(session)
            return await service.send_supervision_bulletin(chat_id=chat_id)
    except Exception:
        logger.exception("08:30 督办通报任务失败")
        return None
