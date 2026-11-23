"""smoke_hardware_approval_instance.py — 五金库申领→飞书审批表单真机冒烟。

用途：验证系统代发起的「福兴电子领/退料单审批」表单与定义完全对齐（控件 id /
类型 / 值形态），并立刻撤回测试实例，避免审批人处理。

⚠️ 会真实创建审批实例（审批人收到一条审批通知，随即撤回），**默认 dry-run**：
    backend 下：
      .venv/bin/python -m scripts.smoke_hardware_approval_instance \
          --material-name "ABS三通" --spec "dn25*2.8mm S6.3 GB/T 20207.1-2006" \
          --need-qty 1 --available 2 --starter-user-id xukangfu
      # 确认表单 JSON 后再真发 + 立即撤回：
      .venv/bin/python -m scripts.smoke_hardware_approval_instance ... --confirm --cancel

冒烟通过判据：create 返回 instance_code，detail 能读回同一表单（六个子控件值一致）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.modules.warehouse.hardware.approval_channel import (  # noqa: E402
    build_platform_form,
)


def _form(args: argparse.Namespace) -> list[dict[str, Any]]:
    return build_platform_form(
        [
            {
                "category": args.category,
                "material_name": args.material_name,
                "spec": args.spec,
                "unit": args.unit,
                "need_qty": args.need_qty,
                "available": args.available,
            }
        ]
    )


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    app_id = settings.WAREHOUSE_FEISHU_APP_ID
    app_secret = settings.WAREHOUSE_FEISHU_APP_SECRET
    approval_code = (settings.HARDWARE_APPROVAL_CODE or "").strip()
    if not (app_id and app_secret and approval_code):
        print("✗ 凭证/定义未配置（WAREHOUSE_FEISHU_APP_ID/SECRET、HARDWARE_APPROVAL_CODE）")
        return 2

    form = _form(args)
    print("approval_code:", approval_code)
    print("starter user_id:", args.starter_user_id)
    print("form:")
    print(json.dumps(form, ensure_ascii=False, indent=1))

    if not args.confirm:
        print("\n[DRY-RUN] 未创建实例；加 --confirm 真发（会通知审批人，配 --cancel 立即撤回）")
        return 0

    from app.platform.integrations.feishu.approval import (
        cancel_instance,
        create_instance,
        get_instance,
    )

    instance_code = await create_instance(
        approval_code,
        args.starter_user_id,
        form,
        app_id=app_id,
        app_secret=app_secret,
    )
    print("✓ 实例已创建:", instance_code)

    inst = await get_instance(instance_code, app_id=app_id, app_secret=app_secret)
    readback = inst.get("form") or []
    print("读回控件:", json.dumps(readback, ensure_ascii=False))

    if args.cancel:
        ok = await cancel_instance(
            approval_code, instance_code, args.starter_user_id,
            app_id=app_id, app_secret=app_secret,
        )
        print("撤回:", "✓" if ok else "✗（定义未开「允许撤销审批」）")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="五金库申领审批表单真机冒烟")
    p.add_argument("--material-name", required=True)
    p.add_argument("--spec", default="")
    p.add_argument("--category", default="")
    p.add_argument("--unit", default="个")
    p.add_argument("--need-qty", type=float, default=1)
    p.add_argument("--available", type=float, default=1)
    p.add_argument("--starter-user-id", required=True, help="发起人飞书 user_id（如 xukangfu）")
    p.add_argument("--confirm", action="store_true", help="真创建实例")
    p.add_argument("--cancel", action="store_true", help="创建后立即撤回")
    return asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
