"""仓储 Agent 4 个查询工具（S1 ticket 03，spec Implementation Decisions 5）。

纯 async 函数 + 注册表（``TOOLS`` 为 OpenAI tools schema、``TOOL_FUNCS``
为名字 → 协程映射；S3 套 MCP 壳时只动注册表外壳）。全部经 S0 的
``WarehouseBitableAdapter`` 真查测试版 Base，**工具内部分页：明细默认
前 10 条 + total**；任何异常包装为 ``{"error": ...}`` 返回给 LLM 自修复
重试，绝不向上抛出中断 Runner 循环。

值形态实测契约（base_scan 摸底 + S0 写契约）：
- 单选（select）读取返回字符串或数组（读写不对称），lookup 恒为数组；
- datetime / 日期 formula 读回毫秒时间戳（数字）或字符串，本模块统一
  规范化（``_cell_list`` / ``_cell_text`` / ``_cell_ms``）；
- user 字段读回 {"id", "name"} 或其数组。

过滤策略：datetime 范围用服务端 filter（records/search 原生支持，
isGreaterEqual/isLess + 毫秒时间戳）；关键词/单选/lookup/有效期用本地
过滤（拉取页内匹配，避免 select-contains / lookup-filter 的接口行为
不确定性）。拉取上限 3 页 × 500 条，超出在结果 note 里说明。
"""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.warehouse.agent.skills.registry import (
    SKILL_TOOL_FUNCS,
    SKILL_TOOLS_SCHEMA,
)
from app.modules.warehouse.agent.tools.memory import (
    MEMORY_TOOL_FUNCS,
    MEMORY_TOOLS_SCHEMA,
)
from app.modules.warehouse.agent.tools.office import (
    OFFICE_TOOL_FUNCS,
    OFFICE_TOOLS_SCHEMA,
)
from app.modules.warehouse.agent.tools.plan import (
    PLAN_TOOL_FUNCS,
    PLAN_TOOLS_SCHEMA,
)
from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter
from app.modules.warehouse.bitable_schema import WarehouseBitableError

logger = logging.getLogger(__name__)

# 分页/截断常量
DETAIL_LIMIT = 10  # 明细默认返回前 N 条（其余计进 total）
FETCH_PAGE_SIZE = 500  # records/search 单页条数（接口上限）
MAX_FETCH_PAGES = 3  # 最多拉 3 页（1500 条），超出在 note 说明
TOOL_RESULT_MAX_BYTES = 4096  # Runner 侧单条工具结果截断上限（对齐 spec 4KB）

QC_STATUSES = ("放行", "条件放行", "否决")  # QA放行 单选选项集（V1.0-5 契约）

# ── adapter 惰性单例（测试 monkeypatch 注入口：query._adapter = fake） ──

_adapter: WarehouseBitableAdapter | None = None


def get_adapter() -> WarehouseBitableAdapter:
    global _adapter
    if _adapter is None:
        _adapter = WarehouseBitableAdapter()
    return _adapter


# ── 单元格值规范化 ──
# 实测形态（records/search，测试版 Base）：
# - 直接标量：3700 / "是" / 1766937600000 / "硫酸"
# - 单选/lookup 计算列包裹：{"type": 3, "value": ["放行"]}
# - formula 包裹：{"type": 2, "value": [0]} / {"type": 5, "value": [ms]}
# - 富文本分段：{"text": "...", "type": "text"} 或其数组
# - user/人员：[{"id", "name", ...}]；关联：{"link_record_ids": ...}；附件：[{"name", ...}]


def _cell_list(value: Any) -> list[str]:
    """把单元格值数组化为文本列表（兼容以上全部形态）。"""
    if value is None:
        return []
    if isinstance(value, list):
        return [part for item in value for part in _cell_list(item)]
    if isinstance(value, dict):
        if "text" in value:  # 富文本分段
            return _cell_list(value.get("text"))
        if "value" in value:  # 类型包裹（formula/lookup）
            return _cell_list(value.get("value"))
        name = value.get("name")  # user/附件
        if name:
            return [str(name)]
        return []
    if isinstance(value, bool):
        return [str(value)]
    return [str(value)]


