# -*- coding: utf-8 -*-
"""列出 09-22 直读 34 条的原始字段键与候选状态列取值，寻找表格视图可能的过滤口径。只读。"""
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

TARGET = date(2026, 9, 22)


async def main() -> None:
    from app.modules.safety.service.special_op_direct.bitable_repo import fetch_day_views

    views = await fetch_day_views(TARGET)
    # 全部字段键
    keys: dict[str, int] = {}
    for v in views:
        for k in (v.raw or {}):
            keys[k] = keys.get(k, 0) + 1
    print("=== 字段键（出现次数） ===")
    for k, n in sorted(keys.items(), key=lambda x: -x[1]):
        print(f"{n:3}  {k}")

    # 候选状态类列的取值分布
    candidates = [
        "状态", "流程状态", "审批状态", "作业状态", "是否作废", "作废",
        "单据状态", "票证状态", "当前节点", "审批节点", "进展",
    ]
    print("\n=== 候选状态列取值 ===")
    for name in candidates:
        if not any(name in k for k in keys):
            continue
        dist: dict[str, int] = {}
        for v in views:
            val = str((v.raw or {}).get(name) or "<空>")
            dist[val] = dist.get(val, 0) + 1
        print(f"[{name}] {dist}")

    # 3 组疑似重复票的原始完整字段对比（节选）
    dup_rids = [
        ("货架制作安装", "recvvyFEMs8eUL", "recvvyFEMsXVTT"),
        ("破路面", "recvvQHkb117pS", "recvvQHkb1jqf7"),
        ("移动电加热控制器", "recvvQdi7CSJZy", "recvvQspTJhwA9"),
    ]
    by_id = {v.record_id: v for v in views}
    print("\n=== 疑似重复票字段对比 ===")
    for label, a, b in dup_rids:
        va, vb = by_id.get(a), by_id.get(b)
        if not va or not vb:
            print(f"[{label}] 缺记录 {a}/{b}")
            continue
        print(f"\n--- {label} ---")
        all_keys = sorted(set(va.raw) | set(vb.raw))
        for k in all_keys:
            x, y = va.raw.get(k), vb.raw.get(k)
            mark = "  " if x == y else "≠ "
            xs, ys = str(x), str(y)
            if xs == ys:
                print(f"{mark}{k}: {xs[:80]}")
            else:
                print(f"{mark}{k}: A={xs[:60]} | B={ys[:60]}")


asyncio.run(main())
