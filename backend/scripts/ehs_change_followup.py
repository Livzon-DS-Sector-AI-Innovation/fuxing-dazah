"""EHS 变更周度督办命令行：预演 / 真发周五一轮 / 出周一总结。

用法（backend 目录下）：
    .venv/bin/python -m scripts.ehs_change_followup dry-run      # 预演（不发送不落库不投格）
    .venv/bin/python -m scripts.ehs_change_followup friday       # 真发周五一轮（需 --confirm）
    .venv/bin/python -m scripts.ehs_change_followup monday       # 出周一总结（需 --confirm）
    .venv/bin/python -m scripts.ehs_change_followup monday --dry-run  # 总结预演

真机验收流程（DESIGN §11）：先置灰度收件人 SAFETY_EHS_CHANGE_FOLLOWUP_GRAY_RECIPIENT
（app_config，安全应用作用域 open_id），再 friday --confirm——所有卡只发灰度收件人；
脚本不受总闸约束（总闸管的是调度器补跑，验收全程保持关）。

周五幂等：重跑只补发未送达的卡（dispatch.send_status 锚）；有失败上抛非零退出。
周一幂等：同一轮不重投（round.status=summarized 锚）。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.safety.service.ehs_change_followup import (  # noqa: E402
    service as ecf_service,
)


async def _main() -> int:
    parser = argparse.ArgumentParser(description="EHS 变更周度督办")
    parser.add_argument(
        "command", choices=["dry-run", "friday", "monday"],
        help="dry-run=周五预演；friday=真发周五一轮；monday=周一总结",
    )
    parser.add_argument("--confirm", action="store_true", help="真发确认（friday/monday 必带）")
    parser.add_argument("--dry-run", action="store_true", help="monday 总结预演（不落库不投格）")
    args = parser.parse_args()

    if args.command == "dry-run":
        stats = await ecf_service.run_friday_round(dry_run=True)
        print(f"\n周五预演统计: {stats}")
        return 0

    if not args.confirm:
        print("真发命令需带 --confirm（先置灰度收件人再验，见模块 docstring）")
        return 2

    if args.command == "friday":
        stats = await ecf_service.run_friday_round()
        print(f"周五一轮完成: {stats}")
        return 0

    stats = await ecf_service.run_monday_summary(dry_run=args.dry_run)
    print(f"周一总结完成: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
