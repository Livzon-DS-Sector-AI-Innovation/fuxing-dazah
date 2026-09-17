"""在飞书「全厂特殊作业一览表」上确保「日报风险等级（AI）」单选列存在（幂等脚本）。

位置与用途见 .scratch/special-op-direct/spec.md「建列脚本」。

用法（在后端目录下执行）：

    .venv/Scripts/python.exe scripts/tmp/ensure_special_op_risk_field.py
    .venv/Scripts/python.exe scripts/tmp/ensure_special_op_risk_field.py --apply

安全约束（黄色操作：修改生产多维表格结构）：

- 默认即 dry-run：先 list_fields 查现状，只打印将新建的列名 / 类型 / 选项，不调用任何写接口；
- 必须显式传 --apply，且 dry-run 输出经人工确认后才执行写入；
- 幂等：列已存在则跳过并打印说明，不重复建列、不报错；
- 已存在但类型/选项与契约不一致时不自动改（同属黄色操作），打印差异并以 5 退出。

退出码：0 成功（新建 / 已存在跳过）；1 异常；2 连接未配置或停用；
        3 读字段失败；4 建列失败；5 与契约不一致（需人工处理）。

Ticket 06 收敛：幂等判断与建列调用全部转发 bitable_direct.writer.ensure_field；
本脚本只保留命令行参数、输出文案与退出码映射。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

sys.path.insert(0, ".")

from app.modules.safety.bitable_config.store import store  # noqa: E402
from app.modules.safety.service.bitable_direct import reader as bd_reader  # noqa: E402
from app.modules.safety.service.bitable_direct import writer as bd_writer  # noqa: E402
from app.modules.safety.service.bitable_direct.errors import (
    BitableConfigError,  # noqa: E402
)
from app.modules.safety.service.special_op_direct.contract import (  # noqa: E402
    FIELD_TYPE_SINGLE_SELECT,
    RISK_FIELD_NAME,
    RISK_FIELD_OPTIONS,
    create_field_property,
)


def _option_names(field: dict[str, Any]) -> list[str]:
    """字段属性里的选项名列表（顺序即展示顺序）。"""
    options = (field.get("property") or {}).get("options") or []
    return [str(o.get("name") or "") for o in options if isinstance(o, dict)]


def _summarize(field: dict[str, Any]) -> str:
    return (
        f"field_id={field.get('field_id')} type={field.get('type')} "
        f"options={_option_names(field)}"
    )


async def ensure(*, dry_run: bool) -> int:
    conn = store.get_connection("special_op", "daily")
    if conn is None or not conn.enabled:
        print("[x] 特殊作业 Bitable 连接未配置或已停用（special_op/daily），中止")
        return 2
    print(
        f"[i] 目标表: {conn.domain}/{conn.kind} status={conn.status} "
        f"app_token={conn.app_token} table_id={conn.table_id}"
    )

    try:
        client = bd_reader.resolve_client("special_op", "daily")
    except BitableConfigError:
        print("[x] 特殊作业 Bitable 连接未配置或已停用（special_op/daily），中止")
        return 2

    spec = bd_writer.FieldSpec(
        name=RISK_FIELD_NAME,
        field_type=FIELD_TYPE_SINGLE_SELECT,
        property_=create_field_property(),
    )
    result = await bd_writer.ensure_field(client, spec, apply=not dry_run)

    if result.status == "failed":
        if "list_fields" in result.message:
            print("[x] list_fields 返回空，疑似接口失败；拒绝在现状未知时建列，中止")
            return 3
        print("[x] create_field 失败（详见日志）")
        return 4

    if result.status == "exists":
        field = result.field or {}
        print(f"[=] 列已存在: {RISK_FIELD_NAME} {_summarize(field)}")
        print("[=] 类型与选项与契约一致，跳过（幂等：不重复建列）")
        return 0

    if result.status == "conflict":
        field = result.field or {}
        print(f"[=] 列已存在: {RISK_FIELD_NAME} {_summarize(field)}")
        print(
            f"[x] 与契约不一致：期望 type={FIELD_TYPE_SINGLE_SELECT} "
            f"options={list(RISK_FIELD_OPTIONS)}"
        )
        print("[x] 不自动修改（改列名/选项同属黄色操作），请人工确认后处理")
        return 5

    if result.status == "would_create":
        print(f"[+] 待新建列: {RISK_FIELD_NAME}")
        print(f"    类型: 单选（Bitable type={FIELD_TYPE_SINGLE_SELECT}）")
        print(f"    选项: {' / '.join(RISK_FIELD_OPTIONS)}（顺序即展示顺序）")
        print("[i] dry-run：未调用任何写接口；确认无误后加 --apply 执行")
        return 0

    # result.status == "created"
    field = result.field or {}
    print(f"[+] 建列成功: {RISK_FIELD_NAME} {_summarize(field)}")
    if result.field is None or not bd_writer.field_matches(result.field, spec):
        print("[!] 警告：创建结果与契约不一致，请人工核对飞书表格")
        return 5
    print("[+] 契约校验通过（单选 / 高风险 / 中风险 / 低风险）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="确保特殊作业表存在「日报风险等级（AI）」单选列（幂等）"
    )
    parser.add_argument(
        "--apply", action="store_true", help="真正建列（默认只做 dry-run 预览）"
    )
    args = parser.parse_args()
    try:
        return asyncio.run(ensure(dry_run=not args.apply))
    except Exception as exc:
        print(f"[x] 执行异常: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
