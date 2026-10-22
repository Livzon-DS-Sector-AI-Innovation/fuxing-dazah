"""周期定格（S1 体系标准符合性核查，二期）——DESIGN §4.3。

每季度首日 08:20 定格上一季度全部季度/月度项 + 半年终版（窗口结束即定格）
+ 年度项当前快照；每年 1 月 1 日同一次运行另定格上一年度年度项终版
（upsert 覆盖中期快照）。定格=复用 page._collect_verdicts 判定管线，
窗口传目标历史周期、评估日传定格日（engine.judge 的 ended 分支）；
period_end 型比率指标随之用该周期完整数据重算（如 Q3 按期整改率窗口=
7-1~9-30 整季）。重复定格=upsert 幂等；清单行删除/标准废弃不定格
（已定格 snapshot 天然留档）；核查表未接入 → no_source 哨兵（严禁假 success）。
"""

from __future__ import annotations

import logging
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.safety.models.standard_check import (
    SNAP_ACHIEVED,
    SNAP_IN_PROGRESS,
    SNAP_MANUAL_DONE,
    SNAP_MANUAL_MISSED,
    SNAP_MISSED,
    SNAP_NO_DATA,
    StandardCheckSnapshot,
)
from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.bitable_direct.errors import BitableConfigError
from app.modules.safety.service.standard_check import page as sc_page
from app.modules.safety.service.standard_check.engine import (
    ST_MISSED,
    ST_NO_DATA,
    ST_OK,
    PeriodWindow,
    StandardRow,
    Verdict,
)
from app.modules.safety.service.standard_check.metrics import MetricContext

logger = logging.getLogger(__name__)

QUARTER_START_MONTHS = (1, 4, 7, 10)

# 周期值与定格目标的对应：月度/季度/半年各自成靶；其余（年度、长周期(3年)、
# 按项目/按事件/按修订、年度汇总、空值）统归年度桶——季度首日运行刷新当年
# 中期快照（period_key=年，长周期/按事件类判定不依赖窗口，刷新无害），1-1
# 运行写入上年终版收口（当年最后一次写=终版，法定留档）。
_BUCKET_PERIODS = ("月度", "季度", "半年")


def _month_end(y: int, m: int) -> date:
    return date(y, m, monthrange(y, m)[1])


@dataclass(frozen=True)
class FreezeTarget:
    """一次定格运行中的一个目标周期。"""

    period_key: str          # 2026 / 2026H1 / 2026-Q3 / 2026-09
    checklist_year: int      # 读清单行的「年度」过滤值
    window: PeriodWindow     # 判定窗口（终版=整周期；中期=当年窗口）
    kind: str                # quarter / month / half_year / year_interim / year_final
    period_value: str | None  # 匹配清单「周期」列；None=年度桶（非月/季/半年）
    in_cell: bool            # 是否计入季度符合性速递格


def quarter_targets(today: date) -> tuple[FreezeTarget, ...]:
    """定格日 → 目标周期清单（纯函数）。

    - 4/1：Q1 终版 + 1~3 月终版 + 年度中期
    - 7/1：Q2 终版 + 4~6 月终版 + H1 终版 + 年度中期
    - 10/1：Q3 终版 + 7~9 月终版 + 年度中期
    - 1/1：上年 Q4 终版 + 10~12 月终版 + 上年 H2 终版 + 上年年度终版
    - 非季度首日 → 空元组（调度端 months 已挡，直调防护）
    """
    if today.day != 1 or today.month not in QUARTER_START_MONTHS:
        return ()

    m, y = today.month, today.year
    pq_y, pq_start = (y - 1, 10) if m == 1 else (y, m - 3)

    targets: list[FreezeTarget] = [
        FreezeTarget(
            period_key=f"{pq_y}-Q{(pq_start - 1) // 3 + 1}",
            checklist_year=pq_y,
            window=PeriodWindow(date(pq_y, pq_start, 1), _month_end(pq_y, pq_start + 2)),
            kind="quarter", period_value="季度", in_cell=True,
        ),
    ]
    for mm in (pq_start, pq_start + 1, pq_start + 2):
        targets.append(FreezeTarget(
            period_key=f"{pq_y}-{mm:02d}",
            checklist_year=pq_y,
            window=PeriodWindow(date(pq_y, mm, 1), _month_end(pq_y, mm)),
            kind="month", period_value="月度", in_cell=True,
        ))

    if pq_start == 4:  # 7-1 运行：上季度=Q2 含 6-30 → H1 窗口结束，终版定格
        targets.append(FreezeTarget(
            period_key=f"{pq_y}H1", checklist_year=pq_y,
            window=PeriodWindow(date(pq_y, 1, 1), date(pq_y, 6, 30)),
            kind="half_year", period_value="半年", in_cell=True,
        ))
    elif pq_start == 10:  # 1-1 运行：上季度=Q4 含 12-31 → H2 终版
        targets.append(FreezeTarget(
            period_key=f"{pq_y}H2", checklist_year=pq_y,
            window=PeriodWindow(date(pq_y, 7, 1), date(pq_y, 12, 31)),
            kind="half_year", period_value="半年", in_cell=True,
        ))

    if m == 1:  # 年度终版：上一年整窗（评估日=定格日 > 窗口末 → ended 终态）
        fy = y - 1
        targets.append(FreezeTarget(
            period_key=str(fy), checklist_year=fy,
            window=PeriodWindow(date(fy, 1, 1), date(fy, 12, 31)),
            kind="year_final", period_value=None, in_cell=False,
        ))
    else:  # 年度中期快照：当年窗口 + 定格日评估（可 in_progress，1-1 终版覆盖）
        targets.append(FreezeTarget(
            period_key=str(y), checklist_year=y,
            window=PeriodWindow(date(y, 1, 1), date(y, 12, 31)),
            kind="year_interim", period_value=None, in_cell=False,
        ))
    return tuple(targets)