def _cell_text(value: Any) -> str:
    return "、".join(_cell_list(value))


def _unwrap(value: Any) -> Any:
    """递归取第一个标量（分段/包裹/数组展开）。"""
    if isinstance(value, list):
        return _unwrap(value[0]) if value else None
    if isinstance(value, dict):
        for key in ("text", "value", "name"):
            if key in value:
                return _unwrap(value[key])
        return None
    return value


def _cell_number(value: Any) -> float | None:
    scalar = _unwrap(value)
    if isinstance(scalar, bool) or scalar is None:
        return None
    if isinstance(scalar, (int, float)):
        return float(scalar)
    text = str(scalar).strip().replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _cell_ms(value: Any) -> int | None:
    """日期/日期 formula 值 → 毫秒时间戳；无法解析返回 None。"""
    scalar = _unwrap(value)
    if isinstance(scalar, bool) or scalar is None:
        return None
    if isinstance(scalar, (int, float)):
        return int(scalar)
    text = str(scalar).strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return int(
                datetime.strptime(text[: len(fmt) + 4], fmt)
                .replace(tzinfo=UTC)
                .timestamp()
                * 1000
            )
        except ValueError:
            continue
    return None


def _fmt_date(value: Any) -> str:
    """日期值 → 'YYYY-MM-DD' 文本（不可解析原样文本，空值空串）。"""
    ms = _cell_ms(value)
    if ms is not None:
        try:
            return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%d")
        except (OSError, OverflowError, ValueError):
            # Windows 对负/超界毫秒抛 OSError（如哨兵值 -2146377600000）→ 原样返回
            return str(_unwrap(value))
    return _cell_text(value)


def _fmt_qty(value: Any) -> str:
    """数量文本：整数去掉 .0 尾巴。"""
    num = _cell_number(value)
    if num is None:
        return _cell_text(value)
    return str(int(num)) if num == int(num) else str(num)


def _match_keyword(fields: dict[str, Any], names: list[str], keyword: str) -> bool:
    """keyword 模糊匹配：任一字段值（数组化后）包含关键词（不区分大小写）。"""
    needle = keyword.strip().lower()
    if not needle:
        return True
    for name in names:
        for part in _cell_list(fields.get(name)):
            if needle in part.lower():
                return True
    return False


def _date_range_ms(
    date_from: str | None, date_to: str | None
) -> tuple[int | None, int | None, str | None]:
    """date_from/date_to（YYYY-MM-DD）→ (lower_ms, upper_ms_exclusive, 错误)。

    from 含当天 00:00 起；to 为次日 00:00 前（含 to 当天全天）。
    本地过滤用（实测该 Base 对 datetime 字段的比较过滤返回 1254018）。
    """
    lower: int | None = None
    upper: int | None = None
    for arg, offset_days, is_lower in ((date_from, 0, True), (date_to, 1, False)):
        if not arg:
            continue
        try:
            base = datetime.strptime(arg.strip(), "%Y-%m-%d")
        except ValueError:
            return None, None, f"日期参数 {arg!r} 格式应为 YYYY-MM-DD"
        target = int(
            (base + timedelta(days=offset_days))
            .replace(tzinfo=UTC)
            .timestamp()
            * 1000
        )
        if is_lower:
            lower = target
        else:
            upper = target
    return lower, upper, None


def _in_date_range(fields: dict[str, Any], date_field: str, lower: int | None, upper: int | None) -> bool:
    """记录的日期字段是否落在 [lower, upper) 毫秒区间；无日期值视为不匹配。"""
    ms = _cell_ms(fields.get(date_field))
    if ms is None:
        return False
    if lower is not None and ms < lower:
        return False
    if upper is not None and ms >= upper:
        return False
    return True


