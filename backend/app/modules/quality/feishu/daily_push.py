"""出报日期当日机器人任务推送：内容构建与发送（定时触发由 quality/scheduled.py 注册到平台统一调度引擎）。

- 早报：今日出报任务 + 待复核任务列表 + 明日出报预告（填报中的任务另发填报卡片）
- 午后催办：今日出报但尚未完成/复核的任务再提醒一次
"""

import logging
from datetime import timedelta

from app.core.time import today as _app_today

logger = logging.getLogger(__name__)

# Redis 不可用时的进程内降级标记：key 当天日期（重启可能重复推，可接受）
_PUSHED_IN_PROCESS: dict[str, str] = {}


async def _mark_pushed(key: str) -> bool:
    """防重复推送：SET NX 标记「key 今天已推」。

    返回 True=本次应推送；False=已推过（调度重复触发/重启/多副本时跳过）。
    标记 TTL 24 小时，次日自动失效重新推送。
    """
    try:
        from app.core.redis import acquire_lock

        return await acquire_lock(f"quality:push:{key}", timeout=24 * 3600)
    except Exception:
        logger.exception("Redis 推送幂等标记不可用，降级进程内标记")
        today = _app_today().isoformat()
        if _PUSHED_IN_PROCESS.get(key) == today:
            return False
        _PUSHED_IN_PROCESS[key] = today
        return True


def _parse_hhmm(value: str, default: tuple[int, int]) -> tuple[int, int]:
    """解析 HH:MM 配置（如 08:05），非法/为空回退默认值。"""
    try:
        h, m = value.strip().split(":")
        return int(h), int(m)
    except Exception:
        return default


async def _push_today_tasks() -> None:
    """早间推送：今日出报任务（含待复核）汇总；填报中的任务另发填报卡片。"""
    from app.core.database import async_session_factory
    from app.modules.quality.feishu.client import (
        QUALITY_FEISHU_CHAT_IDS,
        feishu_configured,
    )
    from app.modules.quality.feishu.message import send_chat_text
    from app.modules.quality.models import QualityTestResult, QualityTestTask
    from app.modules.quality.repository import (
        list_test_results,
        list_test_tasks,
        list_test_tasks_by_report_date,
    )

    if not feishu_configured() or not QUALITY_FEISHU_CHAT_IDS:
        return
    today = _app_today().isoformat()
    if not await _mark_pushed(f"morning:{today}"):
        logger.info("早报今日已推送，跳过（幂等标记）")
        return
    from app.modules.quality.feishu.fill_service import (
        _frontend_task_link,
        _task_doc_file_nos,
    )

    async with async_session_factory() as db:
        tasks = await list_test_tasks_by_report_date(db, today)
        lines: list[str] = []
        pending: list[tuple[QualityTestTask, list[QualityTestResult]]] = []
        for t in tasks:
            rows = await list_test_results(db, t.id)
            filled = sum(1 for r in rows if r.is_pass is not None)
            status_label = {
                "in_progress": "填报中",
                "pending_review": "待复核",
                "completed": "已完成",
            }.get(t.status, t.status)
            file_nos = await _task_doc_file_nos(db, t)
            sop_suffix = f"｜标准文件：{'、'.join(file_nos)}" if file_nos else ""
            lines.append(
                f"- {t.product_name} 批号 {t.batch_number}（{t.specification or '-'}）"
                f"｜{status_label} {filled}/{len(rows)}{sop_suffix}\n"
                f"  {_frontend_task_link(str(t.id))}"
            )
            if t.status == "in_progress":
                pending.append((t, rows))
        # 待复核任务（不限出报日期）：堆积提醒专员进系统审核
        review_items, _ = await list_test_tasks(
            db, product_name=None, status="pending_review", page=1, page_size=200
        )
        review_lines = [
            f"- {t.product_name} 批号 {t.batch_number}" + (
                f"（出报日期 {t.report_date}）" if t.report_date else ""
            )
            + f"\n  {_frontend_task_link(str(t.id))}"
            for t in review_items
        ]
        # 明日出报预告
        tomorrow = (_app_today() + timedelta(days=1)).isoformat()
        tomorrow_items = await list_test_tasks_by_report_date(db, tomorrow)
        tomorrow_lines = [
            f"- {t.product_name} 批号 {t.batch_number}｜"
            f"{'填报中' if t.status == 'in_progress' else {'pending_review': '待复核', 'completed': '已完成'}.get(t.status, t.status)}"
            for t in tomorrow_items
            if t.status != "void"
        ]
    if not lines and not review_lines and not tomorrow_lines:
        return
    blocks: list[str] = []
    if lines:
        blocks.append(f"今日出报任务（{today}）：\n" + "\n".join(lines))
    if review_lines:
        blocks.append(f"待复核任务（{len(review_lines)} 项，请专员进系统审核）：\n" + "\n".join(review_lines))
    if tomorrow_lines:
        blocks.append(f"明日出报预告（{tomorrow}）：\n" + "\n".join(tomorrow_lines))
    text = "\n\n".join(blocks)
    for chat_id in QUALITY_FEISHU_CHAT_IDS:
        try:
            await send_chat_text(chat_id, text)
        except Exception:
            logger.exception("飞书早报发送失败: %s", chat_id)
    # 填报中的任务：与「出报日期=今天」的即时推送一致，下发提醒+填报卡片
    from app.modules.quality.feishu.fill_service import push_task_reminder

    for t, rows in pending:
        await push_task_reminder(t, rows)