def snapshot_status(row: StandardRow, verdict: Verdict) -> tuple[str, str | None]:
    """engine 四态 → snapshot 状态映射（spec §4.2）。

    人工项（metric_key 空）ok/missed → manual_done/manual_missed；空值
    （engine 给 in_progress·待人工核查）→ no_data·「定格时未勾选核查结果」
    （冤案零容忍：没勾≠没做，无数据 Z 项在速递格倒逼补勾）。
    自动项 in_progress 仅出现于年度/半年中期快照，终版定格覆盖为终态。
    """
    if verdict.status == ST_NO_DATA:
        return SNAP_NO_DATA, verdict.note
    if not row.metric_key:
        if verdict.status == ST_OK:
            return SNAP_MANUAL_DONE, verdict.note
        if verdict.status == ST_MISSED:
            return SNAP_MANUAL_MISSED, verdict.note
        return SNAP_NO_DATA, "定格时未勾选核查结果"
    if verdict.status == ST_OK:
        return SNAP_ACHIEVED, verdict.note
    if verdict.status == ST_MISSED:
        return SNAP_MISSED, verdict.note
    return SNAP_IN_PROGRESS, verdict.note


@dataclass
class FreezeResult:
    """一次定格运行的统计（调度日志 / 速递格输入）。"""

    ran: bool = True
    no_source: bool = False
    frozen: int = 0
    quarter_key: str = ""  # 当季季度靶（速递格标题锚）
    targets: list[str] = field(default_factory=list)
    # 当季定格行（速递格范围：季度+月度+当季结束的半年项），含 no/条款/状态/部门/原因
    cell_rows: list[dict[str, Any]] = field(default_factory=list)


def _bj_today() -> date:
    # 与 page._bj_today 同口径复用，避免双份实现漂移
    return sc_page._bj_today()


async def freeze_due(
    *,
    db: Any,
    opener: Any | None = None,
    today: date | None = None,
) -> FreezeResult:
    """执行定格：读核查表 → 逐目标历史窗口判定 → upsert snapshot（不提交，调用方 commit）。"""
    today = today or _bj_today()
    targets = quarter_targets(today)
    if not targets:
        return FreezeResult(ran=False)
    open_client = opener or bd_reader.resolve_client
    try:
        client = open_client(sc_page.DOMAIN, sc_page.KIND)
        records = await bd_reader.fetch_all_records(
            client, field_names=sc_page.FIELD_NAMES, strict=True
        )
    except BitableConfigError as exc:
        logger.info("标准核查表未接入，定格跳过(no_source): %s", exc)
        return FreezeResult(no_source=True)

    rows_all = [sc_page._parse_row(r) for r in records]
    ctx = MetricContext(db=db, opener=opener)
    result = FreezeResult(
        quarter_key=targets[0].period_key,  # quarter 靶恒为首靶
        targets=[t.period_key for t in targets],
    )
    frozen_at = datetime.now(UTC)

    for target in targets:
        year_rows = [
            r for r in rows_all
            if r.year == str(target.checklist_year) and r.no
        ]
        if target.period_value is None:
            t_rows = [r for r in year_rows if r.period not in _BUCKET_PERIODS]
        else:
            t_rows = [r for r in year_rows if r.period == target.period_value]
        if not t_rows:
            continue

        triples = await sc_page._collect_verdicts(
            t_rows, ctx, today, lambda _row, w=target.window: w
        )
        for row, outcome, verdict in triples:
            status, note = snapshot_status(row, verdict)
            values: dict[str, Any] = dict(
                standard_no=row.no,
                year=target.checklist_year,
                period_key=target.period_key,
                metric_key=row.metric_key,
                actual_value=outcome.value,
                operator=row.operator,
                target_value=row.target_value,
                status=status,
                evidence={
                    "window": {
                        "start": target.window.start.isoformat(),
                        "end": target.window.end.isoformat(),
                    },
                    "items": [dict(e) for e in outcome.evidence],
                    "no_data_reason": outcome.no_data_reason,
                },
                frozen_at=frozen_at,
                clause=row.clause,
                basis=row.basis,
                element=row.element,
                period=row.period,
                unit=row.unit,
                department=list(row.department) or None,
                owner=row.owner,
                manual_result=row.manual_result,
                last_done_on=row.last_done_on,
                actual_display=verdict.actual_display,
                note=note,
            )
            stmt = pg_insert(StandardCheckSnapshot).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["standard_no", "period_key"],
                set_=values,
            )
            await db.execute(stmt)
            result.frozen += 1
            if target.in_cell:
                result.cell_rows.append({
                    "period_key": target.period_key,
                    "no": row.no,
                    "clause": row.clause,
                    "status": status,
                    "department": list(row.department),
                    "note": note or outcome.no_data_reason,
                })

    logger.info(
        "标准符合性定格完成: frozen=%d targets=%s no_source=%s",
        result.frozen, result.targets, result.no_source,
    )
    return result