async def _fetch_all(
    table_key: str,
    filter_json: dict[str, Any] | None,
    field_names: list[str],
    sort: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], int | None, bool]:
    """分页拉取记录（≤ MAX_FETCH_PAGES 页）。返回 (records, 服务端total, 是否截断)。"""
    records: list[dict[str, Any]] = []
    server_total: int | None = None
    page_token: str | None = None
    for _ in range(MAX_FETCH_PAGES):
        page = await get_adapter().search_records_page(
            table_key,
            filter_json=filter_json,
            field_names=field_names,
            limit=FETCH_PAGE_SIZE,
            page_token=page_token,
            sort=sort,
        )
        records.extend(page["records"])
        if page["total"] is not None:
            server_total = page["total"]
        page_token = page["page_token"]
        if not page_token:
            break
    return records, server_total, page_token is not None


def _pick(
    fields: dict[str, Any], mapping: list[tuple[str, Any]]
) -> dict[str, str]:
    """按 (输出键, 值格式化函数) 列表抽取记录字段，缺失字段输出空串。"""
    out: dict[str, str] = {}
    for key, formatter in mapping:
        out[key] = formatter(fields.get(key))
    return out


def _as_text(value: Any) -> str:
    return _cell_text(value)


def _truncation_note(truncated: bool) -> str:
    return (
        "数据量超过拉取上限（1500 条），统计可能不完整，建议加日期/关键词缩小范围。"
        if truncated
        else ""
    )


# ── 1. query_stock：物料库存明细总表 ──


async def query_stock(
    keyword: str | None = None,
    qc_status: str | None = None,
    expiring_days: int | None = None,
) -> dict[str, Any]:
    """查物料库存明细（material_stock）：按关键词/QA放行状态/临期天数过滤。"""
    field_names = [
        "物料名称", "物料批号", "厂家批号", "剩余数量", "单位",
        "贮存/槽车取样点", "QA放行", "入库日期", "有效期至/复验期至",
        "物料大类", "级别/型号",
    ]
    records, _server_total, truncated = await _fetch_all(
        "material_stock", None, field_names
    )

    matched: list[dict[str, Any]] = []
    unparseable_expiry = 0
    for row in records:
        fields = row["fields"]
        if keyword and not _match_keyword(
            fields, ["物料名称", "物料批号", "厂家批号"], keyword
        ):
            continue
        if qc_status:
            statuses = _cell_list(fields.get("QA放行"))  # lookup 列，读回数组
            if qc_status.strip() not in statuses:
                continue
        if expiring_days is not None and expiring_days > 0:
            ms = _cell_ms(fields.get("有效期至/复验期至"))  # formula 列
            if ms is None:
                unparseable_expiry += 1
                continue
            try:
                expiry = datetime.fromtimestamp(ms / 1000, tz=UTC).replace(tzinfo=None)
            except (OSError, OverflowError, ValueError):
                # Windows 对负/超界毫秒抛 OSError（哨兵值，如 -2146377600000）
                # ——与 _fmt_date 同款防御，按无法解析处理（ticket 08 复验期
                # 预警依赖本过滤，不能因个别脏数据中断查询）
                unparseable_expiry += 1
                continue
            deadline = datetime.now().replace(tzinfo=None) + timedelta(
                days=int(expiring_days)
            )
            if expiry > deadline:
                continue
        matched.append(row)

    detail = [
        {
            "物料名称": _as_text(f.get("物料名称")),
            "物料批号": _as_text(f.get("物料批号")),
            "剩余数量": _fmt_qty(f.get("剩余数量")),
            "单位": _as_text(f.get("单位")),
            "贮存位置": _as_text(f.get("贮存/槽车取样点")),
            "QA放行": _as_text(f.get("QA放行")),
            "入库日期": _fmt_date(f.get("入库日期")),
            "有效期至/复验期至": _fmt_date(f.get("有效期至/复验期至")),
            "物料大类": _as_text(f.get("物料大类")),
            "级别/型号": _as_text(f.get("级别/型号")),
        }
        for row in matched[:DETAIL_LIMIT]
        for f in [row["fields"]]
    ]

    notes = [n for n in [
        _truncation_note(truncated),
        f"{unparseable_expiry} 条记录的有效期无法解析、未纳入临期过滤"
        if unparseable_expiry else "",
        f"qc_status 仅支持 {'/'.join(QC_STATUSES)}" if qc_status else "",
    ] if n]
    return {
        "total": len(matched),
        "records": detail,
        "note": "；".join(notes),
    }