async def _push_afternoon_reminder() -> None:
    """午后催办：今日出报但仍未完成（填报中/待复核）的任务再提醒一次。"""
    from app.core.database import async_session_factory
    from app.modules.quality.feishu.client import (
        QUALITY_FEISHU_CHAT_IDS,
        feishu_configured,
    )
    from app.modules.quality.feishu.message import send_chat_text
    from app.modules.quality.repository import (
        list_test_results,
        list_test_tasks_by_report_date,
    )

    if not feishu_configured() or not QUALITY_FEISHU_CHAT_IDS:
        return
    today = _app_today().isoformat()
    if not await _mark_pushed(f"afternoon:{today}"):
        logger.info("午后催办今日已推送，跳过（幂等标记）")
        return
    from app.modules.quality.feishu.fill_service import (
        _frontend_task_link,
        _task_doc_file_nos,
    )

    async with async_session_factory() as db:
        tasks = await list_test_tasks_by_report_date(db, today)
        lines: list[str] = []
        for t in tasks:
            if t.status == "completed":
                continue
            rows = await list_test_results(db, t.id)
            filled = sum(1 for r in rows if r.is_pass is not None)
            status_label = {"in_progress": "填报中", "pending_review": "待复核"}.get(t.status, t.status)
            file_nos = await _task_doc_file_nos(db, t)
            sop_suffix = f"｜标准文件：{'、'.join(file_nos)}" if file_nos else ""
            lines.append(
                f"- {t.product_name} 批号 {t.batch_number}｜{status_label} {filled}/{len(rows)}{sop_suffix}\n"
                f"  {_frontend_task_link(str(t.id))}"
            )
    if not lines:
        return
    text = f"出报催办（{today}）：以下任务尚未完成，请抓紧处理\n" + "\n".join(lines)
    for chat_id in QUALITY_FEISHU_CHAT_IDS:
        try:
            await send_chat_text(chat_id, text)
        except Exception:
            logger.exception("飞书催办发送失败: %s", chat_id)




