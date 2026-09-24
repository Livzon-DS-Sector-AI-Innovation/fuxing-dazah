"""特殊作业日报「直读」编排入口：直读 -> 判定 -> 分组 -> 渲染 -> 推送。

与旧镜像链路（``SpecialOperationDailyReportService.generate_and_push``）的关系：

- 渲染复用 ``ReportBuilder.build``、AI 增强复用 ``AIAnalyst``，标题 / 目标群 /
  段落结构 / 标签与改造前完全一致
- 数据源换成 ``bitable_repo.fetch_day_views``（Bitable 直读 + 内存判定）
- **不写平台库**：不再给记录打 ``daily_report_date`` 标记、不再 commit
  （该去重标记的职责移交调度器运行记录）
- 回写「日报风险等级（AI）」列由 Ticket 05 在本入口追加

可测接缝（spec 接缝 2）：``reader`` / ``pusher`` / ``analyst`` 三个参数都可注入替身，
内部跑真实的字段映射、风险判定与 Markdown 渲染。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any, Protocol

from app.modules.safety.feishu.notification import send_group_card
from app.modules.safety.feishu.special_op_digest import build_special_op_digest
from app.modules.safety.schemas.special_op_daily import (
    AIDailyAnalysisResult,
    DailyReportResponse,
)
from app.modules.safety.service.special_op_contract import SpecialOpRecord
from app.modules.safety.service.special_op_direct import config
from app.modules.safety.service.special_op_direct.bitable_repo import (
    BitableRecordsReader,
    RecordWriter,
    WritebackResult,
    fetch_day_views,
    writeback_risk_levels,
)
from app.modules.safety.service.special_operation_daily_report import (
    DAILY_REPORT_CHAT_ID,
    ReportBuilder,
)

logger = logging.getLogger(__name__)


class AnalystLike(Protocol):
    """AI 增强分析接缝（真实实现 ``AIAnalyst``，单测注入替身避免真实大模型调用）。"""

    async def analyze(
        self,
        report_date: date,
        mode: str,
        reports: Sequence[SpecialOpRecord],
        stats: dict[str, int],
    ) -> AIDailyAnalysisResult | None: ...


class GroupPusher(Protocol):
    """群推送接缝（真实实现为 ``send_group_card``，单测注入替身记录推送内容）。"""

    async def send(
        self,
        *,
        chat_id: str,
        title: str,
        content: str,
        elements: list[dict[str, Any]] | None = None,
        header_template: str = "orange",
        subtitle: str | None = None,
        header_tags: list[dict[str, Any]] | None = None,
    ) -> str | None: ...


class _FeishuGroupPusher:
    """默认推送器：与改造前调用同一个 ``send_group_card``、同一组参数。"""

    async def send(
        self,
        *,
        chat_id: str,
        title: str,
        content: str,
        elements: list[dict[str, Any]] | None = None,
        header_template: str = "orange",
        subtitle: str | None = None,
        header_tags: list[dict[str, Any]] | None = None,
    ) -> str | None:
        return await send_group_card(
            chat_id=chat_id, title=title, content=content, elements=elements,
            header_template=header_template, subtitle=subtitle,
            header_tags=header_tags,
        )


def _default_analyst() -> AnalystLike:
    """真实 AI 分析器。

    ``AIAnalyst`` 的 ``session`` 参数在当前实现里未被使用（RAG 走自己的 session），
    直读路径不建 DB 连接即可复用其分析逻辑。
    """
    from app.modules.safety.service.special_operation_daily_report import AIAnalyst

    return AIAnalyst(session=None)  # type: ignore[no-untyped-call]


async def run(
    target_date: date,
    mode: str = "today",
    *,
    target_chats: list[str] | None = None,
    push: bool = True,
    reader: BitableRecordsReader | None = None,
    pusher: GroupPusher | None = None,
    analyst: AnalystLike | None = None,
    writer: RecordWriter | None = None,
    writeback: bool | None = None,
) -> DailyReportResponse:
    """日报直读编排入口。

    Args:
        target_date: 目标日期（北京时间日）
        mode: today（08:00 日报）/ afternoon（17:00 日报）/ tomorrow（次日预警）
        target_chats: 目标群列表；None 表示沿用默认群（手动 API 兼容），
            ``[]`` 表示显式无目标
        push: False 时只渲染不推送（dry-run 冒烟用）
        reader: 直读拉取替身（默认走配置中心的真实 Bitable 连接）
        pusher: 群推送替身（默认 ``send_group_card``）
        analyst: AI 增强替身（默认 ``AIAnalyst``）
        writer: 回写替身（默认配置中心的真实 Bitable 客户端）
        writeback: 是否回写「日报风险等级（AI）」列；None 表示跟随开关
            ``SAFETY_SPECIAL_OP_WRITEBACK_RISK_ENABLED``（默认关闭）

    Raises:
        BitableQueryError: 拉取失败（向上抛错，绝不推送空日报）
        SpecialOpDirectError: Bitable 连接未配置或已停用
        RuntimeError: 推送失败（由调度器标记 failed 并进入补发窗口）
    """
    # 取数：一次批量直读 + 内存判定；失败直接向上抛，不返回空列表
    views = await fetch_day_views(target_date, client=reader)
    # 顺序显式化：按记录创建时间升序稳定排序（同刻保持 Bitable 返回的相对序）。
    # Bitable 返回序本就是创建时间升序；显式声明是为了让「同一份数据 -> 同一份日报」
    # 不依赖表格内部排序。旧镜像链路是堆序（无 ORDER BY），顺序本身不稳定。
    views = sorted(views, key=lambda v: v.created_at)

    effective = [v for v in views if not v.is_excluded]
    excluded_count = len(views) - len(effective)
    high = [v for v in effective if v.daily_risk_level == "high"]
    medium = [v for v in effective if v.daily_risk_level == "medium"]
    low = [v for v in effective if v.daily_risk_level == "low"]
    stats = {
        "total": len(views),
        "effective_total": len(effective),
        "high": len(high),
        "medium": len(medium),
        "low": len(low),
        "excluded": excluded_count,
    }
    # 计划内/外拆分（晨报概况行 / 速递卡副标题 / AI 汇总 prompt 共用）
    stats["planned"] = sum(1 for v in effective if v.report_type == "planned")
    stats["unplanned"] = sum(1 for v in effective if v.report_type == "unplanned")
    # 晚报进度/夜间统计（「已完成」按计划结束时间推算，口径见 ReportBuilder.is_completed）
    now = datetime.now(UTC)
    night_views: list[Any] = []
    if mode == "afternoon":
        completed_n = sum(1 for v in effective if ReportBuilder.is_completed(v, now))
        ongoing_n = sum(
            1 for v in effective
            if not ReportBuilder.is_completed(v, now)
            and ReportBuilder.is_ongoing(v, now)
        )
        stats["completed"] = completed_n
        stats["ongoing"] = ongoing_n
        stats["pending"] = len(effective) - completed_n - ongoing_n
        night_views = ReportBuilder.select_night_ops(target_date, effective)
        stats["night"] = len(night_views)

    # AI 增强分析（与改造前同口径）：只有存在高风险时才调用，失败回退纯规则报告。
    # 晚报只分析未完成记录（已收工的高风险移入「已完成」段点名，不再逐条 AI 分析），
    # 渲染端 _build_afternoon 的 🔴 索引与该子集按同一排序对齐。
    ai_reports: Sequence[Any] = effective
    if mode == "afternoon":
        ai_reports = [v for v in effective if not ReportBuilder.is_completed(v, now)]
    ai_analysis = None
    if any(v.daily_risk_level == "high" for v in ai_reports):
        try:
            ai_analysis = await (analyst or _default_analyst()).analyze(
                report_date=target_date,
                mode=mode,
                reports=ai_reports,
                stats=stats,
            )
        except Exception:
            logger.warning("AI 分析失败，回退纯规则报告", exc_info=True)

    markdown = ReportBuilder.build(
        target_date, mode, effective, stats, ai_analysis=ai_analysis, now=now
    )

    mode_label = (
        "特殊作业日报·晚报"
        if mode == "afternoon"
        else (
            "特殊作业日报"
            if ReportBuilder._is_today_family(mode)
            else "特殊作业次日预警"
        )
    )

    # 速递卡（默认开启，today/afternoon 生效）：长文日报改速递式布局，
    # 完整明细收进折叠面板；构建失败/超限回退旧长卡，绝不漏发
    push_title = f"{mode_label} - {target_date.strftime('%Y-%m-%d')}"
    push_content = markdown
    push_elements: list[dict[str, Any]] | None = None
    push_header_template = "orange"
    push_subtitle: str | None = None
    push_header_tags: list[dict[str, Any]] | None = None
    if ReportBuilder._is_today_family(mode) and config.digest_card_enabled():
        built = await build_special_op_digest(
            target_date, mode, effective, stats, ai_analysis, markdown, now=now
        )
        if built is not None:
            push_title = built.title
            push_content = built.content
            push_elements = built.elements
            push_header_template = built.header_template
            push_subtitle = built.subtitle
            push_header_tags = built.header_tags

    # 回写「日报风险等级（AI）」（Ticket 05）：只写这一列，串行 + 0.5s 间隔。
    # 单条失败只告警、不抛异常 -> 不阻塞下面的群推送，下一轮日报自然补写。
    if writeback is None:
        writeback = config.writeback_risk_enabled()
    writeback_result: WritebackResult | None = None
    if writeback:
        writeback_result = await writeback_risk_levels(views, writer=writer)
        if writeback_result.failed:
            logger.warning(
                "风险等级回写有失败: written=%d failed=%d ids=%s",
                writeback_result.written,
                len(writeback_result.failed),
                writeback_result.failed[:10],
            )

    target_list = target_chats if target_chats is not None else [DAILY_REPORT_CHAT_ID]
    push_results: list[dict[str, Any]] = []
    if push:
        sender = pusher or _FeishuGroupPusher()
        for chat_id in target_list:
            try:
                msg_id = await sender.send(
                    chat_id=chat_id,
                    title=push_title,
                    content=push_content,
                    elements=push_elements,
                    header_template=push_header_template,
                    subtitle=push_subtitle,
                    header_tags=push_header_tags,
                )
                push_results.append({
                    "chat_id": chat_id,
                    "success": msg_id is not None,
                    "message_id": msg_id,
                })
            except Exception as exc:
                logger.exception("推送失败: chat_id=%s", chat_id)
                push_results.append({"chat_id": chat_id, "success": False, "error": str(exc)})
        # 任一目标推送失败（异常或未返回 message_id）视为任务失败：抛出让调度器
        # 标记 failed 并进入补发窗口，避免静默丢失
        if not push_results or not all(r.get("success") for r in push_results):
            failed = next(
                (r.get("error") for r in push_results if not r.get("success")),
                "未返回 message_id",
            )
            raise RuntimeError(f"日报推送失败: {failed}") from None

        # 「安全速递」总卡：投递本报告格子（概览+明细，滚动追加；失败不影响日报）
        if ReportBuilder._is_today_family(mode):
            try:
                from app.modules.safety.feishu.daily_digest import (
                    DigestCell,
                    upsert_daily_digest,
                )

                zone = (
                    ReportBuilder._night_focus_summary(night_views or [])
                    if mode == "afternoon"
                    else ReportBuilder._build_zone_summary(high, medium, mode_label)
                ) or ""
                zone = zone[:80]
                if mode == "afternoon":
                    cell_stats = (
                        f"今日 **{len(effective)}** 项 ｜"
                        f" 完成 {stats['completed']} · 进行 {stats['ongoing']}"
                        f" ｜ 🔴 高 **{len(high)}** · 🌙 夜间 {stats['night']}"
                    )
                    cell_title = "特殊作业日报·晚报"
                else:
                    cell_stats = (
                        f"今日计划 **{len(effective)}** 项 ｜ "
                        f"🔴 高风险 **{len(high)}** · 🟡 中 {len(medium)}"
                        f" · 🟢 低 {len(low)}"
                    )
                    cell_title = "特殊作业日报"
                await upsert_daily_digest(
                    target_date,
                    "special_op",
                    DigestCell(
                        tag_color="blue",
                        tag_text="特殊作业",
                        title=cell_title,
                        stats=cell_stats,
                        zone=zone,
                        detail=markdown,
                    ),
                )
            except Exception:
                logger.warning("安全速递总卡投递失败（特殊作业）", exc_info=True)

    return DailyReportResponse(
        report_date=target_date,
        mode=mode,
        total=len(views),
        excluded=excluded_count,
        high_risk=len(high),
        medium_risk=len(medium),
        low_risk=len(low),
        markdown_report=markdown,
        push_results=push_results,
        logs_analyzed=[v.id for v in effective],
    )
