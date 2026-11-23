"""send_daily_report_previews.py — 生成 8 人 AI 日报预览并私发给评审人。

用法（backend 下）：
    .venv/bin/python -m scripts.send_daily_report_previews --to ou_xxx [--date 2026-11-19]

每人生成一张「AI预览版·待本人确认」卡（真实拉当日系统留痕；无留痕发骨架卡），
逐张 DM 给 --to 指定的评审人（open_id，safety 作用域）。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.safety.feishu.notification import send_user_card_dict  # noqa: E402
from app.modules.safety.service.daily_report import (  # noqa: E402
    config,
    preview,
    profiles,
)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", required=True, help="评审人 open_id（safety 作用域）")
    parser.add_argument("--date", default=None, help="日期键 YYYY-MM-DD，缺省=今天")
    parser.add_argument("--only", default=None, help="只跑指定姓名（调试用）")
    args = parser.parse_args()

    date_key = config.normalize_date_key(args.date)
    names = [args.only] if args.only else list(profiles.PROFILES)
    print(f"生成 {len(names)} 人预览 → {args.to}（{date_key}）")
    sent = 0
    for name in names:
        result = await preview.generate_preview(name, date_key)
        if not result.get("ok"):
            print(f"  [{name}] 失败: {result.get('error')}")
            continue
        degraded = "（降级骨架）" if result.get("degraded") else ""
        msg_id = await send_user_card_dict(args.to, result["card"])
        ok = bool(msg_id)
        sent += int(ok)
        print(f"  [{name}] 事实源命中 {result.get('facts_count', 0)} 条{degraded} → "
              f"{'已发' if ok else '发送失败'}")
        await asyncio.sleep(1.5)  # 轻限流
    print(f"完成：{sent}/{len(names)} 张已私发")


if __name__ == "__main__":
    asyncio.run(main())