# ── 2. query_material：物料名称代码一览表（主数据） ──


async def query_material(keyword: str) -> dict[str, Any]:
    """查物料主数据（material_master）：按名称/代码/ERP名称模糊匹配。"""
    field_names = [
        "代码", "物料名称", "级别", "飞书规格", "物料大类", "单位换算",
        "生产商", "免检物料", "复验期", "有效期", "包装规格", "物料细分类",
        "ERP名称", "使用品种",
    ]
    records, _server_total, truncated = await _fetch_all(
        "material_master", None, field_names
    )
    matched = [
        row for row in records
        if _match_keyword(
            row["fields"], ["物料名称", "代码", "ERP名称", "使用品种"], keyword
        )
    ]
    detail = [
        {
            "代码": _as_text(f.get("代码")),
            "物料名称": _as_text(f.get("物料名称")),
            "级别": _as_text(f.get("级别")),
            "规格": _as_text(f.get("飞书规格")),
            "物料大类": _as_text(f.get("物料大类")),
            "单位换算": _as_text(f.get("单位换算")),
            "生产商": _as_text(f.get("生产商")),
            "免检物料": _as_text(f.get("免检物料")),
            "复验期": _fmt_qty(f.get("复验期")),
            "包装规格": _as_text(f.get("包装规格")),
        }
        for row in matched[:DETAIL_LIMIT]
        for f in [row["fields"]]
    ]
    notes = [n for n in [
        _truncation_note(truncated),
        "一览表无「单位」列，单位信息见「单位换算」列",
    ] if n]
    return {"total": len(matched), "records": detail, "note": "；".join(notes)}


# ── 3. query_movements：物料入库/出库总账（按物料聚合 + 明细） ──


