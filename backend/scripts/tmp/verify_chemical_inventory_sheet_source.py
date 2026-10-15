"""双跑对账：sheet 视图 vs 旧链路 Bitable 总表（chemical-inventory-sheet-source P1-T5）。

同日两源全量直读出 diff 报告：行数 / 物料集合 / 按物料聚合总量差 / 部门分布对照，
供换源观察窗口期每日人工核对（部门口径差异属预期，逐条归类说明）。

运行：cd backend && PYTHONPATH=. uv run python scripts/tmp/verify_chemical_inventory_sheet_source.py
输出：stdout + .scratch/chemical-inventory-sheet-source/reports/sheet-vs-bitable-YYYYMMDD.md
退出码恒 0（报告工具，差异不构成失败；IO 失败退出码 1）。
"""

from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

REPORT_DIR = (
    Path(__file__).resolve().parents[3]
    / ".scratch" / "chemical-inventory-sheet-source" / "reports"
)


def _fmt(v: Decimal | None) -> str:
    if v is None:
        return "-"
    s = format(v.normalize(), "f")
    return s


async def fetch_sheet_views() -> list[Any]:
    from app.modules.safety.bitable_config.store import store
    from app.modules.safety.feishu.office_client import build_office_client
    from app.modules.safety.service.bitable_direct.errors import BitableConfigError
    from app.modules.safety.service.chemical_inventory_direct.sheet_reader import (
        SheetsInventoryReader,
    )

    conn = store.get_connection("chemical_inventory", "source_sheet")
    if conn is None or not conn.enabled:
        raise BitableConfigError("source_sheet 连接未配置或已停用")
    reader = SheetsInventoryReader(build_office_client(), conn.app_token)
    views = await reader.fetch_all(strict=True)
    print(
        f"[sheet] 读取完成：{len(views)} 行，revision={reader.last_revision}，"
        f"anomalies={reader.anomalies or '无'}",
        file=sys.stderr,
    )
    return views


async def fetch_bitable_views() -> list[Any]:
    from app.modules.safety.service.bitable_direct import reader as bd_reader
    from app.modules.safety.service.chemical_inventory_direct.reader import (
        InventoryBitableReader,
    )

    client = bd_reader.resolve_client("chemical_inventory", "inventory")
    views = await InventoryBitableReader(client).fetch_all(strict=True)
    print(f"[bitable] 读取完成：{len(views)} 行", file=sys.stderr)
    return views


def _by_material(views: list[Any]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for v in views:
        name = v.material_name or "?"
        totals[name] += v.total_quantity_t or Decimal("0")
    return dict(totals)


def _by_department(views: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for v in views:
        counts[v.department or "?"] += 1
    return dict(counts)


def build_report(sheet: list[Any], bitable: list[Any]) -> str:
    today = (datetime.now(UTC) + timedelta(hours=8)).date().isoformat()
    sheet_mats = _by_material(sheet)
    bit_mats = _by_material(bitable)
    only_sheet = sorted(set(sheet_mats) - set(bit_mats))
    only_bit = sorted(set(bit_mats) - set(sheet_mats))
    both = set(sheet_mats) & set(bit_mats)
    diffs = sorted(
        ((m, sheet_mats[m], bit_mats[m]) for m in both
         if sheet_mats[m] != bit_mats[m]),
        key=lambda x: -abs(x[1] - x[2]),
    )
    sheet_total = sum(sheet_mats.values(), Decimal("0"))
    bit_total = sum(bit_mats.values(), Decimal("0"))

    lines = [
        "# 危化品库存双跑对账报告（sheet vs bitable）",
        "",
        f"- 对账日期：{today}（北京时间）",
        f"- sheet 源：《危险品日报表》直读，{len(sheet)} 行，总量 {_fmt(sheet_total)} T",
        f"- bitable 源：旧链路总表直读，{len(bitable)} 行，总量 {_fmt(bit_total)} T",
        f"- 行数差：{len(sheet) - len(bitable):+d}；总量差：{_fmt(sheet_total - bit_total)} T",
        "",
        "## 一、物料集合差",
        "",
        f"### 仅在 sheet（{len(only_sheet)} 种）",
    ]
    lines += [f"- {m}：{_fmt(sheet_mats[m])} T" for m in only_sheet] or ["- 无"]
    lines += ["", f"### 仅在 bitable（{len(only_bit)} 种）"]
    lines += [f"- {m}：{_fmt(bit_mats[m])} T" for m in only_bit] or ["- 无"]
    lines += [
        "",
        "## 二、同物料总量差（按差值绝对量降序，全部 "
        f"{len(diffs)} 种）",
        "",
        "物料 | sheet(T) | bitable(T) | 差值(T)",
        "--- | --- | --- | ---",
    ]
    for m, s, b in diffs:
        lines.append(f"{m} | {_fmt(s)} | {_fmt(b)} | {_fmt(s - b)}")
    if not diffs:
        lines.append("（无同物料总量差异）")
    lines += ["", "## 三、部门枚举分布对照", "", "部门 | sheet 行数 | bitable 行数", "--- | --- | ---"]
    sheet_depts = _by_department(sheet)
    bit_depts = _by_department(bitable)
    for d in sorted(set(sheet_depts) | set(bit_depts)):
        lines.append(f"{d} | {sheet_depts.get(d, 0)} | {bit_depts.get(d, 0)}")
    lines += [
        "",
        "## 四、差异归类说明（预期口径，逐条人工核对用）",
        "",
        "1. **部门口径差异（预期）**：sheet 源部门=子表产品线（tikao/aimo/…），bitable 源",
        "   =职能部门（仓储部/提炼一部/…），两套枚举并存不映射——分布对照仅供定位，",
        "   不构成告警。",
        "2. **仅 sheet 物料（预期为主）**：新表按当前在用品类填报；逐条确认是否旧链路",
        "   已停用/合并的物料。",
        "3. **仅 bitable 物料（预期为主）**：旧总表「无删除、行消失留脏行」的已知脏行，",
        "   或车间新表漏报——超过 3 个工作日仍在仅 bitable 侧出现则升级人工核实。",
        "4. **同物料总量差**：核对数量单位（sheet 全列为 kg÷1000 归一；bitable 含 瓶/桶 等",
        "   不可比单位行）与浓度口径（乙醇按浓度多行）。",
        "",
        "---",
        "",
        f"生成：{datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')} · "
        "scripts/tmp/verify_chemical_inventory_sheet_source.py",
    ]
    return "\n".join(lines)


async def main() -> int:
    try:
        sheet = await fetch_sheet_views()
        bitable = await fetch_bitable_views()
    except Exception as exc:  # noqa: BLE001
        print(f"[error] 读取失败：{exc}", file=sys.stderr)
        return 1
    report = build_report(sheet, bitable)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    today = (datetime.now(UTC) + timedelta(hours=8)).date().isoformat()
    out = REPORT_DIR / f"sheet-vs-bitable-{today}.md"
    out.write_text(report)
    print(report)
    print(f"\n[ok] 报告已写入 {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