# ═══════════════════════════════════════════════════════════════
# 季度符合性速递格（DESIGN §4.4：一条/季，只通报不点名个人、不排名）
# ═══════════════════════════════════════════════════════════════

_CLAUSE_LIMIT = 24


def build_compliance_cell(
    cell_rows: list[dict[str, Any]], *, quarter_key: str
) -> Any:
    """当季定格行 → 速递格（纯函数）。

    口径（spec §4.6）：X=achieved+manual_done，Y=X+missed+manual_missed，
    Z=no_data——人工项计入（与页面 compliance_rate 口径一致）；年度中期/终版
    不入格（cell_rows 由 freeze_due 按 in_cell 圈定）。
    """
    from app.modules.safety.feishu.daily_digest import DigestCell

    achieved = [r for r in cell_rows if r["status"] in ("achieved", "manual_done")]
    missed = [r for r in cell_rows if r["status"] in ("missed", "manual_missed")]
    no_data = [r for r in cell_rows if r["status"] == "no_data"]
    x, y, z = len(achieved), len(achieved) + len(missed), len(no_data)

    stats = (
        f"上季度标准达成 **{x}**/{y}"
        + (f" ｜ 未达标 **{len(missed)}**" if missed else "")
        + (f" ｜ 无数据 **{z}** 项" if no_data else "")
    )

    if missed:
        zone = f"未达标 {len(missed)} 项：{missed[0]['no']} {'、'.join(missed[0]['department']) or '未指派部门'}"
        color = "red"
    elif no_data:
        zone = f"上季度判定标准全部达标；另有 {z} 项无数据（源未接入/未核查）"
        color = "orange"
    else:
        zone = f"上季度判定标准全部达标（{x}/{y}）"
        color = "green"

    lines: list[str] = [f"**定格范围**：{quarter_key}（季度/月度项+当季结束的半年项）", ""]
    lines.append(f"**未达标（{len(missed)} 项）**")
    if missed:
        for r in missed:
            dept = "、".join(r["department"]) or "未指派"
            clause = r["clause"][:_CLAUSE_LIMIT]
            lines.append(f"- {r['no']} {clause}（{dept}）")
    else:
        lines.append("无")
    lines.append("")
    lines.append(f"**无数据（{z} 项，不计入达标率）**")
    if no_data:
        by_reason: dict[str, list[str]] = {}
        for r in no_data:
            reason = (r.get("note") or "无数据").strip()
            by_reason.setdefault(reason, []).append(r["no"])
        for reason, nos in by_reason.items():
            lines.append(f"- {reason}：{len(nos)} 项（{'、'.join(nos[:8])}）")
    else:
        lines.append("无")
    lines.append("")
    lines.append("责任落点见「目标责任与绩效」页清单与历史定格 Tab；本通报不点名个人、不排名")

    return DigestCell(
        tag_color=color,
        tag_text="标准符合性",
        title=f"体系标准符合性 · {quarter_key}",
        stats=stats,
        zone=zone[:100],
        detail="\n".join(lines),
    )


async def send_standard_compliance_digest(
    result: FreezeResult,
    *,
    chat_id: str | None = None,
    report_date: date | None = None,
) -> dict[str, Any]:
    """定格收尾投递速递格：总卡开启并入当日卡，关闭时独立群卡（照消防月报模式）。

    失败上抛 → 调度器标 failed 在补发窗口（当日 23:30）内重试；定格幂等 upsert
    + 格子按定格日 key 重投，重试不产生重复行/重复格。
    """
    from app.modules.safety.feishu.daily_digest import (
        digest_enabled,
        send_digest_cell_card,
        upsert_daily_digest,
    )

    if not result.cell_rows or not result.quarter_key:
        return {"sent": True, "skipped": "无当季定格行", "frozen": result.frozen}
    cell = build_compliance_cell(result.cell_rows, quarter_key=result.quarter_key)
    report_date = report_date or _bj_today()

    if digest_enabled():
        ok = await upsert_daily_digest(report_date, "standard_compliance", cell)
    else:
        ok = bool(await send_digest_cell_card(
            cell, chat_id=chat_id,
            title=f"📌 {cell.title} | {report_date.isoformat()}",
        ))
    if not ok:
        raise RuntimeError("标准符合性速递格投递失败（总卡/群卡未确认）")
    stats = {
        "sent": True,
        "report_date": report_date.isoformat(),
        "quarter": result.quarter_key,
        "cell_rows": len(result.cell_rows),
        "frozen": result.frozen,
    }
    logger.info("标准符合性速递格已投递: %s", stats)
    return stats
