"""飞书卡片推送：法规抓取结果通知。

V1.2：主路径并入当日「安全速递」总卡（安全AI创新交流群，regulation 格子，
分级+适用性详情走折叠面板）；总卡停用/投格失败且配置了独立目标时回退独立
分级卡片（V1.1 行为）。复用 safety/feishu 已有 send_group_card() /
send_user_card() / upsert_daily_digest()。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from app.modules.safety.app_config.store import store as _app_config_store
from app.modules.safety.bitable_config.store import store
from app.modules.safety.feishu.daily_digest import (
    DigestCell,
    digest_enabled,
    upsert_daily_digest,
)
from app.modules.safety.feishu.notification import send_group_card, send_user_card
from app.modules.safety.regulation_ingest.schemas import (
    CrawlItemResult,
    CrawlResultSummary,
)

logger = logging.getLogger(__name__)

_CARD_TITLE = "📋 安全生产法规更新通知"
_FEISHU_BASE_URL = os.getenv("FEISHU_BASE_URL", "https://livzon.feishu.cn")

# ── 影响等级排序 ──
_IMPACT_ORDER = {"高": 0, "中": 1, "低": 2}

# ── 适用性三级结论展示 ──
_APPLICABILITY_LABELS = {
    "applicable": "✅ 适用",
    "partially_applicable": "⚠️ 部分适用",
    "not_applicable": "❌ 不适用",
}


class PushNotifier:
    """法规更新推送通知器（V1.1 分级卡片）。"""

    def __init__(self) -> None:
        # 读取链：env > DB 活行（app_config）> 空（不推送）；构造时取一次
        self.chat_id = _app_config_store.get_str(
            "SAFETY_REGULATION_CRAWLER_NOTIFY_CHAT_ID", ""
        )
        self.user_ids: list[str] = [
            uid.strip()
            for uid in _app_config_store.get_str(
                "SAFETY_REGULATION_CRAWLER_NOTIFY_USERS", ""
            ).split(",")
            if uid.strip()
        ]

    async def send_crawl_result_notification(self, result: CrawlResultSummary) -> None:
        """发送爬取结果通知：主路径并入安全速递总卡，回退独立分级卡片。"""
        # 只推送 created/deleted 的项目
        actionable = [i for i in result.items if i.status in ("created", "deleted")]
        if not actionable:
            return

        delivered_to_group = False
        if digest_enabled():
            delivered_to_group = await self.send_crawl_result_digest(result, actionable)
            if not delivered_to_group:
                logger.warning("安全速递投格未生效，尝试独立卡片回退")

        # 独立群卡兜底：总卡停用/投格失败 且显式配置了群目标
        if not delivered_to_group and self.chat_id:
            try:
                await send_group_card(
                    chat_id=self.chat_id,
                    title=_CARD_TITLE,
                    content=self._build_content(result, actionable),
                    header_template=self._pick_header(actionable),
                )
                delivered_to_group = True
                logger.info("法规更新独立通知已发送到群聊: chat_id=%s", self.chat_id)
            except Exception:
                logger.exception("发送群聊通知失败")

        # 私发独立卡（与总卡互不影响；未配置则静默）
        for user_id in self.user_ids:
            try:
                await send_user_card(
                    open_id=user_id,
                    title=_CARD_TITLE,
                    content=self._build_content(result, actionable),
                )
                logger.info("法规更新通知已发送到用户: user_id=%s", user_id)
            except Exception:
                logger.exception("发送用户通知失败: user_id=%s", user_id)

        if not delivered_to_group and not self.user_ids:
            logger.info("法规更新未投递（总卡不可用且未配置通知目标）")

    async def send_crawl_result_digest(
        self, result: CrawlResultSummary, actionable: list[CrawlItemResult],
    ) -> bool:
        """并入当日「安全速递」总卡（regulation 格子，详情=完整分级内容）。

        失败只告警返回 False（由调用方决定是否独立卡回退），不抛异常。
        """
        created = [i for i in actionable if i.status == "created"]
        updated = [i for i in created if i.action == "updated"]
        deleted = [i for i in actionable if i.status == "deleted"]
        high = [i for i in created if i.impact_level == "高"]

        stats = (
            f"本次收录 **{len(created)}** 条 · 🔴高关注 **{len(high)}**"
            f" · 🔄更新 **{len(updated)}** · 🗑️废止 **{len(deleted)}**"
        )
        zone = f"最高关注：《{high[0].title}》" if high else ""
        cell = DigestCell(
            tag_color="red" if high else "blue",
            tag_text="法规更新",
            title="法规收录更新",
            stats=stats,
            zone=zone,
            detail=self._build_content(result, actionable),
        )
        report_date = datetime.now(timezone(timedelta(hours=8))).date()
        try:
            return await upsert_daily_digest(report_date, "regulation", cell)
        except Exception:
            logger.exception("法规更新并入安全速递失败")
            return False

    # ── 卡片内容构建 ──

    @classmethod
    def _record_url(cls, record_id: str) -> str:
        """构建 Bitable 记录链接（回退，仅当 API 返回的 shared_url 不可用时）。

        凭证延迟读 store（knowledge/collection 连接）：改表 ID 后链接立即指向新表。
        注意：此构造格式不可靠，优先使用飞书 API 返回的 /record/{hash} 格式。
        """
        conn = store.get_connection("knowledge", "collection")
        if conn is None or conn.status == "disabled":
            return ""
        return (
            f"https://j0eukrlohu.feishu.cn/base/{conn.app_token}"
            f"?table={conn.table_id}&record={record_id}"
        )

    @classmethod
    def _build_content(
        cls, result: CrawlResultSummary, actionable: list[CrawlItemResult],
    ) -> str:
        """构建分级卡片正文，区分 🔄已更新 / 🔖新增 / 🗑️废止。

        修订法规 → 展示 comparison_summary（修订内容）
        新增法规 → 展示 core_summary（法规概要）
        """
        now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")

        # ── 分类 ──
        updated_items = [i for i in actionable if i.action == "updated" and i.status == "created"]
        created_items = [i for i in actionable if i.action != "updated" and i.status == "created"]
        deleted_items = [i for i in actionable if i.status == "deleted"]

        updated_count = len(updated_items)
        created_count = len(created_items)
        deleted_count = len(deleted_items)

        # ── 头部 ──
        stat_parts = [f"本次抓取 **{result.crawled_count}** 条"]
        if updated_count:
            stat_parts.append(f"🔄更新 **{updated_count}**")
        if created_count:
            stat_parts.append(f"🔖新增 **{created_count}**")
        if deleted_count:
            stat_parts.append(f"🗑️废止 **{deleted_count}**")

        lines = [
            f"⏰ 报告时间：{now}",
            "",
            " | ".join(stat_parts),
        ]

        if result.filtered_count > 0:
            lines.append(f"过滤非法规内容 **{result.filtered_count}** 条")
        if result.attachment_failed_count > 0:
            lines.append(f"附件下载失败 **{result.attachment_failed_count}** 条")

        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━")

        # ── 🔄 已更新（修订替代） ──
        if updated_items:
            lines.append("")
            lines.append(f"🔄 **已更新（{updated_count} 项）**— 旧版已删除，新版替代")
            lines.append("")
            for idx, item in enumerate(updated_items, 1):
                link = cls._inline_link(item)
                lines.append(f"[{idx}] **《{item.title}》**  {link}")
                # 修订概要
                summary = (item.comparison_summary or item.core_summary or "").strip()
                if summary:
                    lines.append(f"    {cls._truncate_summary(summary)}")
                cls._render_applicability(lines, item)
                lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━")

        # ── 🔖 新增（按影响等级分组） ──
        if created_items:
            # 按影响等级分组
            high_items = [i for i in created_items if i.impact_level == "高"]
            mid_items = [i for i in created_items if i.impact_level == "中"]
            low_items = [i for i in created_items if i.impact_level == "低"]
            no_level = [i for i in created_items if not i.impact_level]

            def _render_created_group(
                items: list[CrawlItemResult], emoji: str, label: str,
                bold: bool = True,
            ) -> None:
                if not items:
                    return
                lines.append("")
                prefix = f"{emoji} **{label}（{len(items)} 项）**" if bold else f"{emoji} {label}（{len(items)} 项）"
                lines.append(prefix)
                lines.append("")
                for idx, item in enumerate(items, 1):
                    link = cls._inline_link(item)
                    title_line = f"[{idx}] **《{item.title}》**  {link}" if bold else f"[{idx}] 《{item.title}》  {link}"
                    lines.append(title_line)
                    summary = (item.core_summary or "").strip()
                    if summary:
                        lines.append(f"    {cls._truncate_summary(summary)}")
                    cls._render_applicability(lines, item)
                    lines.append("")

            _render_created_group(high_items, "🔴", "高关注")
            all_mid = mid_items + no_level  # 未评级的归入中等
            _render_created_group(all_mid, "🟠", "值得关注")
            _render_created_group(low_items, "🟡", "参考了解", bold=False)

            lines.append("━━━━━━━━━━━━━━━━━━━━")

        # ── 🗑️ 已废止 ──
        if deleted_items:
            lines.append("")
            lines.append(f"🗑️ **已废止清理（{len(deleted_items)} 项）**")
            lines.append("")
            for idx, item in enumerate(deleted_items, 1):
                lines.append(f"[{idx}] ~~{item.title}~~")
                lines.append("")
            lines.append("━━━━━━━━━━━━━━━━━━━━")

        return "\n".join(lines)

    @staticmethod
    def _truncate_summary(text: str, max_len: int = 120) -> str:
        """截断概要文本，避免飞书卡片过长。"""
        if not text:
            return ""
        t = text.strip()
        if len(t) <= max_len:
            return t
        return t[:max_len - 3] + "..."

    @classmethod
    def _render_applicability(cls, lines: list[str], item: CrawlItemResult) -> None:
        """适用性深度分析行：三级结论 + 首条理由 + 落地建议（≤2 条）。

        高关注项未获分析（限额/失败/开关关）标"分析待补"；中低关注项不渲染。
        """
        if item.impact_level != "高":
            return
        if not item.applicability:
            lines.append("    适用性：⏳ 分析待补")
            return
        label = _APPLICABILITY_LABELS.get(item.applicability, item.applicability)
        reasons = item.applicability_reasons or []
        line = f"    适用性：{label}"
        if reasons and reasons[0]:
            line += f" — {cls._truncate_summary(reasons[0], 80)}"
        lines.append(line)
        for sug in (item.applicability_suggestions or [])[:2]:
            if sug:
                lines.append(f"    💡 {cls._truncate_summary(sug, 80)}")

    async def send_empty_summary_notification(
        self, crawled_count: int = 0, reason: str = "",
    ) -> None:
        """发送空结果通知——脚本已执行但无新法规产出。

        用于以下场景：
        - 数据源未返回任何文档
        - AI 筛选后无匹配法规
        """
        if not self.chat_id and not self.user_ids:
            logger.info("未配置通知目标，跳过空结果推送")
            return

        now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
        lines = [
            f"⏰ 报告时间：{now}",
            "",
            "📋 **安全生产法规更新通知**",
            "",
        ]
        if crawled_count > 0:
            lines.append(f"本次抓取 **{crawled_count}** 条文档，经 AI 筛选后**无新增法规**")
        else:
            lines.append("本次抓取**未获取到新文档**")
        lines.append("")
        if reason:
            lines.append(f"_{reason}_")
            lines.append("")

        content = "\n".join(lines)

        # 发送到群聊
        if self.chat_id:
            try:
                await send_group_card(
                    chat_id=self.chat_id,
                    title=_CARD_TITLE,
                    content=content,
                    header_template="blue",
                )
                logger.info("空结果通知已发送到群聊")
            except Exception:
                logger.exception("发送空结果群聊通知失败")

        # 发送到个人
        for user_id in self.user_ids:
            try:
                await send_user_card(
                    open_id=user_id,
                    title=_CARD_TITLE,
                    content=content,
                )
            except Exception:
                logger.exception("发送空结果用户通知失败: user_id=%s", user_id)

    @classmethod
    def _inline_link(cls, item: CrawlItemResult) -> str:
        """生成 inline 查看原文链接（HTML a 标签，与知识库引用栏一致）。

        优先使用飞书返回的 shared_url（/record/ 格式分享链接），
        回退到手动构造的 Bitable URL。
        """
        if item.status != "created":
            return ""
        url = item.bitable_shared_url or (
            cls._record_url(item.bitable_record_id)
            if item.bitable_record_id else ""
        )
        if not url:
            return ""
        return f"<a href='{url}'>查看原文</a>"

    @staticmethod
    def _pick_header(actionable: list[CrawlItemResult]) -> str:
        """根据影响等级选择卡片 header 颜色。"""
        levels = {i.impact_level for i in actionable if i.impact_level}
        if "高" in levels:
            return "red"
        if "中" in levels:
            return "orange"
        return "blue"
