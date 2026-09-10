"""中控报警 CentralAlarmService — Bitable 多表全量同步（ticket 02）。

数据源：飞书 Base「中控报警统计」`OdMRbCWr3aNEZKsFz94cAt12nzh` 下 15 张同构表。
同步以 feishu_record_id 为主键 upsert；workshop/line 从 Bitable 表名推导。

与 fire_alarm（单表）不同：本服务循环 15 张表，每张表分页拉取 + 软删对齐，
并先 GET /tables 取表名（id→name 映射）以推导车间/产线。
"""
from __future__ import annotations

import logging
import os
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.bitable_config.store import ConnectionView, store
from app.modules.safety.feishu.notification import send_group_card
from app.modules.safety.models import CentralAlarmRecord
from app.modules.safety.schemas.central_alarm import CentralAlarmReportResponse
from app.modules.safety.service.central_alarm.analyst import CentralAlarmAnalyst
from app.modules.safety.service.central_alarm.bitable_mapper import (
    derive_workshop_line,
    map_bitable_fields,
)
from app.modules.safety.service.central_alarm.renderer import render_daily_report

logger = logging.getLogger(__name__)

# ── 连接配置（配置中心 store：主表 + extra_table_ids 白名单，§5.3）──
def _central_conn() -> ConnectionView | None:
    """中控报警连接配置（白名单主表 + extra_table_ids；未启用/缺失返回 None）。"""
    return store.get_connection("central_alarm", "alarm")


def central_alarm_app_token() -> str:
    """中控报警 Base app_token；未启用/缺失返回空串。"""
    conn = _central_conn()
    return conn.app_token if conn and conn.enabled else ""


def central_alarm_table_ids() -> list[str]:
    """白名单全部表 ID（主表 + extra_table_ids）；未启用/缺失返回 []。"""
    conn = _central_conn()
    if conn is None or not conn.enabled:
        return []
    return [t for t in [conn.table_id, *conn.extra_table_ids] if t]


# 日报推送目标群（未配置 → 跳过推送，联调期安全）
CENTRAL_ALARM_CHAT_ID = os.getenv("SAFETY_CENTRAL_ALARM_ANALYSIS_CHAT_ID", "")

# 全量同步分页配置（参照 fire_alarm / special_op；但中央报警表较大，需更高上限防截断）
MAX_PAGES = 50
PAGE_SIZE = 500

# UPDATE 时不覆盖的同步标识字段（workshop/line 由同步逻辑按表推导，应随 re-sync 纠正，故不排除）
_NON_BITABLE_KEYS = ("feishu_record_id", "source")


