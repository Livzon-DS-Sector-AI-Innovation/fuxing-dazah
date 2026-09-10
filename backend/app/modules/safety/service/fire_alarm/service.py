"""消防报警 FireAlarmService — Bitable 全量同步（ticket 02）+ 记录查询/统计（ticket 03）
+ AI 分析日报（ticket 05）/ 周报（ticket 06）生成与推送。

生成流程（backend-design.md §2.2.7）：
- 日报：聚合 → 逐条 AI 回写（flush + re-fetch + commit）→ 汇总 AI → 渲染 → 推送
- 周报：自然周聚合（复用记录上已有的日分析结果，不重复逐条 AI 调用）
  → 周级汇总 AI → 渲染 → 推送
AI 任何环节失败降级，不阻塞报告生成；推送 env 未配置则跳过。
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.bitable_config.store import ConnectionView, store
from app.modules.safety.feishu.notification import send_group_card
from app.modules.safety.models import FireAlarmRecord
from app.modules.safety.schemas.fire_alarm import FireAlarmReportResponse
from app.modules.safety.service.fire_alarm.aggregator import (
    aggregate_daily,
    aggregate_weekly,
    get_natural_week_range,
)
from app.modules.safety.service.fire_alarm.analyst import FireAlarmAnalyst
from app.modules.safety.service.fire_alarm.bitable_mapper import map_bitable_fields
from app.modules.safety.service.fire_alarm.renderer import (
    render_daily_report,
    render_weekly_report,
)

logger = logging.getLogger(__name__)


async def _resolve_mention_ids(names: Any) -> dict[str, str]:
    """姓名 → 安全应用作用域 open_id（@ 提及用）。

    单独抽出模块级函数，便于测试替身（``patch(...service._resolve_mention_ids)``）；
    真正的解析逻辑在 ``feishu.mention``（邮箱 batch_get_id / user_id 反查 + 缓存）。
    """
    from app.modules.safety.feishu import mention

    return await mention.resolve_open_ids(names)

# ── 连接配置（配置中心 store；未启用/缺失时降级为空串，调用方走现有降级分支）──
def _fire_alarm_conn() -> ConnectionView | None:
    """消防报警连接配置（配置中心 store 读取）。"""
    return store.get_connection("fire_alarm", "alarm")


def _fire_alarm_app_token() -> str:
    conn = _fire_alarm_conn()
    return conn.app_token if conn and conn.enabled else ""


def _fire_alarm_table_id() -> str:
    conn = _fire_alarm_conn()
    return conn.table_id if conn and conn.enabled else ""


# 日报/周报推送目标群（未配置 → 跳过推送，联调期安全）
FIRE_ALARM_CHAT_ID = os.getenv("SAFETY_FIRE_ALARM_ANALYSIS_CHAT_ID", "")

# 全量同步分页配置（参照 special_op：page_size=200、上限 10 页防死循环）
MAX_PAGES = 10
PAGE_SIZE = 200

# UPDATE 时不覆盖的同步标识字段（feishu_record_id/source 由同步逻辑统一维护）
_NON_BITABLE_KEYS = ("feishu_record_id", "source")

_BITABLE_RECORDS_URL = (
    "https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}"
    "/tables/{table_id}/records"
)


class FireAlarmService:
    """消防报警分析业务服务（同步 + 查询/统计 + 日报/周报生成与推送编排）。"""

    def __init__(self, session: AsyncSession, ai_service: Any = None) -> None:
        self.session = session
        self.analyst = FireAlarmAnalyst(session, ai_service=ai_service)

    async def sync_from_bitable(self) -> tuple[int, int]:
        """从飞书 Bitable 全量同步到 FireAlarmRecord。

        Returns:
            (synced_count, soft_deleted_count)

        算法（backend-design.md §4.1）:
          1. GET /records 分页拉取（不用 search_records，其分页有 bug）
          2. 按 feishu_record_id upsert：活行 UPDATE 只覆盖 Bitable 字段
             （保留 ai_* 分析字段），无活行 INSERT
          3. 软删对齐：本地有但远端无的 bitable 来源活行
             → is_deleted=true + feishu_record_id=NULL（软删除铁律）
        """
        import httpx

        from app.modules.safety.feishu.client import get_safety_tenant_token

        records: list[dict[str, Any]] = []
        page_token: str | None = None

        async with httpx.AsyncClient(timeout=30) as http:
            token = await get_safety_tenant_token()
            headers = {"Authorization": f"Bearer {token}"}
            for _ in range(MAX_PAGES):
                params: dict[str, Any] = {"page_size": PAGE_SIZE}
                if page_token:
                    params["page_token"] = page_token
                resp = await http.get(
                    _BITABLE_RECORDS_URL.format(
                        app_token=_fire_alarm_app_token(),
                        table_id=_fire_alarm_table_id(),
                    ),
                    headers=headers,
                    params=params,
                )
                d = resp.json()
                if not isinstance(d, dict) or d.get("code", 0) != 0:
                    raise RuntimeError(
                        f"Bitable records 拉取失败: code={d.get('code') if isinstance(d, dict) else '?'}"
                        f", msg={d.get('msg') if isinstance(d, dict) else '?'}"
                    )
                data = d.get("data", {}) or {}
                records.extend(data.get("items", []) or [])
                if not data.get("has_more") or not data.get("page_token"):
                    break
                page_token = data.get("page_token")

        remote_ids: set[str] = set()
        synced = 0
        now = datetime.now(UTC)
        for rec in records:
            record_id = str(rec.get("record_id") or "").strip()
            if not record_id:
                continue
            remote_ids.add(record_id)
            mapped = map_bitable_fields(rec.get("fields") or {})
            mapped["feishu_record_id"] = record_id
            mapped["source"] = "bitable"
            mapped["synced_at"] = now

            existing = await self.session.scalar(
                select(FireAlarmRecord).where(
                    FireAlarmRecord.feishu_record_id == record_id,
                    FireAlarmRecord.is_deleted == False,  # noqa: E712
                )
            )
            if existing is not None:
                # UPDATE — 只覆盖 Bitable 字段，保留平台 AI 分析字段
                for k, v in mapped.items():
                    if v is not None and k not in _NON_BITABLE_KEYS:
                        setattr(existing, k, v)
            else:
                self.session.add(FireAlarmRecord(**mapped))
            synced += 1

        # 软删对齐：远端已删除 → 本地软删 + 清空 feishu_record_id（不占用唯一键）
        stmt = (
            update(FireAlarmRecord)
            .where(
                FireAlarmRecord.source == "bitable",
                FireAlarmRecord.is_deleted == False,  # noqa: E712
                FireAlarmRecord.feishu_record_id.is_not(None),
                FireAlarmRecord.feishu_record_id.not_in(remote_ids),
            )
            .values(is_deleted=True, feishu_record_id=None, synced_at=now)
        )
        result = await self.session.execute(stmt)
        soft_deleted = result.rowcount or 0

        return synced, soft_deleted

    # ── 查询 ──

    async def get_records(
        self, *,
        date_from: date | None = None,
        date_to: date | None = None,
        department: str | None = None,
        alarm_type: str | None = None,
        alarm_nature: str | None = None,
        ai_dimension: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[FireAlarmRecord], int]:
        """分页查询报警记录（多条件筛选，默认过滤软删）。

        Returns:
            (records, total)：按 alarm_time 倒序（最新在前）。
        """
        conds = [FireAlarmRecord.is_deleted == False]  # noqa: E712
        if date_from is not None:
            conds.append(
                FireAlarmRecord.alarm_time
                >= datetime.combine(date_from, time.min, tzinfo=UTC)
            )
        if date_to is not None:
            conds.append(
                FireAlarmRecord.alarm_time
                < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC)
            )
        if department:
            conds.append(FireAlarmRecord.department == department)
        if alarm_type:
            conds.append(FireAlarmRecord.alarm_type == alarm_type)
        if alarm_nature:
            conds.append(FireAlarmRecord.alarm_nature == alarm_nature)
        if ai_dimension:
            conds.append(FireAlarmRecord.ai_dimension == ai_dimension)
        if keyword:
            kw = f"%{keyword}%"
            conds.append(
                or_(
                    FireAlarmRecord.location.ilike(kw),
                    FireAlarmRecord.cause_description.ilike(kw),
                )
            )

        total = (
            await self.session.scalar(
                select(func.count(FireAlarmRecord.id)).where(*conds)
            )
        ) or 0
        offset = (page - 1) * page_size
        rows = (
            await self.session.scalars(
                select(FireAlarmRecord)
                .where(*conds)
                .order_by(FireAlarmRecord.alarm_time.desc())
                .offset(offset)
                .limit(page_size)
            )
        ).all()
        return list(rows), total

    async def get_stats(self, target_date: date | None = None) -> dict:
        """KPI：今日/本周报警数 + 性质/类型/维度/部门分布。

        统计口径（北京时间 UTC+8）：
          - date：target_date 或今天；今日窗口 = 该日 00:00~24:00 北京时间
          - 本周 = 该日所在自然周（周一~周日）
          - 分布基于本周窗口内记录（非软删）；total_count 为全量非软删数
          - week_ai_analyzed_count = 本周窗口内 ai_analyzed_at 非空的记录数
        """
        target_date = target_date or _bj_today()
        today_records = await self._get_records_by_date(target_date)
        week_start, week_end = get_natural_week_range(target_date)
        week_records = await self._get_records_by_week(week_start, week_end)
        total_count = (
            await self.session.scalar(
                select(func.count(FireAlarmRecord.id)).where(
                    FireAlarmRecord.is_deleted == False  # noqa: E712
                )
            )
        ) or 0
        return {
            "date": target_date.isoformat(),
            "today_total": len(today_records),
            "week_total": len(week_records),
            "total_count": total_count,
            "week_ai_analyzed_count": sum(
                1 for r in week_records if r.ai_analyzed_at is not None
            ),
            "nature_distribution": _count_by(week_records, "alarm_nature"),
            "type_distribution": _count_by(week_records, "alarm_type"),
            "dimension_distribution": _count_by(week_records, "ai_dimension"),
            "department_distribution": _count_by(week_records, "department"),
        }

    async def _get_records_by_date(self, target_date: date) -> list[FireAlarmRecord]:
        """按北京时间自然日窗口查询当日报警记录（非软删）。"""
        utc_start = (
            datetime.combine(target_date, time.min, tzinfo=UTC)
            - timedelta(hours=8)  # 北京时间 00:00 = UTC 前一日 16:00
        )
        return list(
            (
                await self.session.scalars(
                    select(FireAlarmRecord).where(
                        FireAlarmRecord.is_deleted == False,  # noqa: E712
                        FireAlarmRecord.alarm_time >= utc_start,
                        FireAlarmRecord.alarm_time < utc_start + timedelta(days=1),
                    )
                )
            ).all()
        )

    async def _get_records_by_rolling_window(
        self, target_date: date,
    ) -> tuple[list[FireAlarmRecord], datetime, datetime]:
        """按滚动 24h 窗口查询报警记录：前日 17:00 ~ 当日 17:00（北京时间）。

        17:00 日报反映的是「上个日报周期（昨日17点至今日17点）」内发生的报警，
        与自然日窗口（00:00~24:00）不同。API 手动触发的日报（无 rolling 标志）
        仍用自然日窗口，调度入口（17:00 触发）用滚动窗口。

        Returns:
            (records, utc_start, utc_end)：utc_start/end 供 renderer 显示区间。
        """
        # 北京时间 target_date 17:00 = UTC target_date 09:00
        utc_end = datetime.combine(target_date, time(9, 0), tzinfo=UTC)
        utc_start = utc_end - timedelta(days=1)  # 前日北京17:00
        return list(
            (
                await self.session.scalars(
                    select(FireAlarmRecord).where(
                        FireAlarmRecord.is_deleted == False,  # noqa: E712
                        FireAlarmRecord.alarm_time >= utc_start,
                        FireAlarmRecord.alarm_time < utc_end,
                    )
                )
            ).all()
        ), utc_start, utc_end

    async def _get_records_by_week(
        self, week_start: date, week_end: date,
    ) -> list[FireAlarmRecord]:
        """按北京时间自然周窗口查询周报警记录（周一 00:00 ~ 周日 24:00 北京时间）。"""
        utc_start = (
            datetime.combine(week_start, time.min, tzinfo=UTC)
            - timedelta(hours=8)  # 北京时间周一 00:00 = UTC 周日 16:00
        )
        utc_end = (
            datetime.combine(week_end + timedelta(days=1), time.min, tzinfo=UTC)
            - timedelta(hours=8)
        )
        return list(
            (
                await self.session.scalars(
                    select(FireAlarmRecord).where(
                        FireAlarmRecord.is_deleted == False,  # noqa: E712
                        FireAlarmRecord.alarm_time >= utc_start,
                        FireAlarmRecord.alarm_time < utc_end,
                    )
                )
            ).all()
        )

    # ── 日报生成与推送 ──

    async def generate_daily_report(
        self, target_date: date | None = None, *,
        push: bool = True, channel: str = "web",
        rolling: bool = False,
        chat_id: str | None = None,
    ) -> FireAlarmReportResponse:
        """生成当日消防报警分析报告（聚合 → 逐条 AI 回写 → 汇总 AI → 渲染 → 推送）。

        Args:
            target_date: 目标日期，默认今天（北京时间 UTC+8）
            push: 是否推送（False 用于 Agent 直接返回报告）
            channel: 审计渠道（web/feishu/system）
            rolling: 是否用滚动 24h 窗口（前日17:00~当日17:00）。
                调度入口17点触发用 True；API 手动触发默认 False（自然日窗口）。

        Returns:
            FireAlarmReportResponse（markdown_report 恒非空；AI 全失败时退化为
            纯数据汇总版本；推送未配置/失败时 push_results 标记 skipped/error）
        """
        target_date = target_date or _bj_today()
        window_start_utc: datetime | None = None
        window_end_utc: datetime | None = None
        if rolling:
            records, window_start_utc, window_end_utc = (
                await self._get_records_by_rolling_window(target_date)
            )
        else:
            records = await self._get_records_by_date(target_date)
        agg = aggregate_daily(records, target_date)

        # 逐条 AI 分析并回写（失败跳过，不阻塞汇总/渲染）
        per_results: dict[str, dict[str, str]] = {}
        if records:
            try:
                per_results = await self.analyst.analyze_per_records(
                    records, channel=channel,
                )
            except Exception:
                logger.warning("逐条 AI 分析失败，跳过")

            # UPDATE 后 re-fetch（CLAUDE.md SQLAlchemy async 铁律）
            await self.session.flush()
            record_ids = [r.id for r in records]
            re_fetched = (
                await self.session.scalars(
                    select(FireAlarmRecord).where(FireAlarmRecord.id.in_(record_ids))
                )
            ).all()
            agg.records = list(re_fetched)
            # 逐条 AI 回写后重算维度分布（聚合发生在回写前，统计需用最新值）
            agg.dimension_distribution = _count_by(re_fetched, "ai_dimension")
            await self.session.commit()

        # 汇总 AI（失败返回 None，renderer 省略 AI 块）
        per_summaries = [
            f"报警{_bj(r.alarm_time)} {r.department or '?'} - {r.ai_reason_analysis[:60]}"
            for r in agg.records if r.ai_reason_analysis
        ]
        ai_summary = await self.analyst.analyze_daily_summary(
            agg, per_summaries, channel=channel,
        )

        # @提及解析（报警部门负责人 → open_id；解析失败退化为纯文本）
        person_open_id = await self._resolve_dept_leader_open_ids(agg.dept_leader_names)

        markdown = render_daily_report(
            agg, person_open_id, ai_summary,
            window_start_utc=window_start_utc,
            window_end_utc=window_end_utc,
        )

        # 推送（push=False / 无生效 chat_id → skipped；chat_id 为空时回退 env）
        push_results = await self._maybe_push(
            title=f"消防报警日报 - {target_date.strftime('%Y-%m-%d')}",
            content=markdown, push=push, chat_id=chat_id,
        )

        return FireAlarmReportResponse(
            report_kind="daily",
            target_date=target_date,
            total=agg.total,
            analyzed=len(per_results),
            markdown_report=markdown,
            push_results=push_results,
            records_analyzed=[r.id for r in agg.records if r.ai_analyzed_at],
        )

    # ── 周报生成与推送 ──

    async def generate_weekly_report(
        self, week_end: date | None = None, *,
        push: bool = True, channel: str = "web",
    ) -> FireAlarmReportResponse:
        """生成自然周（周一~周日）消防报警分析报告。

        流程（backend-design.md §2.2.7）:
          自然周聚合 → 周级汇总 AI（复用记录上已有的日分析结果 ai_dimension/
          ai_reason_analysis，不重复逐条 AI 调用）→ @提及解析 → 渲染 → 推送。

        Args:
            week_end: 周末日期（周日），默认今天（北京时间）所在自然周的周日
            push: 是否推送（False 用于 Agent 直接返回报告）
            channel: 审计渠道（web/feishu/system）

        Returns:
            FireAlarmReportResponse（report_kind="weekly"；AI 失败退化为纯数据汇总；
            推送未配置/失败时 push_results 标记 skipped/error）
        """
        ref = week_end or _bj_today()
        week_start, week_end_resolved = get_natural_week_range(ref)
        records = await self._get_records_by_week(week_start, week_end_resolved)
        agg = aggregate_weekly(records, week_start, week_end_resolved)

        # 周级汇总 AI（失败返回 None，renderer 省略 AI 块；不逐条调用）
        ai_summary = await self.analyst.analyze_weekly_summary(
            agg, channel=channel,
        )

        # @提及解析（报警部门负责人 → open_id；解析失败退化为纯文本）
        person_open_id = await self._resolve_dept_leader_open_ids(agg.dept_leader_names)

        markdown = render_weekly_report(agg, person_open_id, ai_summary)

        # 推送（push=False 或 env 未配置 → skipped）
        push_results = await self._maybe_push(
            title=(
                f"消防报警周报 - {week_start.strftime('%m/%d')}"
                f"~{week_end_resolved.strftime('%m/%d')}"
            ),
            content=markdown, push=push,
        )

        return FireAlarmReportResponse(
            report_kind="weekly",
            target_date=week_end_resolved,
            week_start=week_start,
            total=agg.total,
            markdown_report=markdown,
            push_results=push_results,
        )

    # ── 推送辅助 ──

    async def _maybe_push(
        self, *, title: str, content: str, push: bool,
        chat_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """推送群卡片；无生效 chat_id 或 push=False → 跳过并标记 skipped。

        发送目标唯一来源：调度器配置（DB 播种/覆写），不再回退 env。

        Returns:
            [{"chat_id", "success", "message_id"/"skipped"/"error"}]
            （参照 backend-design.md §6.4 push_results 结构）
        """
        effective_chat_id = chat_id
        if not push or not effective_chat_id:
            logger.info(
                "消防报警分析推送跳过（push=%s chat_id 配置=%s）",
                push, bool(effective_chat_id),
            )
            return [{
                "chat_id": effective_chat_id or "",
                "success": False,
                "skipped": True,
                "reason": "env not configured or push=False",
            }]
        try:
            msg_id = await send_group_card(
                chat_id=effective_chat_id,
                title=title,
                content=content,
            )
            return [{"chat_id": effective_chat_id,
                     "success": msg_id is not None, "message_id": msg_id}]
        except Exception as exc:
            logger.exception("推送失败: chat_id=%s", effective_chat_id)
            return [{"chat_id": effective_chat_id, "success": False, "error": str(exc)}]

    async def _resolve_dept_leader_open_ids(
        self, dept_leader_names: dict[str, str],
    ) -> dict[str, str]:
        """批量解析报警部门负责人 → @ 提及用 open_id。

        ⚠️ 必须用「安全应用作用域」的 open_id：平台同步的
        ``identity.users.feishu_open_id`` 跨应用无效（99992361 open_id cross app），
        因此统一走 ``feishu.mention``（邮箱 batch_get_id / user_id 反查）。
        解析失败返回空 dict，renderer 的 _at 退化为纯文本。
        """
        if not dept_leader_names:
            return {}
        try:
            return await _resolve_mention_ids(dept_leader_names.values())
        except Exception:
            logger.warning("部门负责人 open_id 解析失败（@ 退化为纯文本）", exc_info=True)
            return {}


def _bj_today() -> date:
    """北京时间今天（UTC+8）。"""
    return (datetime.now(UTC) + timedelta(hours=8)).date()


def _bj(dt: datetime | None) -> str:
    """UTC → 北京时间字符串（M/D HH:MM）。"""
    if dt is None:
        return "?"
    return (dt + timedelta(hours=8)).strftime("%m/%d %H:%M")


def _count_by(records: list[FireAlarmRecord], attr: str) -> dict[str, int]:
    """按记录字段统计分布（值为 None 的字段不计入）。"""
    out: dict[str, int] = {}
    for r in records:
        v = getattr(r, attr)
        if v is None:
            continue
        out[v] = out.get(v, 0) + 1
    return out


async def run_daily_fire_alarm_analysis(
    target_date: date | None = None,
    chat_id: str | None = None,
) -> FireAlarmReportResponse | None:
    """定时任务入口：全量同步兜底 + 生成并推送日报到默认群聊。

    - 独立 async_session_factory session，channel="system"，push=True
    - chat_id 由调度器配置传入（DB 覆写优先）；为 None 时回退 env FIRE_ALARM_CHAT_ID
    - 17:00 触发：先 sync_from_bitable（白天事件同步兜底）→ 再 generate_daily_report
      （对齐 special_op 日报调度路径 sync → generate）
    - 日报私发为独立任务（消防报警日报私发 → run_daily_fire_alarm_dm），不在本入口执行
    - 异常向上抛（2026-09-02 改，与 run_daily_fire_alarm_dm 同）：调度器标 failed
      后在补发窗口内自动重试；此前吞异常返回 None 会被误标 success。
    """
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        service = FireAlarmService(session)
        # 同步兜底：17:00 生成前拉全量，防白天事件同步漏掉记录
        synced, soft_deleted = await service.sync_from_bitable()
        if synced or soft_deleted:
            await session.commit()
            logger.info(
                "消防报警同步兜底: synced=%d soft_deleted=%d",
                synced, soft_deleted,
            )
        result = await service.generate_daily_report(
            target_date=target_date, push=True, channel="system",
            rolling=True, chat_id=chat_id,
        )
        await session.commit()
        # 2026-09-02：请求了推送但发送失败 → 上抛标 failed 走补发重试。
        # 此前推送失败只记在 push_results（success=False）不抛，任务被误标
        # success，当天群卡片静默丢失（API 手动流程不受影响，仍走返回值）。
        failed_pushes = [
            p for p in result.push_results
            if not p.get("skipped") and not p.get("success")
        ]
        if failed_pushes:
            raise RuntimeError(
                f"消防报警日报推送失败: {failed_pushes}"
            )
        return result


async def run_daily_fire_alarm_dm(
    target_date: date | None = None,
    skip_sync: bool = False,
) -> dict[str, int] | None:
    """定时任务入口：消防报警日报私发（一卡一条 DM）。

    流程（每日 17:00，与群日报同窗口）：
      1. 开关 SAFETY_FIRE_ALARM_DAILY_DM_ENABLED 未启用 → 跳过（返回 None）
      2. sync_from_bitable 兜底（防白天事件同步漏掉记录）；
         skip_sync=True 时跳过（调度器判定群任务刚成功、同表刚全量同步过）
      3. generate_daily_report(push=False, rolling=True) 复用/补齐 AI 分析并回写
         （analyst 增量：已分析记录不重复调用 AI，群/私任务先后跑均只分析一遍）
      4. send_daily_alarm_dms 按「一卡一条」私发给涉及部门负责人 + 分管安全员

    异常向上抛（2026-09-02 改）：调度器捕获后标 failed，补发窗口内自动重试。
    """
    from app.core.database import async_session_factory
    from app.modules.safety.service.fire_alarm.daily_dm import (
        DM_ENABLED,
        send_daily_alarm_dms,
    )

    if not DM_ENABLED:
        logger.info("消防报警日报私发已关闭 (SAFETY_FIRE_ALARM_DAILY_DM_ENABLED=false)")
        return None

    # 2026-09-02：不再吞异常。此前 except→return None 会让调度器把失败任务
    # 误标 success（跳过≠成功），当天卡片一张没发也不再重试。异常向上抛给
    # 调度器（_run_scheduled_job）→ 标 failed → 补发窗口内自动重试。
    async with async_session_factory() as session:
        service = FireAlarmService(session)
        # 同步兜底：生成前拉全量，防白天事件同步漏掉记录
        if not skip_sync:
            synced, soft_deleted = await service.sync_from_bitable()
            if synced or soft_deleted:
                await session.commit()
                logger.info(
                    "消防报警同步兜底: synced=%d soft_deleted=%d",
                    synced, soft_deleted,
                )
        else:
            logger.info("消防报警私发跳过同步（群任务刚完成同步兜底）")
        # 复用/补齐 AI 分析（不推送）；与私发共用同一滚动窗口
        await service.generate_daily_report(
            target_date=target_date, push=False, channel="system", rolling=True,
        )
        await session.commit()

        dm_records, _ws, _we = await service._get_records_by_rolling_window(
            target_date or _bj_today()
        )
        return await send_daily_alarm_dms(service.session, records=dm_records)


async def run_weekly_fire_alarm_analysis(
    week_end: date | None = None,
) -> FireAlarmReportResponse | None:
    """定时任务入口：生成并推送周报到默认群聊（scheduler-ready，本期不注册）。

    - 独立 async_session_factory session，channel="system"，push=True
    - 失败 try/except 不抛，记录日志返回 None（与 run_daily_fire_alarm_analysis 同模式）
    """
    from app.core.database import async_session_factory

    try:
        async with async_session_factory() as session:
            service = FireAlarmService(session)
            result = await service.generate_weekly_report(
                week_end=week_end, push=True, channel="system",
            )
            await session.commit()
            return result
    except Exception:
        logger.exception("消防报警周报任务失败")
        return None