async def _push_material_alerts() -> None:
    """物料效期预警 + 采购建议推送（每日 08:15，独立幂等标记）。"""
    from app.core.database import async_session_factory
    from app.modules.quality.feishu.client import (
        QUALITY_FEISHU_CHAT_IDS,
        feishu_configured,
    )
    from app.modules.quality.feishu.message import send_chat_text
    from app.modules.quality.repository import (
        generate_env_plans,
        lab_expiry_alerts,
        list_env_plans,
        list_env_records,
        list_inspection_plans,
        material_expiry_alerts,
        retained_destroy_alerts,
        supplier_qual_alerts,
    )
    from app.modules.quality.service.material_containers import MaterialContainerService

    if not feishu_configured() or not QUALITY_FEISHU_CHAT_IDS:
        return
    today = _app_today().isoformat()
    if not await _mark_pushed(f"material-alerts:{today}"):
        logger.info("物料提醒今日已推送，跳过（幂等标记）")
        return
    async with async_session_factory() as db:
        alerts = await material_expiry_alerts(db)
        suggestions = await MaterialContainerService.purchase_suggestions(db)
        supplier_alerts = await supplier_qual_alerts(db)
        lab_alerts = await lab_expiry_alerts(db)
        retained_alerts = await retained_destroy_alerts(db)
        env_open = await list_env_records(db, judge="action", handle_status="open")
        await generate_env_plans(db, today)
        env_plans = await list_env_plans(db, today)
        today_plans = await list_inspection_plans(db, date_str=_app_today().isoformat())
    blocks: list[str] = []
    if env_plans:
        type_label = {"settle": "沉降菌", "float": "浮游菌", "particle": "悬浮粒子", "temp_humidity": "温湿度", "pressure": "压差"}
        pending = [x for x in env_plans if not x["completed"]]
        if pending:
            lines = [
                f"- {x['room']} {x['point_no']}（{type_label.get(x['monitor_type'], x['monitor_type'])}）"
                for x in pending
            ]
            blocks.append(
                f"环境监测今日计划（应测 {len(env_plans)} 个点位，已完成 {len(env_plans) - len(pending)}，未完成 {len(pending)}）：\n"
                + "\n".join(lines)
                + "\n完成请飞书填报：环境 点位 P001 值 5"
            )
    if env_open:
        lines = [
            f"- {r['room']} {r['point_no']} {r['record_date']} 结果 {r['result_value']}（行动限 {r['action_limit']}）"
            for r in env_open
        ]
        blocks.append(f"环境超行动限未处理（{len(env_open)} 项，请到环境监测页标记处理并留说明）：\n" + "\n".join(lines))
    if retained_alerts:
        lines = []
        for a in retained_alerts:
            tail = "（已到期未销毁，请尽快安排销毁）" if a["expired"] else "（30 天内到期，请安排销毁计划）"
            lines.append(
                f"- {a['sample_name']} 批号 {a['batch_no']}：销毁到期 {a['destroy_due_date']}"
                + (f"｜位置 {a['location']}" if a["location"] else "")
                + tail
            )
        blocks.append("留样销毁提醒（双人确认销毁后请到留样台账登记）：\n" + "\n".join(lines))
    if supplier_alerts:
        lines = [
            f"- {s['name']}（{s['code']}）：资质效期 {s['qual_expiry_date']}"
            + ("（已过期，建议暂停采购并重新审计）" if s["expired"] else "（临期，建议联系供应商更新资质）")
            for s in supplier_alerts
        ]
        blocks.append("供应商资质提醒：\n" + "\n".join(lines))
    if alerts:
        lines = []
        for a in alerts:
            parts = []
            if a["expired"]:
                parts.append(f"已过期 {a['expired']} 瓶（建议：隔离并申请复验/报废处置）")
            if a["near"]:
                parts.append(f"临效期 {a['near']} 瓶（最早 {a['earliest']}，建议：优先领用或申请复验）")
            lines.append(f"- {a['material_name']}（{a['material_code']}）：{'，'.join(parts)}")
        blocks.append("物料效期提醒（在库/待验/已赋码）：\n" + "\n".join(lines))
    if suggestions:
        lines = [
            f"- {s['material_name']}（{s['material_code']}）：可用 {s['available']}，"
            f"安全库存 {s['min_stock']}，建议采购 {s['gap']} 瓶" + (
                f"｜供应商 {s['vendor_name']}" if s["vendor_name"] else ""
            )
            for s in suggestions
        ]
        blocks.append("采购建议（低于安全库存）：\n" + "\n".join(lines))
    if lab_alerts:
        type_label = {"reagent": "试剂", "reference_standard": "对照品", "titrant": "滴定液", "instrument": "仪器校验"}
        lines = []
        for a in lab_alerts:
            label = type_label.get(a["item_type"], a["item_type"])
            tail = "（已过期，禁止使用）" if a["expired"] else "（临期，请及时处理）"
            lines.append(f"- {label} {a['name']}：有效期 {a['expiry_date']}{tail}")
        blocks.append("试剂/仪器效期提醒（30 天内）：\n" + "\n".join(lines))
    if today_plans:
        pending = [p for p in today_plans if p.status == "pending"]
        if pending:
            lines = []
            for p in pending:
                batch = f"（批号 {p.batch_no}）" if p.batch_no else ""
                lines.append(f"- {p.department} {p.product_name}{batch} 计划请检 {p.plan_time[11:]}")
            blocks.append(f"今日请检计划（{len(pending)} 项，请相关车间及 QC 安排）：\n" + "\n".join(lines))
    if not blocks:
        return
    text = "\n\n".join(blocks)
    for chat_id in QUALITY_FEISHU_CHAT_IDS:
        try:
            await send_chat_text(chat_id, text)
        except Exception:
            logger.exception("物料提醒发送失败: %s", chat_id)


async def _push_stocktake_reminder() -> None:
    """每月 25 日 09:00 盘点提醒（复用幂等标记，key=stocktake:{月份}）。"""
    from app.modules.quality.feishu.client import (
        QUALITY_FEISHU_CHAT_IDS,
        feishu_configured,
    )
    from app.modules.quality.feishu.message import send_chat_text

    if not feishu_configured() or not QUALITY_FEISHU_CHAT_IDS:
        return
    month = _app_today().strftime("%Y-%m")
    if not await _mark_pushed(f"stocktake:{month}"):
        logger.info("本月盘点提醒已推送，跳过（幂等标记）")
        return
    text = "本月库存盘点提醒：请到「扫码操作台」选择盘点模式，按盘点单扫码核对库存（系统在库=待验+合格）。盘点完成后差异清单可导出 Excel 归档。"
    for chat_id in QUALITY_FEISHU_CHAT_IDS:
        try:
            await send_chat_text(chat_id, text)
        except Exception:
            logger.exception("盘点提醒发送失败: %s", chat_id)