class CentralAlarmService:
    """中控报警分析业务服务（同步 + 查询/统计 + 日报生成与推送编排）。"""

    def __init__(self, session: AsyncSession, ai_service: Any = None) -> None:
        self.session = session
        self.analyst = CentralAlarmAnalyst(session, ai_service=ai_service)

    # ── 全量同步（循环 15 表）──

    async def sync_from_bitable(self) -> tuple[int, int]:
        """从飞书 Bitable 全量同步到 CentralAlarmRecord。

        Returns:
            (synced_count, soft_deleted_count)

        算法（backend-design.md §3.2）:
          1. GET /tables 取 id→name 映射（推导 workshop/line 用）
          2. 循环业务表（排除含「配置」的配置表），每张表 GET /records 分页拉取 + upsert
          3. 全部表同步完后统一软删对齐：本地有但远端（任一白名单表）无的 bitable 来源活行
             → is_deleted=true + feishu_record_id=NULL（软删除铁律）
        """
        import httpx

        from app.modules.safety.feishu.client import get_safety_tenant_token

        async with httpx.AsyncClient(timeout=30) as http:
            token = await get_safety_tenant_token()
            name_map = await self._fetch_table_name_map(http, token)
            now = datetime.now(UTC)

            synced = 0
            all_remote_ids: set[str] = set()
            for table_id in central_alarm_table_ids():
                table_name = name_map.get(table_id, "")
                # 排除配置表（非报警记录，如「中控报警数据源配置」）
                if _is_config_table(table_name):
                    logger.info("中控报警跳过配置表: table_id=%s name=%s", table_id, table_name)
                    continue
                workshop, line = derive_workshop_line(table_name)
                s, remote_ids = await self._sync_one_table(
                    http, token, table_id, table_name, workshop, line, now,
                )
                synced += s
                all_remote_ids |= remote_ids

            # 全局软删对齐：远端（全部白名单表）已删 → 本地软删 + 清空 feishu_record_id
            if all_remote_ids:
                stmt = (
                    update(CentralAlarmRecord)
                    .where(
                        CentralAlarmRecord.source == "bitable",
                        CentralAlarmRecord.is_deleted == False,  # noqa: E712
                        CentralAlarmRecord.feishu_record_id.is_not(None),
                        CentralAlarmRecord.feishu_record_id.not_in(all_remote_ids),
                    )
                    .values(is_deleted=True, feishu_record_id=None, synced_at=now)
                )
                result = await self.session.execute(stmt)
                soft_deleted = cast(CursorResult[Any], result).rowcount or 0
            else:
                soft_deleted = 0
        return synced, soft_deleted

    async def _fetch_table_name_map(
        self, http: Any, token: str,
    ) -> dict[str, str]:
        """GET /bitable/v1/apps/{app_token}/tables → {table_id: table_name}。"""
        url = (
            f"https://open.feishu.cn/open-apis/bitable/v1/apps"
            f"/{central_alarm_app_token()}/tables"
        )
        resp = await http.get(url, headers={"Authorization": f"Bearer {token}"})
        d = resp.json()
        if not isinstance(d, dict) or d.get("code", 0) != 0:
            logger.error("Bitable tables 拉取失败: code=%s msg=%s",
                         d.get("code") if isinstance(d, dict) else "?",
                         d.get("msg") if isinstance(d, dict) else "?")
            return {}
        items = d.get("data", {}).get("items", []) or []
        return {item.get("table_id", ""): item.get("name", "") for item in items}

    async def _sync_one_table(
        self, http: Any, token: str, table_id: str, table_name: str,
        workshop: str, line: str | None, now: datetime,
    ) -> tuple[int, set[str]]:
        """单表分页拉取 + upsert + 软删对齐。

        Returns:
            (synced, remote_ids)：本次 upsert 条数 + 该表远端全部 record_id 集合
            （供全局软删对齐用；本方法不做软删，跨表软删在 sync_from_bitable 统一处理）。
        """
        records_url = (
            f"https://open.feishu.cn/open-apis/bitable/v1/apps"
            f"/{central_alarm_app_token()}/tables/{table_id}/records"
        )
        records: list[dict[str, Any]] = []
        page_token: str | None = None
        for _ in range(MAX_PAGES):
            params: dict[str, Any] = {"page_size": PAGE_SIZE}
            if page_token:
                params["page_token"] = page_token
            resp = await http.get(
                records_url, headers={"Authorization": f"Bearer {token}"}, params=params,
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
        for rec in records:
            record_id = str(rec.get("record_id") or "").strip()
            if not record_id:
                continue
            remote_ids.add(record_id)
            mapped = map_bitable_fields(rec.get("fields") or {})
            mapped["feishu_record_id"] = record_id
            mapped["source"] = "bitable"
            mapped["workshop"] = workshop
            mapped["line"] = line
            mapped["synced_at"] = now

            existing = await self.session.scalar(
                select(CentralAlarmRecord).where(
                    CentralAlarmRecord.feishu_record_id == record_id,
                    CentralAlarmRecord.is_deleted == False,  # noqa: E712
                )
            )
            if existing is not None:
                # UPDATE — 只覆盖 Bitable 字段，保留平台 AI 分析字段
                for k, v in mapped.items():
                    if v is not None and k not in _NON_BITABLE_KEYS:
                        setattr(existing, k, v)
            else:
                self.session.add(CentralAlarmRecord(**mapped))
            synced += 1

        return synced, remote_ids

    # ── 查询 ──

    async def get_records(
        self, *,
        date_from: date | None = None,
        date_to: date | None = None,
        workshop: str | None = None,
        line: str | None = None,
        post: str | None = None,
        ai_alarm_type: str | None = None,
        ai_dimension: str | None = None,
        ai_pattern: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[CentralAlarmRecord], int]:
        """分页查询中控报警记录（多条件筛选，默认过滤软删）。

        Returns:
            (records, total)：按 alarm_date 倒序（最新在前）。
        """
        conds = [CentralAlarmRecord.is_deleted == False]  # noqa: E712
        if date_from is not None:
            conds.append(
                CentralAlarmRecord.alarm_date
                >= datetime.combine(date_from, time.min, tzinfo=UTC)
            )
        if date_to is not None:
            conds.append(
                CentralAlarmRecord.alarm_date
                < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC)
            )
        if workshop:
            conds.append(CentralAlarmRecord.workshop == workshop)
        if line:
            conds.append(CentralAlarmRecord.line == line)
        if post:
            conds.append(CentralAlarmRecord.post == post)
        if ai_alarm_type:
            conds.append(CentralAlarmRecord.ai_alarm_type == ai_alarm_type)
        if ai_dimension:
            conds.append(CentralAlarmRecord.ai_dimension == ai_dimension)
        if ai_pattern:
            conds.append(CentralAlarmRecord.ai_pattern == ai_pattern)
        if keyword:
            kw = f"%{keyword}%"
            conds.append(
                or_(
                    CentralAlarmRecord.alarm_description.ilike(kw),
                    CentralAlarmRecord.special_note.ilike(kw),
                )
            )

        total = (
            await self.session.scalar(
                select(func.count(CentralAlarmRecord.id)).where(*conds)
            )
        ) or 0
        offset = (page - 1) * page_size
        rows = (
            await self.session.scalars(
                select(CentralAlarmRecord)
                .where(*conds)
                .order_by(CentralAlarmRecord.alarm_date.desc())
                .offset(offset)
                .limit(page_size)
            )
        ).all()
        return list(rows), total

    async def get_stats(self, target_date: date | None = None) -> dict[str, Any]:
        """KPI：今日/本周报警数 + 车间/岗位/报警类型/异常模式/维度分布。

        统计口径（北京时间 UTC+8）：
          - date：target_date 或今天；今日窗口 = 该日 00:00~24:00 北京时间
          - 本周 = 该日所在自然周（周一~周日）
          - 分布基于本周窗口内记录（非软删）；total_count 为全量非软删数
          - week_ai_analyzed_count = 本周窗口内 ai_analyzed_at 非空的记录数
        """
        from .aggregator import get_natural_week_range

        target_date = target_date or _bj_today()
        today_records = await self._get_records_by_date(target_date)
        week_start, week_end = get_natural_week_range(target_date)
        week_records = await self._get_records_by_week(week_start, week_end)
        total_count = (
            await self.session.scalar(
                select(func.count(CentralAlarmRecord.id)).where(
                    CentralAlarmRecord.is_deleted == False  # noqa: E712
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
            "workshop_distribution": _count_by(week_records, "workshop"),
            "post_distribution": _count_by(week_records, "post"),
            "alarm_type_distribution": _count_by(week_records, "ai_alarm_type"),
            "pattern_distribution": _count_by(week_records, "ai_pattern"),
            "dimension_distribution": _count_by(week_records, "ai_dimension"),
        }

    async def _get_records_by_date(self, target_date: date) -> list[CentralAlarmRecord]:
        """按北京时间自然日窗口查询当日报警记录（非软删）。"""
        utc_start = (
            datetime.combine(target_date, time.min, tzinfo=UTC)
            - timedelta(hours=8)  # 北京时间 00:00 = UTC 前一日 16:00
        )
        return list(
            (
                await self.session.scalars(
                    select(CentralAlarmRecord).where(
                        CentralAlarmRecord.is_deleted == False,  # noqa: E712
                        CentralAlarmRecord.alarm_date >= utc_start,
                        CentralAlarmRecord.alarm_date < utc_start + timedelta(days=1),
                    )
                )
            ).all()
        )

    async def _get_records_by_week(
        self, week_start: date, week_end: date,
    ) -> list[CentralAlarmRecord]:
        """按北京时间自然周窗口查询周报警记录（周一 00:00 ~ 周日 24:00 北京时间）。"""
        utc_start = (
            datetime.combine(week_start, time.min, tzinfo=UTC)
            - timedelta(hours=8)
        )
        utc_end = (
            datetime.combine(week_end + timedelta(days=1), time.min, tzinfo=UTC)
            - timedelta(hours=8)
        )
        return list(
            (
                await self.session.scalars(
                    select(CentralAlarmRecord).where(
                        CentralAlarmRecord.is_deleted == False,  # noqa: E712
                        CentralAlarmRecord.alarm_date >= utc_start,
                        CentralAlarmRecord.alarm_date < utc_end,
                    )
                )
            ).all()
        )


    # ── 日报生成与推送 ──

    async def generate_daily_report(
        self, target_date: date | None = None, *,
        push: bool = True, channel: str = "web", rolling: bool = True,
        chat_id: str | None = None,
    ) -> CentralAlarmReportResponse:
        """生成当日中控报警分析报告（聚合 → 逐条 AI 回写 → 汇总 AI → 渲染 → 推送）。

        时间窗口默认「前日 17:00 ~ 当日 17:00」（北京时间，与消防报警一致，rolling=True）；
        传入 rolling=False 则用自然日窗口（00:00~24:00）。

        Args:
            target_date: 目标日期，默认今天（北京时间 UTC+8）
            push: 是否推送（False 用于 Agent 直接返回报告）
            channel: 审计渠道（web/feishu/system）
            rolling: 是否用滚动 24h 窗口（前日17:00~当日17:00）。默认 True（与消防报警一致）；
                传 False 用自然日窗口（00:00~24:00）。

        Returns:
            CentralAlarmReportResponse（markdown_report 恒非空；AI 全失败时退化为
            纯数据汇总版本；推送未配置/失败时 push_results 标记 skipped/error）
        """
        from .aggregator import aggregate_daily

        target_date = target_date or _bj_today()
        window_start_utc: datetime | None = None
        window_end_utc: datetime | None = None
        if rolling:
            records, window_start_utc, window_end_utc = (
                await self._get_records_by_rolling_window(target_date)
            )
        else:
            records = await self._get_records_by_date(target_date)
        # 筛选规则：仅统计 高高压力 / 高高液位 / 回收车间高高温 三类，不做全量
        records = _filter_high_high_alarms(records)
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
                    select(CentralAlarmRecord).where(CentralAlarmRecord.id.in_(record_ids))
                )
            ).all()
            agg.records = list(re_fetched)
            agg = _recompute_agg_distributions(agg)
            await self.session.commit()

        # 汇总 AI（失败返回 None，renderer 省略 AI 块）
        per_summaries = [
            f"报警{_bj(r.alarm_date)} {r.workshop or '?'} {r.post or '?'} - {r.ai_reason_analysis[:60]}"
            for r in agg.records if r.ai_reason_analysis
        ]
        ai_summary = await self.analyst.analyze_daily_summary(
            agg, per_summaries, channel=channel,
        )

        markdown = render_daily_report(
            agg, ai_summary, window_start_utc=window_start_utc,
            window_end_utc=window_end_utc,
        )

        # 推送（push=False 或 env 未配置 → skipped）
        push_results = await self._maybe_push(
            title=f"中控报警日报 - {target_date.strftime('%Y-%m-%d')}",
            content=markdown, push=push, chat_id=chat_id,
        )

        return CentralAlarmReportResponse(
            report_kind="daily",
            target_date=target_date,
            total=agg.total,
            analyzed=len(per_results),
            markdown_report=markdown,
            push_results=push_results,
            records_analyzed=[r.id for r in agg.records if r.ai_analyzed_at],
        )

    # ── 推送辅助 ──

    async def _maybe_push(
        self, *, title: str, content: str, push: bool, chat_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """推送群卡片；无生效 chat_id 或 push=False → 跳过并标记 skipped。

        发送目标唯一来源：调度器配置（DB 播种/覆写），不再回退 env。
        """
        effective_chat_id = chat_id
        if not push or not effective_chat_id:
            logger.info(
                "中控报警分析推送跳过（push=%s chat_id 配置=%s）",
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
                chat_id=effective_chat_id, title=title, content=content,
            )
            return [{"chat_id": effective_chat_id,
                     "success": msg_id is not None, "message_id": msg_id}]
        except Exception as exc:
            logger.exception("推送失败: chat_id=%s", effective_chat_id)
            return [{"chat_id": effective_chat_id, "success": False, "error": str(exc)}]

    async def _get_records_by_rolling_window(
        self, target_date: date,
    ) -> tuple[list[CentralAlarmRecord], datetime, datetime]:
        """按滚动 24h 窗口查询：前日 17:00 ~ 当日 17:00（北京时间）。"""
        utc_end = datetime.combine(target_date, time(9, 0), tzinfo=UTC)
        utc_start = utc_end - timedelta(days=1)
        return list(
            (
                await self.session.scalars(
                    select(CentralAlarmRecord).where(
                        CentralAlarmRecord.is_deleted == False,  # noqa: E712
                        CentralAlarmRecord.alarm_date >= utc_start,
                        CentralAlarmRecord.alarm_date < utc_end,
                    )
                )
            ).all()
        ), utc_start, utc_end


def _bj_today() -> date:
    """北京时间今天（UTC+8）。"""
    return (datetime.now(UTC) + timedelta(hours=8)).date()


def _count_by(records: list[CentralAlarmRecord], attr: str) -> dict[str, int]:
    """按记录字段统计分布（值为 None 的字段不计入）。"""
    out: dict[str, int] = {}
    for r in records:
        v = getattr(r, attr)
        if v is None:
            continue
        out[v] = out.get(v, 0) + 1
    return out


def _is_config_table(table_name: str) -> bool:
    """是否为非业务的配置表（表名含「配置」，如「中控报警数据源配置」）。"""
    return "配置" in (table_name or "")


# ── 日报筛选规则（仅统计三类"高高"报警，不做全量；排除泡碱操作的高高液位）──
_HIGH_HIGH_PRESSURE_KW = ("高高压",)        # 高高压力（文本标记"高高压"）
_HIGH_HIGH_LEVEL_KW = ("高高液",)           # 高高液位（含 高高液位/高/高高液位/高高液）
_HIGH_HIGH_TEMP_KW = ("高高温",)            # 高高温度
_RECYCLE_WORKSHOPS = ("酒精回收和旧罐区", "乙腈回收", "异丙醇回收")  # 回收车间
_PAO_JIAN_KW = ("泡碱",)                    # 泡碱操作（其高高液位不统计）


def _is_high_high_alarm(record: CentralAlarmRecord) -> bool:
    """判断是否属于 高高压力 / 高高液位(除泡碱) / 回收车间高高温 三类。"""
    desc = (record.alarm_description or "")
    # 1. 高高压力（含"高高压"文本标记）
    if any(k in desc for k in _HIGH_HIGH_PRESSURE_KW):
        return True
    # 2. 回收车间高高温（仅回收车间）
    if record.workshop in _RECYCLE_WORKSHOPS and any(k in desc for k in _HIGH_HIGH_TEMP_KW):
        return True
    # 3. 高高液位（排除泡碱操作；单"高液位"不算高高，不匹配"高高液"）
    if any(k in desc for k in _HIGH_HIGH_LEVEL_KW):
        if not any(k in desc for k in _PAO_JIAN_KW):
            return True
    return False


def _filter_high_high_alarms(records: list[CentralAlarmRecord]) -> list[CentralAlarmRecord]:
    """仅保留 高高压力 / 高高液位(除泡碱) / 回收车间高高温 的高报警记录。"""
    return [r for r in records if _is_high_high_alarm(r)]


def _bj(dt: datetime | None) -> str:
    """UTC → 北京时间字符串（M/D HH:MM）。"""
    if dt is None:
        return "?"
    return (dt + timedelta(hours=8)).strftime("%m/%d %H:%M")


def _group_by_workshop(records: list[CentralAlarmRecord]) -> dict[str, list[CentralAlarmRecord]]:
    """按车间分组（渲染明细用）。"""
    out: dict[str, list[CentralAlarmRecord]] = {}
    for r in records:
        if r.workshop:
            out.setdefault(r.workshop, []).append(r)
    return out or {"全部": list(records)}


def _recompute_agg_distributions(agg: Any) -> Any:
    """逐条 AI 回写后重算聚合分布（聚合发生在回写前，统计需用最新值）。

    为避免循环依赖（aggregator 的 CentralAlarmDailyAgg），这里直接就地更新各分布字段。
    """
    agg.post_distribution = _count_by(agg.records, "post")
    agg.alarm_type_distribution = _count_by(agg.records, "ai_alarm_type")
    agg.pattern_distribution = _count_by(agg.records, "ai_pattern")
    agg.dimension_distribution = _count_by(agg.records, "ai_dimension")
    agg.workshop_distribution = _count_by(agg.records, "workshop")
    return agg


async def run_daily_central_alarm_analysis(
    target_date: date | None = None,
    chat_id: str | None = None,
) -> CentralAlarmReportResponse | None:
    """定时任务入口：全量同步兜底 + 生成并推送日报到默认群聊。

    - 独立 async_session_factory session，channel="system"，push=True
    - 17:00 触发：先 sync_from_bitable（白天事件同步兜底）→ 再 generate_daily_report
    - 异常向上抛（2026-09-02 改，与 fire_alarm 入口同）：调度器标 failed 后在
      补发窗口内自动重试；此前吞异常返回 None 会被误标 success。
    """
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        service = CentralAlarmService(session)
        synced, soft_deleted = await service.sync_from_bitable()
        if synced or soft_deleted:
            await session.commit()
            logger.info("中控报警同步兜底: synced=%d soft_deleted=%d", synced, soft_deleted)
        result = await service.generate_daily_report(
            target_date=target_date, push=True, channel="system", rolling=True, chat_id=chat_id,
        )
        await session.commit()
        # 2026-09-02：请求了推送但发送失败 → 上抛标 failed 走补发重试
        # （与 fire_alarm 入口同；跳过推送〔无 chat 配置〕不算失败）。
        failed_pushes = [
            p for p in result.push_results
            if not p.get("skipped") and not p.get("success")
        ]
        if failed_pushes:
            raise RuntimeError(f"中控报警日报推送失败: {failed_pushes}")
        return result