async def query_movements(
    material: str | None = None,
    direction: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """查入/出库总账（material_receipt / material_outbound），按物料聚合汇总。

    direction: inbound=入库 / outbound=出库 / both=两者（默认）。
    date_from/date_to: 'YYYY-MM-DD'，按入库日期/领用日期过滤。
    """
    dir_norm = (direction or "both").strip().lower()
    if dir_norm not in ("inbound", "outbound", "both"):
        return {"error": f"direction 仅支持 inbound/outbound/both，收到 {direction!r}"}

    plans: list[tuple[str, str, str, list[str]]] = []
    # (表key, 方向中文, 日期字段, 明细字段)
    if dir_norm in ("inbound", "both"):
        plans.append((
            "material_receipt", "入库", "入库日期",
            ["物料名称", "物料批号", "入库数量", "单位", "入库日期",
             "QA放行", "贮存/槽车取样点"],
        ))
    if dir_norm in ("outbound", "both"):
        plans.append((
            "material_outbound", "出库", "领用日期",
            ["物料名称", "物料批号", "出库数量", "单位", "领用日期",
             "领用部门", "领用类型"],
        ))

    result: dict[str, Any] = {"total": 0, "summary": [], "records": []}
    all_notes: list[str] = []
    for table_key, dir_cn, date_field, field_names in plans:
        lower, upper, err = _date_range_ms(date_from, date_to)
        if err:
            return {"error": err}
        # 日期倒序拉最近数据（datetime 比较过滤实测不可用，日期范围本地过滤）
        records, _server_total, truncated = await _fetch_all(
            table_key, None, field_names,
            sort=[{"field_name": date_field, "desc": True}],
        )
        if truncated:
            all_notes.append(f"{dir_cn}数据超过拉取上限（1500 条），仅统计最近记录")
        matched = [
            row for row in records
            if (not material or _match_keyword(row["fields"], ["物料名称"], material))
            and (lower is None and upper is None
                 or _in_date_range(row["fields"], date_field, lower, upper))
        ]
        # 按物料名称聚合数量（数量字段随方向不同）
        qty_key = "入库数量" if dir_cn == "入库" else "出库数量"
        agg: dict[tuple[str, str], float] = {}
        for row in matched:
            fields = row["fields"]
            num = _cell_number(fields.get(qty_key))
            if num is None:
                continue
            unit = _as_text(fields.get("单位")) or "-"
            key = (_as_text(fields.get("物料名称")) or "-", unit)
            agg[key] = agg.get(key, 0.0) + num
        summary = [
            {"物料名称": name, "数量": _fmt_qty(q), "单位": unit}
            for (name, unit), q in sorted(
                agg.items(), key=lambda kv: kv[1], reverse=True
            )
        ]
        detail = [
            {
                "物料名称": _as_text(f.get("物料名称")),
                "物料批号": _as_text(f.get("物料批号")),
                qty_key: _fmt_qty(f.get(qty_key)),
                "单位": _as_text(f.get("单位")),
                date_field: _fmt_date(f.get(date_field)),
                "贮存/槽车取样点": _as_text(f.get("贮存/槽车取样点"))
                if dir_cn == "入库"
                else "",
                "QA放行": _as_text(f.get("QA放行")) if dir_cn == "入库" else "",
                "领用部门": _as_text(f.get("领用部门")) if dir_cn == "出库" else "",
                "领用类型": _as_text(f.get("领用类型")) if dir_cn == "出库" else "",
            }
            for row in matched[:DETAIL_LIMIT]
            for f in [row["fields"]]
        ]
        # 去掉方向不适用产生的空键，保持明细紧凑
        detail = [
            {k: v for k, v in item.items() if v != "" or k in ("物料名称", qty_key)}
            for item in detail
        ]
        result["total"] += len(matched)
        result["summary"].append({f"{dir_cn}汇总": summary})
        result["records"].append({f"{dir_cn}明细": detail})

    if all_notes:
        result["note"] = "；".join(all_notes)
    return result


# ── 4. query_report：呆料/不合格汇总 ──
# dead 数据源偏差（实测）：ticket 给的呆料汇总坐标 tbl3AhExWLtRww0g 是工作版
# 快照 id；测试版 Base 该用途表（tblLxUJN0rtW49zT）字段结构为月度出库汇总
# （无 产生呆料数量/处理方式/处理进度/使用部门/登记日期）。因此 dead 改查
# 入库总账「呆料判断=是」的批次清单（批次级呆料，字段齐全且真实可用）。

DEAD_RECEIPT_FILTER: dict[str, Any] = {
    "conjunction": "and",
    "conditions": [{"field_name": "呆料判断", "operator": "is", "value": ["是"]}],
}

REPORT_UNQUALIFIED_FIELDS = [
    "物料名称", "不合格项目", "处理方式", "到货日期", "登记人",
    "计量单位", "物料大类",
]


async def query_report(report_type: str = "dead") -> dict[str, Any]:
    """查汇总报表清单：dead=呆料批次清单 / unqualified=不合格物料（前10条+total）。"""
    key = (report_type or "dead").strip().lower()
    if key not in ("dead", "unqualified"):
        return {
            "error": f"report_type 仅支持 dead/unqualified，收到 {report_type!r}"
        }

    if key == "dead":
        records, _server_total, truncated = await _fetch_all(
            "material_receipt",
            DEAD_RECEIPT_FILTER,
            ["物料名称", "物料批号", "入库数量", "单位", "入库日期",
             "贮存/槽车取样点", "使用部门（槽车）"],
        )
        detail = [
            {
                "物料名称": _as_text(f.get("物料名称")),
                "物料批号": _as_text(f.get("物料批号")),
                "呆料产生数量（入库数量）": _fmt_qty(f.get("入库数量")),
                "单位": _as_text(f.get("单位")),
                "入库日期": _fmt_date(f.get("入库日期")),
                "贮存位置": _as_text(f.get("贮存/槽车取样点")),
                "使用部门": _as_text(f.get("使用部门（槽车）")),
            }
            for row in records[:DETAIL_LIMIT]
            for f in [row["fields"]]
        ]
        return {
            "report_type": "dead",
            "report_name": "呆料批次清单（入库总账·呆料判断=是）",
            "total": len(records),
            "records": detail,
            "note": _truncation_note(truncated),
        }

    records, _server_total, truncated = await _fetch_all(
        "unqualified_stock", None, REPORT_UNQUALIFIED_FIELDS
    )
    detail = [
        {
            "物料名称": _as_text(f.get("物料名称")),
            "不合格项目": _as_text(f.get("不合格项目")),
            "处理方式": _as_text(f.get("处理方式")),
            "到货日期": _fmt_date(f.get("到货日期")),
            "登记人": _as_text(f.get("登记人")),
            "计量单位": _as_text(f.get("计量单位")),
            "物料大类": _as_text(f.get("物料大类")),
        }
        for row in records[:DETAIL_LIMIT]
        for f in [row["fields"]]
    ]
    return {
        "report_type": "unqualified",
        "report_name": "不合格物料汇总",
        "total": len(records),
        "records": detail,
        "note": _truncation_note(truncated),
    }


# ── 注册表（S3 套 MCP 壳的对接点）──
# 查询工具 + Harness 计划工具（ticket 05）+ 长期记忆工具（ticket 06）+
# 办公工具（ticket 07，send_card 确认门回调随模块导入注册）+
# 技能库工具（ticket 08，load_skill 拉取 SOP 全文）共用同一注册表；
# 声明 `_ctx` 形参的工具由 execute_tool 自动注入会话上下文（见 execute_tool）。


def _accepts_ctx(func: Callable[..., Any]) -> bool:
    """工具函数是否声明了 `_ctx` 形参（plan 类工具需要会话上下文）。"""
    try:
        return "_ctx" in inspect.signature(func).parameters
    except (TypeError, ValueError):  # pragma: no cover — 内建对象防御
        return False


TOOL_FUNCS: dict[str, Callable[..., Awaitable[dict[str, Any]]]] = {
    "query_stock": query_stock,
    "query_material": query_material,
    "query_movements": query_movements,
    "query_report": query_report,
    **PLAN_TOOL_FUNCS,
    **MEMORY_TOOL_FUNCS,
    **OFFICE_TOOL_FUNCS,
    **SKILL_TOOL_FUNCS,
}

_TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "query_stock",
            "description": (
                "查询物料库存明细（当前在库批次）：按关键词（物料名称/批号模糊）、"
                "QA放行状态（放行/条件放行/否决）、临期天数过滤。"
                "返回每批次的剩余数量、单位、贮存位置、QA放行、入库日期、有效期。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "物料名称或批号关键词（模糊匹配），如「硫酸」「10407」",
                    },
                    "qc_status": {
                        "type": "string",
                        "enum": list(QC_STATUSES),
                        "description": "QA放行状态过滤",
                    },
                    "expiring_days": {
                        "type": "integer",
                        "description": "临期过滤：未来 N 天内到有效期/复验期",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_material",
            "description": (
                "查询物料主数据（物料名称代码一览表）：代码、级别、规格、物料大类、"
                "生产商、免检物料、复验期。查物料的基本信息/代码/级别/规格时用本工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "物料名称/代码/ERP名称关键词（模糊匹配）",
                    },
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_movements",
            "description": (
                "查询物料入库/出库流水（总账）并按物料聚合汇总数量。"
                "问「某段时间入库/领用了哪些物料、量多少」时用本工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "material": {
                        "type": "string",
                        "description": "物料名称关键词（模糊匹配），缺省查全部",
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["inbound", "outbound", "both"],
                        "description": "inbound=入库 / outbound=出库 / both=两者（默认）",
                    },
                    "date_from": {
                        "type": "string",
                        "description": "起始日期 YYYY-MM-DD（含当天）",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "截止日期 YYYY-MM-DD（含当天）",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_report",
            "description": (
                "查询报告清单。report_type=dead 返回入库总账中呆料判断为「是」的批次清单（物料/批号/数量/入库日期/贮存位置）；report_type=unqualified 返回不合格物料清单（物料/不合格项目/处理方式/到货日期）。默认前 10 条+总数。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "report_type": {
                        "type": "string",
                        "enum": ["dead", "unqualified"],
                        "description": "dead=呆料清单（默认）/ unqualified=不合格清单",
                    },
                },
                "required": [],
            },
        },
    },
]

