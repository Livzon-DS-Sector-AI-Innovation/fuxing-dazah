"""emergency_drill 直读只读冒烟（emergency-drill-direct Ticket 06）。

不经 service 双路径（无任何写/触发面挂载），只验证 reader 直拉与视图映射；
附一次附件 store 命中率抽样（路径推算与 handler 落盘一致的旁证）。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/smoke_emergency_drill_reader.py

退出码：0 成功；2 连接未配置；3 拉取失败。
"""

from __future__ import annotations

import asyncio
import sys
import time

sys.path.insert(0, ".")


async def main() -> int:
    from app.modules.safety import attachment_store
    from app.modules.safety.service.emergency_drill_direct.reader import open_reader

    t0 = time.perf_counter()
    views = await open_reader().fetch_all(strict=True)
    elapsed = time.perf_counter() - t0
    print(f"直读 {len(views)} 行，耗时 {elapsed:.2f}s")

    exec_n = sum(1 for v in views if v.execution_time is not None)
    done_n = sum(1 for v in views if v.status == "已完成")
    print(f"实施时间非空={exec_n} 已完成={done_n}"
          f"（探针基线 69/2，生产漂移属正常）")

    # 附件路径推算 × 统一存储命中（handler 持续下载 → 命中即证明命名一致）
    hit = miss = 0
    sample: list[str] = []
    for v in views:
        for attr in ("drill_plan_file", "plan_final_file", "signin_file",
                     "eval_form_file", "drill_record_file", "eval_ai_file"):
            for path in (getattr(v, attr) or []):
                if attachment_store.exists(path):
                    hit += 1
                else:
                    miss += 1
                    if len(sample) < 3:
                        sample.append(f"{attr}:{path}")
    print(f"附件 store 命中={hit} 未命中={miss}（未命中=事件未送达/未下载，404 降级）")
    for s in sample:
        print(f"  未命中样例: {s}")

    first = views[0]
    print(f"样例行: id={first.id} type={first.drill_type} dept={first.department}"
          f" plan_ref={first.plan_time_ref} exec={first.execution_time}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as exc:  # noqa: BLE001
        print(f"[x] {exc}")
        sys.exit(3)
