"""驾驶舱/图卡缓存后台预热（2026-11-02 性能修复 P1）。

问题：总览/风险分区图卡的数据全是 Bitable/3.x 平台实时直读，冷缓存用户
打开页面要等 10~40s；既有域级 60s TTL 缓存只在「有人访问后」存在，挡不住
「每天第一次打开」。

方案：调度引擎常驻 interval 任务定期 force 刷新三处结果缓存——
1. goals 标准核查页（最重的一路：strict 全量直读 + 指标计算）；
2. build_overview（goals 已热后，其余域并行采集各自回填域级缓存）；
3. pins 当日图卡（八路口径聚合）。

用户请求全部命中热缓存；预热失败仅记日志（缓存过期后用户现算，行为同修复前）。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def run_dashboard_warmup_once() -> str:
    """单轮预热：goals 页 → overview → pins。返回 summarised 状态。"""

    outcomes: list[str] = []

    # 1) goals 标准核查页：force 重算（strict 直读不吃域级缓存，必须自己刷）
    try:
        from app.modules.safety.service.standard_check.page import (
            build_standard_check_page,
        )

        data = await build_standard_check_page(force=True)
        outcomes.append(f"goals={data.get('status')}")
    except Exception as exc:  # noqa: BLE001 预热失败不影响正确性
        logger.warning("goals 页预热失败: %r", exc)
        outcomes.append("goals=failed")

    # 2) 总览聚合：goals 命中刚刷的页缓存，其余域并行现采回填各自缓存
    try:
        from app.modules.safety.service.overview import build_overview

        data = await build_overview(force=True)
        outcomes.append(f"overview_errors={len(data.get('errors') or [])}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("overview 预热失败: %r", exc)
        outcomes.append("overview=failed")

    # 3) 风险分区图卡（当日口径）
    try:
        from app.modules.safety.service.facility_map.service import (
            bj_today,
            get_pins_cached,
        )

        data = await get_pins_cached(bj_today(), force=True)
        outcomes.append(f"pins_errors={len(data.get('errors') or [])}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("pins 预热失败: %r", exc)
        outcomes.append("pins=failed")

    summary = " ".join(outcomes)
    logger.info("驾驶舱缓存预热完成: %s", summary)
    return summary
