"""推送任务注册表 — 推送任务行的代码唯一事实源（只能改值不能新增任务）。

- scene 与内容生成器（push_center.generators）一一对应；
- trigger 二态：scheduled（频率驱动）/ event（业务钩子触发，无调度）；
- 目标缺省回落 target_env_var 指向的 env（逗号分隔多目标）。

schedule 结构（引擎到期判断用，store 校验同构）：
``{"type": "daily", "time": "08:00"}`` /
``{"type": "weekly", "weekday": 0, "time": "08:30"}``（0=周一）/
``{"type": "monthly", "day": 1, "time": "08:30"}`` /
``{"type": "yearly", "month": 1, "day": 1, "time": "08:30"}``（V3.0 分期D）/
``{"type": "interval", "seconds": 60}``；
日历型可带 ``"window_minutes"``（默认 60，窗口守卫防重启误触发与重复执行）。
本模块零副作用导入，migration 可直接引用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PushTaskInfo:
    """单个推送任务行（task_name 是稳定标识，DB 只能改值不能新增）。"""

    task_name: str
    scene: str
    label: str
    description: str
    trigger: str                                # scheduled | event
    default_schedule: dict[str, Any] | None     # None = 事件触发，无调度
    target_env_var: str                         # 目标缺省回落 env（空 = 无兜底）


_TASKS: tuple[PushTaskInfo, ...] = (
    PushTaskInfo(
        task_name="morning_report",
        scene="morning_report",
        label="晨报推送",
        description="每日 08:00 推送昨日出入库汇总、异常与低库存/临期 Top5（补 V2.0 欠账）",
        trigger="scheduled",
        default_schedule={"type": "daily", "time": "08:00"},
        target_env_var="WAREHOUSE_ALERT_CHAT_ID",
    ),
    PushTaskInfo(
        task_name="weekly_stock_report",
        scene="weekly_stock_report",
        label="周库存报表",
        description="每周一 08:30 推送近 7 天出入库汇总与库存概况",
        trigger="scheduled",
        default_schedule={"type": "weekly", "weekday": 0, "time": "08:30"},
        target_env_var="WAREHOUSE_ALERT_CHAT_ID",
    ),
    PushTaskInfo(
        task_name="monthly_report_push",
        scene="monthly_report_push",
        label="月报推送",
        description="每月 1 日 08:30 推送上月出入库月报摘要",
        trigger="scheduled",
        default_schedule={"type": "monthly", "day": 1, "time": "08:30"},
        target_env_var="WAREHOUSE_ALERT_CHAT_ID",
    ),
    PushTaskInfo(
        task_name="stale_lists",
        scene="stale_lists",
        label="超6月与不合格清单",
        description="每日 09:00 推送呆滞与不合格物料清单（附 LLM 解读，失败降级模板）",
        trigger="scheduled",
        default_schedule={"type": "daily", "time": "09:00"},
        target_env_var="WAREHOUSE_ALERT_CHAT_ID",
    ),
    PushTaskInfo(
        task_name="express_notify",
        scene="express_notify",
        label="快递发货通知",
        description="成品出库确认后自动推送发货通知卡（事件触发，无定时；Ticket 08 接入）",
        trigger="event",
        default_schedule=None,
        target_env_var="WAREHOUSE_ALERT_CHAT_ID",
    ),
    # ── V3.0 分期B（QC 请验放行闭环，设计 §4.1）──
    PushTaskInfo(
        task_name="arrival_inspection",
        scene="arrival_inspection",
        label="到货请验通知",
        description="原辅料入库登记确认后自动推 QC 群「到货请验」卡（事件触发，链路1）",
        trigger="event",
        default_schedule=None,
        target_env_var="WAREHOUSE_TEST_CHAT_ID",
    ),
    PushTaskInfo(
        task_name="qc_progress_alert",
        scene="qc_progress_alert",
        label="QC 进度超期提醒",
        description="QC 扫描发现未取样/未出报超期批号时推 QC 群提醒卡（事件触发，链路2）",
        trigger="event",
        default_schedule=None,
        target_env_var="WAREHOUSE_TEST_CHAT_ID",
    ),
    PushTaskInfo(
        task_name="release_notify",
        scene="release_notify",
        label="放行上架通知",
        description="QA 放行（含条件放行）后推仓库群「已放行可上架」卡（事件触发，链路3）",
        trigger="event",
        default_schedule=None,
        target_env_var="WAREHOUSE_TEST_CHAT_ID",
    ),
    # ── V3.0 分期C（领料 FIFO 与供应商名录，设计 §4.2/§4.3）──
    PushTaskInfo(
        task_name="supplier_mismatch_alert",
        scene="supplier_mismatch_alert",
        label="供应商不一致提醒",
        description="入库识别供应商与主数据不一致时推提醒卡（事件触发，AI 辅助核对口径）",
        trigger="event",
        default_schedule=None,
        target_env_var="WAREHOUSE_TEST_CHAT_ID",
    ),
    # ── V3.0 分期D（分析补全，设计 §4.4/§4.5/§4.8）──
    PushTaskInfo(
        task_name="finished_daily_summary",
        scene="finished_daily_summary",
        label="成品每日汇总",
        description="每日 08:15 推送昨日成品出入库汇总与近 90 天质量状态分布（§4.5 成品③）",
        trigger="scheduled",
        default_schedule={"type": "daily", "time": "08:15"},
        target_env_var="WAREHOUSE_TEST_CHAT_ID",
    ),
    PushTaskInfo(
        task_name="invoice_four_state",
        scene="invoice_four_state",
        label="开票四态推送",
        description="每日 08:45 推送当月开票/发货四态合计与发货未开票明细（§4.8⑥）",
        trigger="scheduled",
        default_schedule={"type": "daily", "time": "08:45"},
        target_env_var="WAREHOUSE_TEST_CHAT_ID",
    ),
    PushTaskInfo(
        task_name="finished_disposition_lists",
        scene="finished_disposition_lists",
        label="成品退货不合格清单",
        description="每日 09:15 推送成品退货/不合格/待处理清单（推送后挂处理方案确认门，§4.8④）",
        trigger="scheduled",
        default_schedule={"type": "daily", "time": "09:15"},
        target_env_var="WAREHOUSE_TEST_CHAT_ID",
    ),
    PushTaskInfo(
        task_name="shipment_analysis",
        scene="shipment_analysis",
        label="发货去向月度分析",
        description="每月 1 日 09:00 推送上月销售发货客户排名/环比/品名分布分析（§4.8⑤）",
        trigger="scheduled",
        default_schedule={"type": "monthly", "day": 1, "time": "09:00"},
        target_env_var="WAREHOUSE_TEST_CHAT_ID",
    ),
    PushTaskInfo(
        task_name="material_usage_compare",
        scene="material_usage_compare",
        label="物料用量对比报告",
        description="每月 1 日 09:30 推送上月物料实际用量与预期基准对比及合理化建议（§4.4⑥）",
        trigger="scheduled",
        default_schedule={"type": "monthly", "day": 1, "time": "09:30"},
        target_env_var="WAREHOUSE_TEST_CHAT_ID",
    ),
    PushTaskInfo(
        task_name="workshop_weekly_usage",
        scene="workshop_weekly_usage",
        label="车间周用量汇总",
        description="每周一 09:00 按领用部门推送近 7 天领料用量汇总（§4.4⑤ 简化版）",
        trigger="scheduled",
        default_schedule={"type": "weekly", "weekday": 0, "time": "09:00"},
        target_env_var="WAREHOUSE_TEST_CHAT_ID",
    ),
    PushTaskInfo(
        task_name="annual_report",
        scene="annual_report",
        label="年度报表推送",
        description="每年 1 月 1 日 08:30 推送上年度年报（原辅料出入库聚合+成品年度开票/发货，§4.5）",
        trigger="scheduled",
        default_schedule={"type": "yearly", "month": 1, "day": 1, "time": "08:30"},
        target_env_var="WAREHOUSE_TEST_CHAT_ID",
    ),
    # ── V3.0 二期 P1（总文档缺口补齐，2026-09-22）──
    PushTaskInfo(
        task_name="low_stock_alert",
        scene="low_stock_alert",
        label="低库存预警推送",
        description="每日 08:10 推送低于安全库存物料清单（本地镜像口径，与晨报低库存同源；总文档原辅料⑤）",
        trigger="scheduled",
        default_schedule={"type": "daily", "time": "08:10"},
        target_env_var="WAREHOUSE_TEST_CHAT_ID",
    ),
)

PUSH_REGISTRY: dict[str, PushTaskInfo] = {t.task_name: t for t in _TASKS}
assert len(PUSH_REGISTRY) == len(_TASKS), "推送任务注册表存在重复 task_name"


def get_task(task_name: str) -> PushTaskInfo:
    """未知任务抛 ValueError（消息以「未知任务」开头，404 语义）。"""
    info = PUSH_REGISTRY.get(task_name)
    if info is None:
        raise ValueError(f"未知任务: {task_name}")
    return info


def iter_tasks() -> tuple[PushTaskInfo, ...]:
    """遍历全部任务行，供 migration 播种 + 引擎遍历。"""
    return _TASKS
