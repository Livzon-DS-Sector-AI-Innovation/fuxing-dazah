"""在飞书消防「火灾报警信息」表上确保 4 个 AI 列存在（幂等脚本）。

位置与用途见 .scratch/fire-alarm-direct/spec.md「建列脚本」。

用法（在后端目录下执行）：

    .venv/Scripts/python.exe scripts/tmp/ensure_fire_alarm_ai_fields.py
    .venv/Scripts/python.exe scripts/tmp/ensure_fire_alarm_ai_fields.py --apply

安全约束（黄色操作：修改生产多维表格结构）：

- 默认即 dry-run：只 list_fields 查现状并打印将新建的列，不调用任何写接口；
- 必须显式传 --apply，且 dry-run 输出经人工确认后才执行写入；
- 幂等：4 列均已存在且与契约一致则跳过，不重复建列、不报错；
- 已存在但类型/选项与契约不一致时不自动改，打印差异并以 5 退出；
- 建列前用 list_fields 拉全量字段名核对，不依赖 search 的字段返回值。

退出码：0 成功（新建 / 已存在跳过）；1 异常；2 连接未配置或停用；
        3 读字段失败；4 建列失败；5 与契约不一致（需人工处理）。

Ticket 02 收敛：幂等判断与建列调用全部转发 bitable_direct.writer.ensure_field；
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
from app.modules.safety.service.fire_alarm import contract  # noqa: E402


def _field_summary(field: dict[str, Any] | None) -> str:
    if not field:
        return "无返回字段信息"
    field_id = field.get("field_id") or "-"
    field_type = field.get("type") or "-"
    option_names = bd_writer.extract_option_names(field.get("property"))
    suffix = f" options={option_names}" if option_names else ""
    return f"field_id={field_id} type={field_type}{suffix}"


async def ensure(*, dry_run: bool) -> int:
    conn = store.get_connection("fire_alarm", "alarm")
    if conn is None or not conn.enabled:
        print("[x] 消防报警 Bitable 连接未配置或已停用（fire_alarm/alarm），中止")
        return 2
    print(
        f"[i] 目标表: {conn.domain}/{conn.kind} status={conn.status} "
        f"app_token={conn.app_token} table_id={conn.table_id}"
    )

    try:
        client = bd_reader.resolve_client("fire_alarm", "alarm")
    except BitableConfigError:
        print("[x] 消防报警 Bitable 连接未配置或已停用（fire_alarm/alarm），中止")
        return 2

    fields = await client.list_fields()
    if not fields:
        print("[x] list_fields 返回空，疑似接口失败；拒绝在现状未知时建列，中止")
        return 3
    print(f"[i] 当前字段数: {len(fields)}")

    exit_code = 0
    specs = contract.build_field_specs()
    for spec in specs:
        result = await bd_writer.ensure_field(client, spec, apply=not dry_run)
        if result.status == "exists":
            print(f"[=] 列已存在，跳过: {spec.name} {_field_summary(result.field)}")
            continue
        if result.status == "would_create":
            print(f"[+] 待新建列: {bd_writer.describe_spec(spec)}")
            continue
        if result.status == "created":
            print(f"[+] 建列成功: {spec.name} {_field_summary(result.field)}")
            if not bd_writer.field_matches(result.field or {}, spec):
                print("[!] 警告：创建结果与契约不一致，请人工核对飞书表格")
                exit_code = 5
            continue
        if result.status == "conflict":
            print(f"[x] 列已存在但与契约不一致，不自动修改: {spec.name}")
            print(f"    当前: {_field_summary(result.field)}")
            print(f"    期望: {bd_writer.describe_spec(spec)}")
            exit_code = 5
            continue
        # failed
        print(f"[x] 建列失败: {spec.name}:{result.message}")
        if "list_fields" in result.message:
            exit_code = 3
        else:
            exit_code = 4

    if dry_run and exit_code == 0:
        print("[i] dry-run：未调用 create_field；确认无误后加 --apply 执行")
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(
        description="确保消防报警表存在 4 个 AI 列（幂等）"
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