TOOLS: list[dict[str, Any]] = [
    *_TOOLS_SCHEMA,
    *PLAN_TOOLS_SCHEMA,
    *MEMORY_TOOLS_SCHEMA,
    *OFFICE_TOOLS_SCHEMA,
    *SKILL_TOOLS_SCHEMA,
]

# Runner 工具执行统一入口：未知工具/参数错误都包装为 {"error": ...} 结果。


async def execute_tool(
    name: str, arguments: dict[str, Any], ctx: dict[str, Any] | None = None
) -> dict[str, Any]:
    """按名字执行注册工具；异常一律包装为 {"error": ...}（不中断 Runner）。

    ctx：Runner 传入的会话上下文（{"session_id", "chat_id", "open_id"}），
    仅注入给声明了 `_ctx` 形参的工具（ticket 05 的 plan 类工具，发进度
    卡片用）；其余工具签名与调用方式保持不变。
    """
    func = TOOL_FUNCS.get(name)
    if func is None:
        known = "、".join(sorted(TOOL_FUNCS))
        return {"error": f"未知工具 {name!r}，可用工具: {known}"}
    try:
        if _accepts_ctx(func):
            return await func(**arguments, _ctx=ctx)
        return await func(**arguments)
    except WarehouseBitableError as exc:
        logger.warning("工具 %s Base 查询失败: %s", name, exc)
        return {"error": f"Base 查询失败: {exc}"}
    except TypeError as exc:
        logger.warning("工具 %s 参数错误: %s", name, exc)
        return {"error": f"参数错误: {exc}（请检查参数名与类型后重试）"}
    except Exception as exc:  # noqa: BLE001 — 工具层兜底，保证循环不中断
        logger.exception("工具 %s 执行异常", name)
        return {"error": f"工具执行失败: {type(exc).__name__}: {exc}"}


_TRUNCATE_SUFFIX = "\n…[结果超长已截断，请缩小查询范围（加关键词/日期）后重试]"


def serialize_tool_result(result: dict[str, Any]) -> str:
    """工具结果 → JSON 文本；超过 4KB 截断并附提示（spec：截断 4KB/条）。"""
    try:
        text = json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = json.dumps({"error": "工具结果不可序列化"}, ensure_ascii=False)
    if len(text.encode("utf-8")) <= TOOL_RESULT_MAX_BYTES:
        return text
    # 预算 = 4KB - 提示后缀的字节数（含安全余量），保证截断后仍 ≤4KB
    budget = TOOL_RESULT_MAX_BYTES - len(_TRUNCATE_SUFFIX.encode("utf-8")) - 8
    clipped = text.encode("utf-8")[:budget].decode("utf-8", errors="ignore")
    return clipped + _TRUNCATE_SUFFIX
