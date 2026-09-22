"""本地 dev 库镜像回填（contractor-admission-direct Ticket 08，cert/key_risk_op 同口径）。

事件镜像只在生产跑，本地库为空——双路径比对前先回填。本域无全量同步服务方法
（镜像只靠事件喂），回填内联实现：直读全量视图 → mapped values → upsert_from_bitable
逐行落库。只读 Bitable、只写本地 dev 库；不触发 AI 审核（不走 service 查询路径，
无变更检测触发器）。

AI 态补齐：upsert 不带 ai_*（生产由审核流程写），本地回填后按 Bitable 3 列派生
补写 ai_review_status/ai_review_result（completed ⇔ AI审核结论非空）——模拟生产
「回写成功」态，使 Agent/列表比对有信号；生产若存在「已审核但回写失败」漂移，
比对会如实暴露（该差异方向为直读更正确）。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/backfill_contractor_mirror.py
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")


async def main() -> int:
    from app.core.database import async_session_factory
    from app.modules.safety.service.contractor_admission import (
        ContractorAdmissionService,
    )
    from app.modules.safety.service.contractor_admission_direct.reader import (
        open_reader,
    )
    from app.modules.safety.service.contractor_admission_direct.views import (
        mapped_field_keys,
    )

    views = await open_reader().fetch_all(strict=True)
    keys = mapped_field_keys()
    created = updated = ai_filled = 0
    async with async_session_factory() as db:
        service = ContractorAdmissionService(db)
        for view in views:
            values = {k: getattr(view, k) for k in keys}
            existing = await service.get_by_feishu_id(view.id)
            await service.upsert_from_bitable(values, view.id, "admission")
            completed = view.ai_review_status == "completed"
            if existing is None:
                created += 1
                target = await service.get_by_feishu_id(view.id)
            else:
                updated += 1
                target = existing
            if target is not None:
                # ai_* 不在 upsert 通道里（防御性跳过），按派生态**全量归一**
                # （只补不清会把本地残留的旧 completed 行带进比对，污染结果）
                await service.repo.update_contractor_admission(target.id, {
                    "ai_review_status": "completed" if completed else "none",
                    "ai_review_result": view.ai_review_result if completed else None,
                })
                if completed:
                    ai_filled += 1
    print(f"[OK] 回填完成: total={len(views)} created={created} updated={updated}"
          f" ai态归一completed={ai_filled}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

