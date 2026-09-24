# -*- coding: utf-8 -*-
"""用 V3.6 新规则重跑今日特殊作业日报，并更新安全速递总卡的「特殊作业」格子。

- 走真实 daily.run 编排：直读 → 新规则判定 → 渲染 → AI 增强 → 速递总卡 upsert
- 推送器替换为内存记录器：不向特殊作业群重发整卡（08:00 已发过旧规则版），
  仅放行「安全速递总卡」upsert 分支（PATCH 今日已有总卡）
- 回写「日报风险等级（AI）」列关闭（不在本次动作范围）
- 结束后回读 Redis 格子 + 单独直读一遍统计新规则命中明细
"""
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

TARGET = date(2026, 9, 22)


class _RecordOnlyPusher:
    """只记录不发送：抑制整卡重发，放行安全速递总卡 upsert。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send(self, **kwargs):
        self.calls.append(kwargs)
        return "om_suppressed"


async def main() -> None:
    from app.modules.safety.service.special_op_direct import daily
    from app.modules.safety.service.special_op_direct.bitable_repo import (
        fetch_day_views,
    )

    pusher = _RecordOnlyPusher()
    result = await daily.run(
        TARGET, mode="today", push=True, pusher=pusher, writeback=False,
    )
    print("=== 新规则日报统计 ===")
    print("total:", result.total, "excluded:", result.excluded)
    print("high:", result.high_risk, "medium:", result.medium_risk, "low:", result.low_risk)
    print("速递 upsert 后 pusher 记录数(应为1,未真发):", len(pusher.calls))

    # 单独直读一遍，统计 V3.6 两条新规则的命中明细
    views = await fetch_day_views(TARGET)
    zone_hits = [
        v for v in views
        if "动火作业涉及高风险区域" in (v.daily_risk_reason or "")
    ]
    corrosive_hits = [
        v for v in views
        if "作业涉及腐蚀性管道" in (v.daily_risk_reason or "")
    ]
    print("=== V3.6 新规则命中 ===")
    for v in zone_hits:
        reason = (v.daily_risk_reason or "").split("; ")
        hit = next(r for r in reason if "动火作业涉及高风险区域" in r)
        print(f"[规则15] {v.department} {v.location} :: {hit}")
    for v in corrosive_hits:
        reason = (v.daily_risk_reason or "").split("; ")
        hit = next(r for r in reason if "作业涉及腐蚀性管道" in r)
        print(f"[规则16] {v.department} {v.location} :: {hit}")
    if not zone_hits and not corrosive_hits:
        print("（今日无记录命中两条新规则）")

    print("=== 日报全文 ===")
    print(result.markdown_report)

    # 回读 Redis 确认总卡格子已更新
    from app.core.redis import get_redis

    store = await get_redis()
    raw = await store.hget(f"safety:daily_digest:{TARGET.isoformat()}", "special_op")
    if raw is None:
        print("!! 速递格子未写入")
        return
    cell = json.loads(raw)
    print("=== 速递格子(回读) ===")
    print("stats:", cell.get("stats"))
    print("zone:", cell.get("zone"))
    print("detail 长度:", len(cell.get("detail", "")), "字符")
    print("detail 与本次日报一致:", cell.get("detail") == result.markdown_report)
    msg_id = await store.get(f"safety:daily_digest:card:{TARGET.isoformat()}")
    print("总卡 message_id:", msg_id, "（已 PATCH 原卡）" if msg_id else "（无原卡，已新建）")


asyncio.run(main())
