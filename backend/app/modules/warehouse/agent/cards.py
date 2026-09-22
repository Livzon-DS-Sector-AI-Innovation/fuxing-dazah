"""仓储 Agent 查询结果卡片渲染器（S1 ticket 04，飞书卡片 JSON 2.0）。

Runner 的 Reply → 飞书交互卡片。卡片为 **JSON 2.0 结构**
（schema/config/header/body.elements；2026-09-14 由旧版 1.0 迁移，
实证规格：table 组件列字段为 display_name、按钮直接放 body.elements、
旧 action 容器在 2.0 已不支持——横排按钮用 column_set 双列），
``notification.send_card`` / ``send_card_to_user`` 直接可发。

渲染策略（ticket 04）：
- Reply.data 携带结构化工具结果（runner 工具循环填充：最后使用的工具名 +
  原始结果 dict，见 runner.Reply 注释）→ 按工具名分发专用卡片：
  query_stock → 库存卡片（批号/剩余数量/单位/库位/三态列）；
  query_material → 物料主数据卡片（单条块式全字段 / 多条原生表格）；
  query_movements → 出入库汇总卡片（方向聚合 + 明细表）；
  query_report → 呆料/不合格清单卡片（report_type 区分标题）；
- 无 data / 未知工具 / result 非 dict → ``render_text_card`` 文本卡片兜底
  （即票02 的「仓储助手」markdown 卡片行为）；
- 渲染防御：任何渲染异常降级文本卡片，**永不因渲染抛错中断回复**。

表格约定：lark_md（含 2.0 markdown 组件）不支持表格语法，数据表格一律用
2.0 原生 table 组件（列定义见各 *_COLUMNS 常量，单元格 data_type=text，
数量列 lark_md 保留加粗）；单元格统一经 ``_clean`` 清洗（去 markdown
特殊字符/换行、超长截断，空值显示 -），防止数据内容破坏排版或撑爆卡片
体积。明细默认前 10 条（对齐工具层 DETAIL_LIMIT），超出追加「共 N 条，
回复「更多」查看」提示（原生 table 行数 ≤ page_size 不出分页器，行为
与旧伪表格一致）。兜底文本卡片会把 LLM 回复中的标准 markdown 表格
（|---| 分隔）自动转成原生 table 组件（``_markdown_with_tables``），
其余文本原样保持 markdown。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.modules.warehouse.agent.runner import Reply
from app.modules.warehouse.models import WarehouseAgentSession

logger = logging.getLogger(__name__)

# 卡片 JSON schema 版本（2.0：原生 table 组件 / 按钮直排 / column_set）
CARD_SCHEMA = "2.0"

# 兜底文本卡片标题（与 gateway 票02 行为一致）
TEXT_CARD_TITLE = "仓储助手"

# 明细最多展示行数（对齐 tools/query.py 的 DETAIL_LIMIT）
MAX_DETAIL_ROWS = 10

# 原生 table 每页行数（行数 ≤ page_size 不出分页器，与旧行式伪表格观感一致）
TABLE_PAGE_SIZE = 10

# LLM 文字回复在专用卡片顶部的截断长度（超出以 … 结尾）
REPLY_TEXT_MAX = 600

# 单元格默认截断长度 / note 截断长度
_CELL_MAX = 40
_NOTE_MAX = 200

# 兜底文本卡片转原生 table 的安全上限（防 LLM 超大表撑爆卡片体积）
_MD_TABLE_MAX_ROWS = 30
_MD_TABLE_MAX_COLS = 8

# 库存卡片列定义（(name, display_name, data_type)；测试断言用）
STOCK_TABLE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("material", "物料", "text"),
    ("batch", "批号", "text"),
    ("qty", "剩余数量", "lark_md"),
    ("unit", "单位", "text"),
    ("location", "库位", "text"),
    ("qc", "三态", "text"),
)

# 三态标记（QA放行 单选：放行/条件放行/否决，V1.0-5 契约）
_QC_STATUS_MARKS = {"放行": "✅", "条件放行": "⚠️", "否决": "❌"}

# markdown/HTML 特殊字符 → 空格（防止单元格内容被 lark_md 解析）。
# 不含 #：换行已清洗且数据行均有序号前缀，# 不会出现在行首（无标题语法风险），
# 而库位名「24#仓库」等场景 # 是有效字符，必须保留。
_MD_CHARS = ("*", "_", "`", "[", "]", "<", ">")

_WS_RE = re.compile(r"\s+")


# ── 基础构件 ──


def _md(content: str) -> dict[str, Any]:
    return {"tag": "markdown", "content": content}


def build_card(
    *, title: str, template: str, elements: list[dict[str, Any]]
) -> dict[str, Any]:
    """飞书卡片 JSON 2.0 根结构（gateway/confirm 内联卡片同构复用）。"""
    return {
        "schema": CARD_SCHEMA,
        "config": {"update_multi": True, "width_mode": "fill"},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": template,
        },
        "body": {"elements": elements},
    }


def _table(
    columns: tuple[tuple[str, str, str], ...], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """2.0 原生 table 组件：columns=(name, display_name, data_type)，
    rows 键=列 name（值须为字符串）。行数 ≤ page_size 不出分页器。"""
    return {
        "tag": "table",
        "page_size": TABLE_PAGE_SIZE,
        "row_height": "low",
        "header_style": {"background_style": "grey", "bold": True},
        "columns": [
            {"name": name, "display_name": display, "data_type": data_type}
            for name, display, data_type in columns
        ],
        "rows": rows,
    }


def _button_row(buttons: list[dict[str, Any]]) -> dict[str, Any]:
    """横排按钮行（2.0 无 action 容器：column_set auto 宽双列承载）。"""
    return {
        "tag": "column_set",
        "flex_mode": "none",
        "columns": [
            {
                "tag": "column",
                "width": "auto",
                "vertical_align": "top",
                "elements": [button],
            }
            for button in buttons
        ],
    }


def _confirm_cancel_buttons(
    value_base: dict[str, Any], *, confirm_label: str, cancel_label: str
) -> dict[str, Any]:
    """确认门按钮行（value 携带 scene/draft_id/action 供回调路由）。

    2.0 按钮回调数据官方字段为 behaviors[type=callback].value（字段表必填），
    旧式 value 官方 Demo 仍在用且发送合法——两处双写同值，回调取哪个都一致。
    """
    return _button_row(
        [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": confirm_label},
                "type": "primary",
                "value": {**value_base, "action": "confirm"},
                "behaviors": [
                    {"type": "callback", "value": {**value_base, "action": "confirm"}}
                ],
            },
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": cancel_label},
                "value": {**value_base, "action": "cancel"},
                "behaviors": [
                    {"type": "callback", "value": {**value_base, "action": "cancel"}}
                ],
            },
        ]
    )


def _clean(value: Any, max_len: int = _CELL_MAX) -> str:
    """单元格值 → 安全展示文本：去换行/markdown 字符、截断、空值显示 -。"""
    try:
        text = "" if value is None else str(value)
    except Exception:  # noqa: BLE001 — 渲染防御：任意对象 str 失败按空值处理
        text = ""
    text = text.replace("\r", " ").replace("\n", " ")
    for ch in _MD_CHARS:
        text = text.replace(ch, " ")
    text = _WS_RE.sub(" ", text).strip()
    if len(text) > max_len:
        text = text[:max_len] + "…"
    return text or "-"


def _clip(text: str, max_len: int) -> str:
    """LLM 文本截断（保留 markdown 原貌，仅控制长度）。"""
    text = (text or "").strip()
    return text if len(text) <= max_len else text[:max_len] + "…"


# ── 兜底文本卡片：标准 markdown 表格 → 原生 table 转换 ──
# LLM 回复里可能出现标准 markdown 表格（| a | b | + |---|---|），lark_md
# 不渲染表格语法（原样露管道符）。此处把表格块解析成 2.0 table 组件，
# 其余文本行原样保持 markdown 元素。

_MD_TABLE_ROW_RE = re.compile(r"^\s*\|")  # 表格行：以 | 开头（容忍缺尾管道）
_MD_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]*-{3,}[\s:|-]*\|?\s*$")
_MD_TABLE_CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")


def _is_md_table_separator(line: str) -> bool:
    """分隔行：仅含 | : - 空格 且至少一段 3 连字符（|---|---| / | --- |）。"""
    return bool(line.strip()) and bool(_MD_TABLE_SEP_RE.match(line))


def _split_md_table_cells(line: str) -> list[str]:
    """表格行 → 单元格文本（去首尾管道、按未转义 | 切分、还原 \\|）。"""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.replace("\\|", "|").strip() for cell in _MD_TABLE_CELL_SPLIT_RE.split(stripped)]


def _md_table_element(header: list[str], data_lines: list[str]) -> dict[str, Any] | None:
    """解析后的表头/数据行 → table 组件；畸形（0 列/超限）返回 None 回落原文。"""
    if not header or len(header) > _MD_TABLE_MAX_COLS:
        return None
    columns = tuple(
        (f"c{index}", _clean(cell, 24) if cell else f"列{index + 1}", "lark_md")
        for index, cell in enumerate(header)
    )
    rows: list[dict[str, Any]] = []
    for line in data_lines[:_MD_TABLE_MAX_ROWS]:
        cells = _split_md_table_cells(line)
        cells = (cells + [""] * len(header))[: len(header)]
        rows.append({f"c{index}": cell for index, cell in enumerate(cells)})
    if not rows:
        return None
    return _table(columns, rows)


def _markdown_with_tables(text: str) -> list[dict[str, Any]]:
    """LLM 文本 → 元素列表：标准 markdown 表格块转原生 table，其余保持 markdown。"""
    lines = (text or "").splitlines()
    elements: list[dict[str, Any]] = []
    plain: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        # 表格块识别：当前行是管道行，下一行是分隔行
        if (
            "|" in line
            and _MD_TABLE_ROW_RE.match(line)
            and index + 1 < len(lines)
            and _is_md_table_separator(lines[index + 1])
        ):
            header = _split_md_table_cells(line)
            data_start = index + 2
            data_end = data_start
            while data_end < len(lines) and _MD_TABLE_ROW_RE.match(lines[data_end]):
                data_end += 1
            table = _md_table_element(header, lines[data_start:data_end])
            if table is not None:
                # 剔除紧邻表格的空行（markdown 块收口干净）
                while plain and not plain[-1].strip():
                    plain.pop()
                if plain:
                    elements.append(_md("\n".join(plain)))
                    plain = []
                elements.append(table)
                index = data_end
                # 跳过表格后紧邻的一个空行
                if index < len(lines) and not lines[index].strip():
                    index += 1
                continue
        plain.append(line)
        index += 1
    if plain:
        elements.append(_md("\n".join(plain)))
    return elements or [_md("")]


def render_text_card(title: str, markdown: str) -> dict[str, Any]:
    """通用文本卡片（无结构化数据/渲染降级时的兜底）：markdown 表格自动转原生 table。"""
    return build_card(title=title, template="blue", elements=_markdown_with_tables(markdown or ""))


def _list_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """工具结果 records → dict 行列表。

    结构畸形（缺失/类型异常/无一是 dict）抛 ValueError——由
    render_reply_card 捕获降级文本卡片（ticket 04：数据缺字段/类型异常
    降级，不静默渲染坏数据）；records=[] 为合法空结果，返回空列表走
    各卡片的空结果友好态。
    """
    records = data.get("records")
    if not isinstance(records, list):
        raise ValueError(f"records 应为列表，实际 {type(records).__name__}")
    rows = [rec for rec in records if isinstance(rec, dict)]
    if records and not rows:
        raise ValueError("records 元素均非 dict")
    return rows


def _list_field(data: dict[str, Any], key: str) -> list[Any]:
    """工具结果指定键 → list；结构畸形抛 ValueError（同 _list_rows 口径）。"""
    value = data.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key} 应为列表，实际 {type(value).__name__}")
    return value


def _total_of(data: dict[str, Any]) -> int | None:
    total = data.get("total")
    return total if isinstance(total, int) and total >= 0 else None


def _note_of(data: dict[str, Any]) -> str:
    note = data.get("note")
    return note.strip() if isinstance(note, str) else ""


def _dict_rows(records: list[Any]) -> list[dict[str, Any]]:
    return [rec for rec in records if isinstance(rec, dict)]


def _summary_elements(reply_text: str) -> list[dict[str, Any]]:
    """专用卡片顶部的 LLM 文字回复（保留其总结价值；分割线由各渲染器统一加）。"""
    text = (reply_text or "").strip()
    if not text:
        return []
    return [_md(_clip(text, REPLY_TEXT_MAX))]


def _note_elements(note: str) -> list[dict[str, Any]]:
    return [{"tag": "hr"}, _md(f"ℹ️ {_clean(note, _NOTE_MAX)}")]


def _truncation_hint(total: int | None, shown: int) -> str:
    """截断提示行（S1 不做真分页，仅提示）。"""
    if total is not None and total > shown:
        return f"……共 {total} 条，回复「更多」查看（当前展示前 {shown} 条）"
    return ""


def _status_mark(status: str) -> str:
    """QA 放行三态 → emoji 前缀标记。"""
    if status == "-":
        return status
    return f"{_QC_STATUS_MARKS.get(status, '')}{status}"


def _generic_table(rows: list[dict[str, Any]], max_rows: int = MAX_DETAIL_ROWS) -> dict[str, Any]:
    """通用原生表格：列取首条记录的键（工具输出的中文键即展示名）。"""
    columns: tuple[tuple[str, str, str], ...] = tuple(
        (str(key), str(key), "text") for key in rows[0].keys()
    )
    table_rows = [
        {str(key): _clean(rec.get(str(key))) for key in rows[0].keys()}
        for rec in rows[:max_rows]
    ]
    return _table(columns, table_rows)


# ── 1. 库存卡片 ──

_EMPTY_STOCK_TEXT = (
    "未查询到符合条件的库存记录。\n"
    "可换个关键词试试，或放宽筛选条件（如不限 QA 放行状态 / 临期范围）。"
)


def _stock_table_row(rec: dict[str, Any]) -> dict[str, str]:
    """库存记录 → table 行（键=STOCK_TABLE_COLUMNS 列 name）。"""
    qty = _clean(rec.get("剩余数量"), 16)
    return {
        "material": _clean(rec.get("物料名称")),
        "batch": _clean(rec.get("物料批号")),
        "qty": f"**{qty}**" if qty != "-" else qty,
        "unit": _clean(rec.get("单位"), 10),
        "location": _clean(rec.get("贮存位置"), 24),
        "qc": _status_mark(_clean(rec.get("QA放行"), 10)),
    }


def _stock_table(rows: list[dict[str, Any]], total: int | None) -> list[dict[str, Any]]:
    """库存数据 → [table 元素]（+ 截断提示 markdown 元素）。"""
    elements = [_table(STOCK_TABLE_COLUMNS, [_stock_table_row(r) for r in rows[:MAX_DETAIL_ROWS]])]
    hint = _truncation_hint(total, min(len(rows), MAX_DETAIL_ROWS))
    if hint:
        elements.append(_md(hint))
    return elements


def render_stock_card(data: dict[str, Any], *, reply_text: str = "") -> dict[str, Any]:
    """库存查询结果卡片：批号/剩余数量/单位/库位/三态。"""
    rows = _list_rows(data)
    elements = _summary_elements(reply_text)
    if not rows:
        elements.append(_md(_EMPTY_STOCK_TEXT))
        return build_card(title="📦 库存查询", template="blue", elements=elements)
    elements.append({"tag": "hr"})
    elements.extend(_stock_table(rows, _total_of(data)))
    note = _note_of(data)
    if note:
        elements.extend(_note_elements(note))
    return build_card(title="📦 库存查询", template="blue", elements=elements)


# ── 2. 物料主数据卡片 ──

# 多条记录行式表格列定义（(name, display_name, data_type)）
_MATERIAL_TABLE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("material", "物料", "text"),
    ("code", "代码", "text"),
    ("grade", "级别", "text"),
    ("spec", "规格", "text"),
    ("category", "大类", "text"),
    ("manufacturer", "生产商", "text"),
)
# 单条记录块式展示的字段分组（键 = 工具输出键）
_MATERIAL_BLOCK_GROUPS: tuple[tuple[str, ...], ...] = (
    ("级别", "物料大类"),
    ("生产商", "免检物料", "复验期"),
    ("包装规格", "单位换算"),
)


def _material_block(index: int, rec: dict[str, Any]) -> str:
    title = (
        f"**{index}. {_clean(rec.get('物料名称'))}**"
        f"（代码 {_clean(rec.get('代码'), 20)}）"
    )
    lines = [
        "｜".join(f"{label} {_clean(rec.get(label), 20)}" for label in group)
        for group in _MATERIAL_BLOCK_GROUPS
    ]
    return "\n".join([title, *lines])


def _material_table_row(rec: dict[str, Any]) -> dict[str, str]:
    """物料主数据记录 → table 行（键=_MATERIAL_TABLE_COLUMNS 列 name）。"""
    return {
        "material": _clean(rec.get("物料名称")),
        "code": _clean(rec.get("代码"), 20),
        "grade": _clean(rec.get("级别"), 16),
        "spec": _clean(rec.get("规格"), 24),
        "category": _clean(rec.get("物料大类"), 16),
        "manufacturer": _clean(rec.get("生产商"), 24),
    }


def render_material_card(
    data: dict[str, Any], *, reply_text: str = ""
) -> dict[str, Any]:
    """物料主数据卡片：单条块式全字段，多条原生表格。"""
    rows = _list_rows(data)
    elements = _summary_elements(reply_text)
    if not rows:
        elements.append(
            _md("未查询到符合条件的物料主数据。\n可换个名称/代码关键词试试。")
        )
        return build_card(title="🧪 物料信息", template="blue", elements=elements)
    elements.append({"tag": "hr"})
    if len(rows) == 1:
        elements.append(_md(_material_block(1, rows[0])))
        shown = 1
    else:
        elements.append(
            _table(_MATERIAL_TABLE_COLUMNS, [_material_table_row(r) for r in rows[:MAX_DETAIL_ROWS]])
        )
        shown = min(len(rows), MAX_DETAIL_ROWS)
    hint = _truncation_hint(_total_of(data), shown)
    if hint:
        elements.append(_md(hint))
    note = _note_of(data)
    if note:
        elements.extend(_note_elements(note))
    return build_card(title="🧪 物料信息", template="blue", elements=elements)


# ── 3. 出入库汇总卡片 ──


def _movement_section_lines(heading: str, rows: Any) -> str:
    """单方向汇总节 markdown：`📥 入库汇总` + 聚合行（物料 数量 单位）。"""
    if not isinstance(rows, list) or not rows:
        return ""
    dict_rows = _dict_rows(rows)
    if not dict_rows:
        return ""
    icon = "📥" if "入库" in heading else "📤" if "出库" in heading else "•"
    lines = [f"{icon} **{heading}**（共 {len(dict_rows)} 种物料）"]
    for index, rec in enumerate(dict_rows[:MAX_DETAIL_ROWS], 1):
        qty = _clean(rec.get("数量"), 20)
        cells = [
            _clean(rec.get("物料名称")),
            f"**{qty}**" if qty != "-" else qty,
            _clean(rec.get("单位"), 10),
        ]
        lines.append(f"{index}. " + "｜".join(cells))
    if len(dict_rows) > MAX_DETAIL_ROWS:
        lines.append(f"……汇总仅展示前 {MAX_DETAIL_ROWS} 种物料")
    return "\n".join(lines)


def _movement_detail_elements(heading: str, rows: Any) -> list[dict[str, Any]]:
    """单方向明细节元素：`📥 入库明细` markdown + 原生 table。"""
    if not isinstance(rows, list) or not rows:
        return []
    dict_rows = _dict_rows(rows)
    if not dict_rows:
        return []
    icon = "📥" if "入库" in heading else "📤" if "出库" in heading else "•"
    return [_md(f"{icon} **{heading}**"), _generic_table(dict_rows)]


def render_movements_card(
    data: dict[str, Any], *, reply_text: str = ""
) -> dict[str, Any]:
    """出入库总账卡片：按方向的聚合汇总数字 + 原生明细表。"""
    elements = _summary_elements(reply_text)
    body: list[dict[str, Any]] = []
    summary_chunks: list[str] = []
    summary = _list_field(data, "summary")
    records = _list_field(data, "records")
    for section in summary:
        if isinstance(section, dict):
            for heading, rows in section.items():
                chunk = _movement_section_lines(str(heading), rows)
                if chunk:
                    summary_chunks.append(chunk)
    if summary_chunks:
        body.append(_md("\n\n".join(summary_chunks)))
    for section in records:
        if isinstance(section, dict):
            for heading, rows in section.items():
                body.extend(_movement_detail_elements(str(heading), rows))
    if not body:
        elements.append(
            _md("未查询到符合条件的出入库记录。\n可放宽日期范围或换物料关键词试试。")
        )
        return build_card(title="🔄 出入库汇总", template="blue", elements=elements)
    total = _total_of(data)
    if total is not None and total > MAX_DETAIL_ROWS:
        body.append(_md(_truncation_hint(total, MAX_DETAIL_ROWS)))
    elements.append({"tag": "hr"})
    elements.extend(body)
    note = _note_of(data)
    if note:
        elements.extend(_note_elements(note))
    return build_card(title="🔄 出入库汇总", template="blue", elements=elements)


# ── 4. 呆料/不合格报告卡片 ──

_REPORT_TITLES = {"dead": "📋 呆料批次清单", "unqualified": "🚫 不合格物料汇总"}
_REPORT_TEMPLATES = {"dead": "orange", "unqualified": "red"}


def render_report_card(data: dict[str, Any], *, reply_text: str = "") -> dict[str, Any]:
    """呆料/不合格清单卡片：report_type 区分标题与配色。"""
    report_type = str(data.get("report_type") or "")
    title = _REPORT_TITLES.get(report_type, "📋 报告清单")
    template = _REPORT_TEMPLATES.get(report_type, "blue")
    rows = _list_rows(data)
    elements = _summary_elements(reply_text)
    if not rows:
        elements.append(_md("当前没有符合条件的报告记录。"))
        return build_card(title=title, template=template, elements=elements)
    elements.append({"tag": "hr"})
    elements.append(_generic_table(rows))
    hint = _truncation_hint(_total_of(data), min(len(rows), MAX_DETAIL_ROWS))
    if hint:
        elements.append(_md(hint))
    note = _note_of(data)
    if note:
        elements.extend(_note_elements(note))
    return build_card(title=title, template=template, elements=elements)


# ── 5. 任务计划进度卡片（ticket 05，工具侧发送）──

# 步骤状态 → 图标（ticket 05 契约）
STEP_STATUS_MARKS = {
    "pending": "⬜",
    "in_progress": "⏳",
    "done": "✅",
    "skipped": "⏭",
    "failed": "❌",
}
PLAN_CARD_TITLE = "📋 任务计划"
_PLAN_STATUS_CN = {"active": "进行中", "done": "已完成", "abandoned": "已取消"}


def render_progress_card(plan: dict[str, Any]) -> dict[str, Any]:
    """任务进度卡片：计划标题 + 步骤状态列表（tools/plan.py 发送）。

    plan: {"plan_no", "title", "status", "steps": [{no, desc, status, note}]}。
    每步一行「图标 序号. 描述（note）」，头部附状态与进度（终态步/总步数）。
    渲染防御同其他卡片：字段缺失按空值处理、内容 _clean 清洗，不抛错。
    """
    plan_no = _clean(plan.get("plan_no"), 30)
    title = _clean(plan.get("title"), 60)
    steps = [s for s in (plan.get("steps") or []) if isinstance(s, dict)]
    plan_status = str(plan.get("status") or "active")
    finished = sum(
        1 for s in steps if str(s.get("status") or "") in ("done", "skipped", "failed")
    )
    lines = [
        f"**{plan_no}｜{title}**",
        f"状态：{_PLAN_STATUS_CN.get(plan_status, plan_status)}｜进度 {finished}/{len(steps)}",
    ]
    for step in steps:
        status_key = str(step.get("status") or "pending")
        mark = STEP_STATUS_MARKS.get(status_key, "⬜")
        no = step.get("no")
        no_text = str(no) if no is not None else "?"
        line = f"{mark} {no_text}. {_clean(step.get('desc'), 60)}"
        note = str(step.get("note") or "").strip()
        if note:
            line += f"（{_clean(note, 40)}）"
        lines.append(line)
    if not steps:
        lines.append("（该计划没有步骤）")
    template = "green" if plan_status == "done" else "blue"
    return build_card(
        title=PLAN_CARD_TITLE, template=template, elements=[_md("\n".join(lines))]
    )


# ── 6. 办公工具卡片（ticket 07：发送确认预览 / 确认后外发 / 到点提醒）──

# 预览确认卡片标题与按钮文案（gateway 卡片回调路由按 value.scene 分发）
SEND_PREVIEW_CARD_TITLE = "📨 待发送确认"
CONFIRM_SEND_BUTTON_LABEL = "✅ 确认发送"
CANCEL_SEND_BUTTON_LABEL = "❌ 取消"
REMINDER_CARD_TITLE = "⏰ 到点提醒"

# 预览卡片正文中 content 的截断长度（外发原文仍完整发送）
_PREVIEW_CONTENT_MAX = 500


def render_confirm_preview_card(
    payload: dict[str, Any], *, scene: str, draft_id: str
) -> dict[str, Any]:
    """send_card 确认门预览卡片（tools/office.py 发起后发发起人）。

    payload 为确认草稿载荷（target/title/content/target_kind…）；
    按钮 value 携带 scene + draft_id（gateway 回调路由 → confirm.handle_action，
    仅发起人点击生效）。渲染防御同其他卡片：字段缺失按空值处理，不抛错。
    """
    title = _clean(payload.get("title"), 60)
    # 目标为系统生成的 ID（user:ou_… / group:oc_…，含下划线）：
    # 确认门要求精确展示，不做 markdown 字符清洗（仅防换行），下划线误伤不可接受
    target = " ".join(str(payload.get("target") or "-").split()) or "-"
    kind = str(payload.get("target_kind") or "")
    kind_cn = {"user": "用户", "group": "群聊"}.get(kind, "")
    target_display = f"{kind_cn} {target}".strip()
    content = str(payload.get("content") or "").strip()
    lines = [
        f"**标题**：{title}",
        f"**目标**：{target_display}",
        "",
        "**内容**：",
        _clip(content, _PREVIEW_CONTENT_MAX) or "（无内容）",
    ]
    value_base = {"scene": scene, "draft_id": draft_id}
    return build_card(
        title=SEND_PREVIEW_CARD_TITLE,
        template="orange",
        elements=[
            _md("\n".join(lines)),
            {"tag": "hr"},
            _confirm_cancel_buttons(
                value_base,
                confirm_label=CONFIRM_SEND_BUTTON_LABEL,
                cancel_label=CANCEL_SEND_BUTTON_LABEL,
            ),
        ],
    )


def render_outgoing_card(title: str, content: str) -> dict[str, Any]:
    """确认后真正外发的卡片（send_card 工具的最终投递内容）。"""
    return build_card(
        title=_clean(title, 60) or "通知",
        template="blue",
        elements=[_md(content or "")],
    )


def render_reminder_card(reminder: dict[str, Any]) -> dict[str, Any]:
    """到点提醒卡片（create_reminder 的延时任务触发时发送）。

    reminder: {"content", "trigger_at"（展示用时间文本，可空）}。
    """
    content = str(reminder.get("content") or "").strip() or "（无内容）"
    lines = [f"**{content}**"]
    trigger_at = str(reminder.get("trigger_at") or "").strip()
    if trigger_at:
        lines.append(f"设定时间：{_clean(trigger_at, 40)}")
    return build_card(
        title=REMINDER_CARD_TITLE, template="yellow", elements=[_md("\n".join(lines))]
    )


# ── 7. 登记确认卡片（S2 ticket 03：识别草稿 confirm/cancel，对话修改重发；
#      S3 ticket 01：按 draft.scene 分支——receipt 入库识别 / gmp_outbound
#      GMP 出库对话登记 / finished_outbound 成品出库对话登记（ticket 02）；
#      按钮 value.scene 分发到各自确认回调）──

# 卡片标题与按钮文案（gateway 卡片回调路由按 value.scene 分发）
RECEIPT_CONFIRM_CARD_TITLE = "📋 入库确认"
CONFIRM_RECEIPT_BUTTON_LABEL = "✅ 确认入库"
CANCEL_RECEIPT_BUTTON_LABEL = "❌ 取消"

# GMP 出库登记确认卡片（S3 ticket 01：scene=gmp_outbound 分支文案）
GMP_OUTBOUND_SCENE = "gmp_outbound"
GMP_CONFIRM_CARD_TITLE = "🧪 GMP 出库登记"
CONFIRM_GMP_BUTTON_LABEL = "✅ 确认登记"
CANCEL_GMP_BUTTON_LABEL = "❌ 取消"

# 成品出库登记确认卡片（S3 ticket 02：scene=finished_outbound 分支文案）
FINISHED_OUTBOUND_SCENE = "finished_outbound"
FINISHED_CONFIRM_CARD_TITLE = "📦 成品出库登记"
CONFIRM_FINISHED_BUTTON_LABEL = "✅ 确认登记"
CANCEL_FINISHED_BUTTON_LABEL = "❌ 取消"

# 成品入库（V3.0 §4.6：识别+对话双入口；质量状态恒写待检，卡片静态提示）
FINISHED_RECEIPT_SCENE = "finished_receipt"
FINISHED_RECEIPT_CONFIRM_CARD_TITLE = "🏭 成品入库登记"
CONFIRM_FINISHED_RECEIPT_BUTTON_LABEL = "✅ 确认入库"
CANCEL_FINISHED_RECEIPT_BUTTON_LABEL = "❌ 取消"

# 领料登记确认卡片（V3.0 分期C：scene=picking_outbound 分支文案）
PICKING_OUTBOUND_SCENE = "picking_outbound"
PICKING_CONFIRM_CARD_TITLE = "🏭 领料登记"
CONFIRM_PICKING_BUTTON_LABEL = "✅ 确认领料"
CANCEL_PICKING_BUTTON_LABEL = "❌ 取消"

# 识别置信度低于该阈值加 ⚠ 高亮（spec：低置信度字段提醒重点核对）
RECEIPT_CONFIDENCE_WARN = 0.7

# 必提 8 字段（展示名, recognized/aligned 键；顺序即卡片展示顺序）
RECEIPT_REQUIRED_FIELDS: tuple[tuple[str, str], ...] = (
    ("物料名称", "material_name"),
    ("厂家批号", "vendor_batch_no"),
    ("数量", "quantity"),
    ("单位", "unit"),
    ("供应商", "supplier"),
    ("生产商", "manufacturer"),
    ("车牌", "plate_no"),
    ("合同号", "contract_no"),
)

# 选提 5 字段（识别不到显示 —）
RECEIPT_OPTIONAL_FIELDS: tuple[tuple[str, str], ...] = (
    ("包装规格", "package_spec"),
    ("生产日期", "produced_at"),
    ("到货时间段", "arrival_period"),
    ("备注", "remark"),
    ("联系人", "contact"),
)

# 对话修改引导（spec 决策 5：[修改] 无按钮，引导文本对话）
RECEIPT_MODIFY_HINT = (
    "💡 确认前请核对 ⚠ 字段；要修改可直接回复消息（如「数量改成 200」）。"
)

# GMP 必收 4 字段（展示名, aligned 键；顺序即卡片展示顺序）
GMP_REQUIRED_FIELDS: tuple[tuple[str, str], ...] = (
    ("物料批号", "material_batch_no"),
    ("领用数量", "quantity"),
    ("单位", "unit"),
    ("生产批号", "production_batch_no"),
)

# GMP 选填/展示字段（物料名称仅展示——lookup 拒写不落 Base）
GMP_OPTIONAL_FIELDS: tuple[tuple[str, str], ...] = (
    ("物料名称", "material_name"),
    ("单据类型", "doc_type"),
    ("领用品种", "category"),
    ("领用部门", "department"),
)

GMP_MODIFY_HINT = "💡 确认前请核对以上信息；要修改可直接回复消息（如「数量改成 30」）。"

# 成品出库必收 5 字段（S3 ticket 02；展示名, aligned 键；顺序即卡片展示顺序）
FINISHED_REQUIRED_FIELDS: tuple[tuple[str, str], ...] = (
    ("产品名称", "product_name"),
    ("产品批号", "product_batch_no"),
    ("出库量", "quantity"),
    ("单位", "unit"),
    ("销售客户", "customer"),
)

# 成品出库选填字段（用途缺省「销售」；快递号为附件字段——submit 侧降级
# 不落 Base，仅展示并用于推送卡片）
FINISHED_OPTIONAL_FIELDS: tuple[tuple[str, str], ...] = (
    ("用途", "purpose"),
    ("快递号", "express_no"),
    ("温度计", "thermometer"),
    ("备注", "remark"),
)

FINISHED_MODIFY_HINT = (
    "💡 确认前请核对以上信息；要修改可直接回复消息（如「出库量改成 200」）。"
)

# 成品入库必收 4 字段（展示名, 键；识别路径 recognized 带置信度、对话路径
# aligned 即收集值——同一渲染函数两用）
FINISHED_RECEIPT_REQUIRED_FIELDS: tuple[tuple[str, str], ...] = (
    ("产品名称", "product_name"),
    ("产品批号", "product_batch_no"),
    ("入库数量", "quantity"),
    ("单位", "unit"),
)

# 成品入库选填字段（入库日期缺省提交日；车间写备注前缀——入库车间列只读）
FINISHED_RECEIPT_OPTIONAL_FIELDS: tuple[tuple[str, str], ...] = (
    ("入库日期", "receipt_date"),
    ("品规", "spec"),
    ("生产日期", "produced_at"),
    ("有效期", "expiry"),
    ("生产车间", "workshop"),
    ("库区位置", "storage_location"),
    ("备注", "remark"),
)

FINISHED_RECEIPT_MODIFY_HINT = (
    "💡 确认前请核对以上信息；要修改可直接回复消息（如「数量改成 100」）。"
    "入库质量状态默认「待检」，QC 判定后在台账改判。"
)

# 领料必收 4 字段（展示名, aligned 键；顺序即卡片展示顺序）
PICKING_REQUIRED_FIELDS: tuple[tuple[str, str], ...] = (
    ("物料", "material"),
    ("领用数量", "quantity"),
    ("单位", "unit"),
    ("领用部门", "department"),
)

# 领料选填/展示字段（指定批号有值=用户改过建议；无值=按 FIFO 建议）
PICKING_OPTIONAL_FIELDS: tuple[tuple[str, str], ...] = (
    ("领用类型", "use_type"),
    ("指定批号", "designated_batch"),
    ("备注", "remark"),
)

PICKING_MODIFY_HINT = (
    "💡 确认前请核对批次与数量；要改批号可直接回复消息（如「改成 10407-251008」）。"
)


def _field_line(
    index: int,
    label: str,
    key: str,
    recognized: dict[str, Any],
    aligned: dict[str, Any],
    *,
    warn_on_missing: bool,
) -> str:
    """单字段展示行：`1. 数量：200 ⚠`。

    值来源：draft.aligned 覆盖优先（对话修改后的最新值；material_name 恒为
    对齐标准名），否则 recognized 识别值。⚠ 规则：人工改过的字段不再提示
    （用户自己填的）；未改过且 confidence < 0.7 加 ⚠；空值展示 —（选提字段
    的正常缺省）时仅在 warn_on_missing（必提分区）下加 ⚠ 提醒缺识别。
    """
    override = aligned.get(key)
    if override is not None and str(override).strip():
        value_text = _clean(str(override), 60)
        return f"{index}. {label}：{value_text}"
    item = recognized.get(key)
    value: Any = item.get("value") if isinstance(item, dict) else None
    confidence = 0.0
    if isinstance(item, dict):
        try:
            confidence = float(str(item.get("confidence")))
        except (TypeError, ValueError):
            confidence = 0.0  # 缺省/非数字按 0 处理
    text = "" if value is None else str(value).strip()
    if not text:
        mark = " ⚠" if warn_on_missing else ""
        return f"{index}. {label}：—{mark}"
    mark = " ⚠" if confidence < RECEIPT_CONFIDENCE_WARN else ""
    return f"{index}. {label}：{_clean(text, 60)}{mark}"


def _aligned_line(aligned: dict[str, Any]) -> str:
    """物料对齐行：none → 未匹配警告；非 none → 标准名+代码+大类+核对提示。

    reverse/fuzzy 匹配（识别名带后缀或近似）附加「请核对」提示——名称
    识别可能有误，代码/大类仅供参考。
    """
    match = str(aligned.get("match_confidence") or "")
    if match == "none":
        return "⚠ 物料名称未匹配主数据，请核对"
    if not match and not aligned:
        return ""  # aligned 缺失（防御）：整段降级省略
    name = _clean(aligned.get("material_name"), 60)
    code = _clean(aligned.get("code"), 30)
    category = _clean(aligned.get("material_category"), 20)
    line = f"**物料对齐**：{name}（代码 {code}｜大类 {category}）"
    caveat = ""
    if match == "fuzzy" or aligned.get("match_direction") == "reverse":
        caveat = " ⚠ 按近似/前缀匹配，请核对物料名称"
    return line + caveat


def _render_gmp_confirm_card(draft: Any) -> dict[str, Any]:
    """GMP 出库登记确认卡片（scene=gmp_outbound 分支，S3 ticket 01）。

    draft.aligned = 对话收集字段（canonical 键；create_dialog_draft 落库，
    update_draft 修改后覆盖），recognized 同内容留底（无识别置信度语义，
    ⚠ 规则仅保留缺字段提醒）。物料名称仅展示（lookup 拒写不落 Base）。
    渲染防御同主入口：字段缺失降级，不抛错。
    """
    aligned = draft.aligned if isinstance(draft.aligned, dict) else {}
    recognized = draft.recognized if isinstance(draft.recognized, dict) else {}
    draft_no = _clean(getattr(draft, "draft_no", ""), 30)
    scene = str(getattr(draft, "scene", "") or GMP_OUTBOUND_SCENE)
    draft_id = str(getattr(draft, "id", ""))

    lines = [f"**草稿**：{draft_no or '-'}", "", "**登记信息**"]
    for index, (label, key) in enumerate(GMP_REQUIRED_FIELDS, 1):
        lines.append(
            _field_line(index, label, key, recognized, aligned, warn_on_missing=True)
        )
    lines.extend(["", "**补充信息（选填）**"])
    for index, (label, key) in enumerate(GMP_OPTIONAL_FIELDS, 1):
        lines.append(
            _field_line(index, label, key, recognized, aligned, warn_on_missing=False)
        )
    lines.extend(["", GMP_MODIFY_HINT])

    value_base = {"scene": scene, "draft_id": draft_id}
    return build_card(
        title=GMP_CONFIRM_CARD_TITLE,
        template="orange",
        elements=[
            _md("\n".join(lines)),
            {"tag": "hr"},
            _confirm_cancel_buttons(
                value_base,
                confirm_label=CONFIRM_GMP_BUTTON_LABEL,
                cancel_label=CANCEL_GMP_BUTTON_LABEL,
            ),
        ],
    )


def _render_finished_receipt_confirm_card(draft: Any) -> dict[str, Any]:
    """成品入库登记确认卡片（scene=finished_receipt 分支，V3.0 §4.6）。

    识别/对话双入口共用：识别路径 recognized 携带置信度（⚠ 规则生效）、
    对话路径 aligned 即收集值（无置信度语义，⚠ 仅缺字段提醒）——_field_line
    的 aligned 覆盖优先机制天然兼容两形态。质量状态恒写「待检」以静态行
    提示（不占字段行）。多行登记（识别 rows 归组 >1 行）时按行展示提交集
    合（每行一条台账），标量字段以第一行为主。渲染防御同主入口，不抛错。
    """
    aligned = draft.aligned if isinstance(draft.aligned, dict) else {}
    recognized = draft.recognized if isinstance(draft.recognized, dict) else {}
    draft_no = _clean(getattr(draft, "draft_no", ""), 30)
    scene = str(getattr(draft, "scene", "") or FINISHED_RECEIPT_SCENE)
    draft_id = str(getattr(draft, "id", ""))

    from app.modules.warehouse.agent.pipeline.submit import (
        normalize_finished_receipt_rows,
    )

    try:
        rows = normalize_finished_receipt_rows(draft)
    except Exception:  # noqa: BLE001 — 归组失败按单行渲染降级
        rows = []
    multi = len(rows) > 1

    if multi:
        lines = [
            f"**草稿**：{draft_no or '-'}",
            "",
            f"**登记信息（共 {len(rows)} 行，按批号归组，每行一条台账）**",
        ]
        for index, row in enumerate(rows, start=1):
            lines.append(
                f"{index}. {row.get('product_name') or '-'}"
                f"　批 **{row.get('product_batch_no') or '-'}**："
                f"{row.get('quantity', '-')} {row.get('unit', '')}"
            )
        lines.extend(["", "**补充信息（以第一行为主）**"])
        for index, (label, key) in enumerate(FINISHED_RECEIPT_OPTIONAL_FIELDS, 1):
            lines.append(
                _field_line(index, label, key, recognized, aligned, warn_on_missing=False)
            )
        lines.extend(["", "**质量状态**：待检（每行默认，QC 判定后在台账改判）"])
        lines.extend([
            "",
            "💡 确认后**按行写入台账**；回复修改（如「数量改成 55」）仅调整"
            "第一行，其余行确认后请在台账调整。",
        ])
        value_base = {"scene": scene, "draft_id": draft_id}
        return build_card(
            title=FINISHED_RECEIPT_CONFIRM_CARD_TITLE,
            template="orange",
            elements=[
                _md("\n".join(lines)),
                {"tag": "hr"},
                _confirm_cancel_buttons(
                    value_base,
                    confirm_label=CONFIRM_FINISHED_RECEIPT_BUTTON_LABEL,
                    cancel_label=CANCEL_FINISHED_RECEIPT_BUTTON_LABEL,
                ),
            ],
        )

    lines = [f"**草稿**：{draft_no or '-'}", "", "**登记信息**"]
    for index, (label, key) in enumerate(FINISHED_RECEIPT_REQUIRED_FIELDS, 1):
        lines.append(
            _field_line(index, label, key, recognized, aligned, warn_on_missing=True)
        )
    lines.extend(["", "**补充信息（选填）**"])
    for index, (label, key) in enumerate(FINISHED_RECEIPT_OPTIONAL_FIELDS, 1):
        lines.append(
            _field_line(index, label, key, recognized, aligned, warn_on_missing=False)
        )
    lines.extend(["", "**质量状态**：待检（入库默认，QC 判定后在台账改判）"])
    lines.extend(["", FINISHED_RECEIPT_MODIFY_HINT])

    value_base = {"scene": scene, "draft_id": draft_id}
    return build_card(
        title=FINISHED_RECEIPT_CONFIRM_CARD_TITLE,
        template="orange",
        elements=[
            _md("\n".join(lines)),
            {"tag": "hr"},
            _confirm_cancel_buttons(
                value_base,
                confirm_label=CONFIRM_FINISHED_RECEIPT_BUTTON_LABEL,
                cancel_label=CANCEL_FINISHED_RECEIPT_BUTTON_LABEL,
            ),
        ],
    )


def _render_finished_confirm_card(draft: Any) -> dict[str, Any]:
    """成品出库登记确认卡片（scene=finished_outbound 分支，S3 ticket 02）。

    与 GMP 确认卡片同构（对话收集字段、无识别置信度语义，⚠ 规则仅保留
    缺字段提醒），字段集/文案换成成品口径。渲染防御同主入口：字段缺失
    降级，不抛错。
    """
    aligned = draft.aligned if isinstance(draft.aligned, dict) else {}
    recognized = draft.recognized if isinstance(draft.recognized, dict) else {}
    draft_no = _clean(getattr(draft, "draft_no", ""), 30)
    scene = str(getattr(draft, "scene", "") or FINISHED_OUTBOUND_SCENE)
    draft_id = str(getattr(draft, "id", ""))

    lines = [f"**草稿**：{draft_no or '-'}", "", "**登记信息**"]
    for index, (label, key) in enumerate(FINISHED_REQUIRED_FIELDS, 1):
        lines.append(
            _field_line(index, label, key, recognized, aligned, warn_on_missing=True)
        )
    lines.extend(["", "**补充信息（选填）**"])
    for index, (label, key) in enumerate(FINISHED_OPTIONAL_FIELDS, 1):
        lines.append(
            _field_line(index, label, key, recognized, aligned, warn_on_missing=False)
        )
    lines.extend(["", FINISHED_MODIFY_HINT])

    value_base = {"scene": scene, "draft_id": draft_id}
    return build_card(
        title=FINISHED_CONFIRM_CARD_TITLE,
        template="orange",
        elements=[
            _md("\n".join(lines)),
            {"tag": "hr"},
            _confirm_cancel_buttons(
                value_base,
                confirm_label=CONFIRM_FINISHED_BUTTON_LABEL,
                cancel_label=CANCEL_FINISHED_BUTTON_LABEL,
            ),
        ],
    )


def _render_picking_confirm_card(draft: Any) -> dict[str, Any]:
    """领料登记确认卡片（scene=picking_outbound 分支，V3.0 分期C）。

    与 GMP 确认卡片同构（对话收集字段、无识别置信度语义），额外渲染
    FIFO 建议批次列表（跨批拆分逐行：批号 x 承担量 / 库存量 / 贮存位置）。
    渲染防御同主入口：字段缺失降级，不抛错。
    """
    aligned = draft.aligned if isinstance(draft.aligned, dict) else {}
    recognized = draft.recognized if isinstance(draft.recognized, dict) else {}
    draft_no = _clean(getattr(draft, "draft_no", ""), 30)
    scene = str(getattr(draft, "scene", "") or PICKING_OUTBOUND_SCENE)
    draft_id = str(getattr(draft, "id", ""))

    lines = [f"**草稿**：{draft_no or '-'}", "", "**登记信息**"]
    for index, (label, key) in enumerate(PICKING_REQUIRED_FIELDS, 1):
        lines.append(
            _field_line(index, label, key, recognized, aligned, warn_on_missing=True)
        )
    lines.extend(["", "**补充信息（选填）**"])
    for index, (label, key) in enumerate(PICKING_OPTIONAL_FIELDS, 1):
        lines.append(
            _field_line(index, label, key, recognized, aligned, warn_on_missing=False)
        )

    # FIFO 建议批次（picking_plan 结构化快照；用户改批号后由工具侧重算覆盖）
    plan = aligned.get("picking_plan")
    if isinstance(plan, list) and plan:
        lines.extend(["", "**FIFO 批次建议**（最早放行批次优先）"])
        for item in plan:
            if not isinstance(item, dict):
                continue
            batch = _clean(item.get("batch_no"), 40)
            pick = item.get("pick_qty")
            pick_text = f"{pick:g}" if isinstance(pick, (int, float)) else "-"
            stock = item.get("stock_qty")
            stock_text = f"{stock:g}" if isinstance(stock, (int, float)) else "-"
            location = _clean(item.get("location"), 30)
            lines.append(
                f"- {batch}：领 {pick_text}（库存 {stock_text} {item.get('unit') or ''}，{location}）"
            )
    warning = str(aligned.get("picking_warning") or "").strip()
    if warning:
        lines.extend(["", f"⚠ {warning}"])

    lines.extend(["", PICKING_MODIFY_HINT])

    value_base = {"scene": scene, "draft_id": draft_id}
    return build_card(
        title=PICKING_CONFIRM_CARD_TITLE,
        template="orange",
        elements=[
            _md("\n".join(lines)),
            {"tag": "hr"},
            _confirm_cancel_buttons(
                value_base,
                confirm_label=CONFIRM_PICKING_BUTTON_LABEL,
                cancel_label=CANCEL_PICKING_BUTTON_LABEL,
            ),
        ],
    )


def render_confirm_status_card(
    draft: Any, *, state: str, title: str
) -> dict[str, Any]:
    """确认卡片的状态更新视图（PATCH 原卡）：登记中 / 已确认 / 已取消 / 失败。

    state: processing（登记中）/ done（已登记）/ cancelled（已取消）/
    failed（失败）。字段清单沿用 render_receipt_confirm_card 的正文结构，
    按钮区按状态替换（processing=无按钮，done/cancelled/failed=状态说明）。
    """
    confirm_card = render_receipt_confirm_card(draft)
    status_line = {
        "processing": "⏳ **已确认，正在登记…**",
        "done": "✅ **已确认，登记完成**（结果见下方回执）",
        "cancelled": "❌ **已取消**",
        "failed": "⚠️ **登记未完成**（详见下方失败回执）",
    }.get(state, f"状态：{state}")
    elements = [
        {"tag": "markdown", "content": status_line},
    ]
    # 保留字段清单，移除确认/取消按钮行（2.0 按钮行=column_set）与确认引导
    # 行——状态卡不再提供操作入口，防止重复登记/取消（后端状态机同样拦截）
    for el in confirm_card.get("body", {}).get("elements", []):
        if el.get("tag") == "column_set":
            continue
        content = str(el.get("content") or "")
        if "💡 确认前请核对" in content:
            content = content.split("💡 确认前请核对")[0].rstrip("；;。 \n")
        if content:
            elements.append({"tag": "markdown", "content": content})
    return {
        "schema": CARD_SCHEMA,
        "config": {"update_multi": True},
        "header": {"title": {"tag": "plain_text", "content": title}, "template": "blue"},
        "body": {"elements": elements},
    }


def render_receipt_confirm_card(draft: Any) -> dict[str, Any]:
    """登记确认卡片（pipeline.draft_flow.send_confirm_card 发送）。

    draft 为 warehouse_agent_drafts 行（或同构对象）。按 draft.scene 分发：
    gmp_outbound → :func:`_render_gmp_confirm_card`（对话收集字段，无识别
    置信度/物料对齐段）；finished_outbound →
    :func:`_render_finished_confirm_card`（成品口径，同对话收集形态）；
    其余（receipt 及缺省）→ 入库识别卡片（13 字段 value/confidence +
    aligned 对齐字段）。

    入库识别形态：必提/选提分区 + 低置信度 ⚠ + 物料对齐行 + [✅ 确认入库]
    [❌ 取消] 按钮（value={scene, action, draft_id}，gateway 按 scene 分发到
    confirm.handle_action）。渲染防御：recognized/aligned 缺字段或整段缺失
    一律降级，不抛错。
    """
    scene = str(getattr(draft, "scene", "") or "receipt")
    if scene == GMP_OUTBOUND_SCENE:
        return _render_gmp_confirm_card(draft)
    if scene == FINISHED_OUTBOUND_SCENE:
        return _render_finished_confirm_card(draft)
    if scene == PICKING_OUTBOUND_SCENE:
        return _render_picking_confirm_card(draft)
    if scene == FINISHED_RECEIPT_SCENE:
        return _render_finished_receipt_confirm_card(draft)
    recognized = draft.recognized if isinstance(draft.recognized, dict) else {}
    aligned = draft.aligned if isinstance(draft.aligned, dict) else {}
    draft_no = _clean(getattr(draft, "draft_no", ""), 30)
    draft_id = str(getattr(draft, "id", ""))

    lines = [f"**草稿**：{draft_no or '-'}", ""]
    lines.append("**必提信息**")
    for index, (label, key) in enumerate(RECEIPT_REQUIRED_FIELDS, 1):
        lines.append(
            _field_line(index, label, key, recognized, aligned, warn_on_missing=True)
        )
    lines.append("")
    lines.append("**选填信息**")
    for index, (label, key) in enumerate(RECEIPT_OPTIONAL_FIELDS, 1):
        lines.append(
            _field_line(index, label, key, recognized, aligned, warn_on_missing=False)
        )
    aligned_text = _aligned_line(aligned)
    if aligned_text:
        lines.extend(["", aligned_text])
    lines.extend(["", RECEIPT_MODIFY_HINT])

    value_base = {"scene": scene, "draft_id": draft_id}
    return build_card(
        title=RECEIPT_CONFIRM_CARD_TITLE,
        template="orange",
        elements=[
            _md("\n".join(lines)),
            {"tag": "hr"},
            _confirm_cancel_buttons(
                value_base,
                confirm_label=CONFIRM_RECEIPT_BUTTON_LABEL,
                cancel_label=CANCEL_RECEIPT_BUTTON_LABEL,
            ),
        ],
    )


# ── 8. 登记回执卡片（S2 ticket 04：submit 结果 + 读回核对 + 降级提示；
#      S3 ticket 01：scene=gmp_outbound 分支标题/文案；S3 ticket 02：
#      scene=finished_outbound 分支标题/文案）──

# 卡片标题（submit 读回核对一致 / 不一致两种形态）
RECEIPT_RESULT_CARD_TITLE_OK = "✅ 入库已登记"
RECEIPT_RESULT_CARD_TITLE_MISMATCH = "⚠ 入库已登记（读回不一致）"

# GMP 出库回执标题（scene=gmp_outbound 分支）
GMP_RESULT_CARD_TITLE_OK = "✅ GMP 出库已登记"
GMP_RESULT_CARD_TITLE_MISMATCH = "⚠ GMP 出库已登记（读回不一致）"

# 成品出库回执标题（scene=finished_outbound 分支，S3 ticket 02）
FINISHED_RESULT_CARD_TITLE_OK = "✅ 成品出库已登记"
FINISHED_RESULT_CARD_TITLE_MISMATCH = "⚠ 成品出库已登记（读回不一致）"

# 领料回执标题（scene=picking_outbound 分支，V3.0 分期C）
PICKING_RESULT_CARD_TITLE_OK = "✅ 领料已登记"
PICKING_RESULT_CARD_TITLE_MISMATCH = "⚠ 领料已登记（读回不一致）"

# 成品入库回执标题（scene=finished_receipt 分支，V3.0 §4.6）
FINISHED_RECEIPT_RESULT_CARD_TITLE_OK = "✅ 成品入库已登记"
FINISHED_RECEIPT_RESULT_CARD_TITLE_MISMATCH = "⚠ 成品入库已登记（读回不一致）"

# 读回核对一致提示行（按 scene 的核对字段口径）
RECEIPT_CHECK_OK_LINE = "✅ 数量/批号/单位/供应商 与 Base 读回一致"
GMP_CHECK_OK_LINE = "✅ 批号/数量/单位 与 Base 读回一致"
FINISHED_CHECK_OK_LINE = "✅ 批号/出库量/单位/客户 与 Base 读回一致"
PICKING_CHECK_OK_LINE = "✅ 批号/领用数量/领用部门 与 Base 读回一致"
FINISHED_RECEIPT_CHECK_OK_LINE = "✅ 产品/批号/数量/单位 与 Base 读回一致"

# 领料批号降级提示（选项集未命中需人工补填，同 GMP 口径）
PICKING_DEGRADE_BATCH_HINT = "⚠ 物料批号需在 Base 人工补填（选项集未命中）"

# 成品入库品规降级提示（品规单选选项集未命中需人工补填）
FINISHED_RECEIPT_DEGRADE_SPEC_HINT = "⚠ 品规需在 Base 人工补填（选项集未命中）"

# GMP 物料批号写入 API 专用文本字段（2026-09-07 新建；原单选字段
# 入——Base 侧字段编辑限制，放开后置 True 提示随之消失）
GMP_DEGRADE_BATCH_HINT = (
    "⚠ 物料批号需在 Base 人工补填（Base 侧字段编辑限制，放开后自动写入）"
)

# 物料名称降级提示（spec Implementation Decisions 6：测试版该字段重复选项
# 未治理，submit 跳过写入——治理后移除降级，提示随之消失）
RECEIPT_DEGRADE_MATERIAL_HINT = (
    "⚠ 物料名称需在 Base 人工补选（选项重复问题，治理后自动写入）"
)

# 成品快递号降级提示（S3 ticket 02：附件字段 type 17 写入需 file_token，
# 快递号写入 API 专用文本字段（原字段为附件类型 type 17）
# 开关注释；快递号仍用于推送卡片内容）
FINISHED_DEGRADE_EXPRESS_HINT = (
    "⚠ 快递号需在 Base 人工补填（附件字段，文本快递单号无法自动写入）"
)

# 写入字段摘要/核对结果行的单元格截断
_RESULT_VALUE_MAX = 30


def _fmt_ts_value(value: Any) -> str:
    """写入字段展示值格式化：毫秒时间戳转日期；附件（file_token dict/list）
    显示为「📎 附件已上传」而非原始 token。"""
    if isinstance(value, dict) and "file_token" in value:
        return "📎 附件已上传"
    if isinstance(value, list) and value and isinstance(value[0], dict) and "file_token" in value[0]:
        return f"📎 附件已上传（{len(value)} 个）"
    if isinstance(value, int) and not isinstance(value, bool) and value > 10**12:
        try:
            from datetime import datetime as _dt

            return _dt.fromtimestamp(value / 1000).strftime("%Y-%m-%d")
        except (OSError, OverflowError, ValueError):
            return str(value)
    return str(value) if value is not None else "-"


def _base_record_link(draft: Any, record_id: str) -> str:
    """多维表格记录直达链接（租户域名 + app_token/table/record 三元组）。"""
    app_token = str(getattr(draft, "target_base", "") or "")
    table_id = str(getattr(draft, "target_table", "") or "")
    if app_token and table_id:
        return (
            f"https://j0eukrlohu.feishu.cn/base/{app_token}"
            f"?table={table_id}&record={record_id}"
        )
    return ""


def render_receipt_result_card(
    draft: Any, check_result: dict[str, Any]
) -> dict[str, Any]:
    """登记回执卡片（pipeline.submit.submit_receipt / submit_gmp /
    submit_outbound 发送，dry-run 可捕获）。标题与核对文案按 draft.scene
    分支（gmp_outbound → GMP 出库标题 / finished_outbound → 成品出库标题），
    正文结构三场景共用。

    check_result 由 submit_receipt/submit_gmp/submit_outbound 构造：
    - consistent：bool，读回核对是否一致；
    - mismatches：[{field, written, read_back}]（规范化文本后的不一致项）；
    - written：{Base 字段名: 写入值}（展示摘要）；
    - record_id：Base 记录 id；degraded：[未写入字段名]（降级/选项集不匹配）。

    渲染：标题按 consistent 分「✅ …已登记」（green）/「⚠ …已登记
    （读回不一致）」（red）；正文 = 草稿号 + Base 记录 id + 写入字段摘要 +
    读回核对结果（✅ 关键字段一致 / ⚠ 写入值 vs 读回值对照行）+ 降级提示。
    渲染防御同其他卡片：check_result 缺键/畸形一律按空值降级，不抛错。
    """
    draft_no = _clean(getattr(draft, "draft_no", ""), 30)
    scene = str(getattr(draft, "scene", "") or "receipt")
    # 各 scene 分支配置：回执标题/核对一致行/专属降级字段与提示（receipt 缺省）
    if scene == GMP_OUTBOUND_SCENE:
        title_ok = GMP_RESULT_CARD_TITLE_OK
        title_mismatch = GMP_RESULT_CARD_TITLE_MISMATCH
        check_ok_line = GMP_CHECK_OK_LINE
        special_field, special_hint = "物料批号", GMP_DEGRADE_BATCH_HINT
    elif scene == FINISHED_OUTBOUND_SCENE:
        title_ok = FINISHED_RESULT_CARD_TITLE_OK
        title_mismatch = FINISHED_RESULT_CARD_TITLE_MISMATCH
        check_ok_line = FINISHED_CHECK_OK_LINE
        special_field, special_hint = "快递号", FINISHED_DEGRADE_EXPRESS_HINT
    elif scene == PICKING_OUTBOUND_SCENE:
        title_ok = PICKING_RESULT_CARD_TITLE_OK
        title_mismatch = PICKING_RESULT_CARD_TITLE_MISMATCH
        check_ok_line = PICKING_CHECK_OK_LINE
        special_field, special_hint = "物料批号", PICKING_DEGRADE_BATCH_HINT
    elif scene == FINISHED_RECEIPT_SCENE:
        title_ok = FINISHED_RECEIPT_RESULT_CARD_TITLE_OK
        title_mismatch = FINISHED_RECEIPT_RESULT_CARD_TITLE_MISMATCH
        check_ok_line = FINISHED_RECEIPT_CHECK_OK_LINE
        special_field, special_hint = "品规", FINISHED_RECEIPT_DEGRADE_SPEC_HINT
    else:
        title_ok = RECEIPT_RESULT_CARD_TITLE_OK
        title_mismatch = RECEIPT_RESULT_CARD_TITLE_MISMATCH
        check_ok_line = RECEIPT_CHECK_OK_LINE
        special_field, special_hint = "物料名称", RECEIPT_DEGRADE_MATERIAL_HINT
    check = check_result if isinstance(check_result, dict) else {}
    consistent = bool(check.get("consistent"))
    record_id = _clean(check.get("record_id"), 40)

    lines = [f"**草稿**：{draft_no or '-'}"]
    if record_id != "-":
        link = _base_record_link(draft, record_id)
        lines.append(
            f"**多维表格记录**：[{record_id}]({link})" if link else f"**记录 ID**：{record_id}"
        )

    written = check.get("written")
    if isinstance(written, dict) and written:
        lines.extend(["", "**写入字段**"])
        for index, (name, value) in enumerate(written.items(), 1):
            lines.append(
                f"{index}. {_clean(name, 24)}："
                f"{_clean(_fmt_ts_value(value), _RESULT_VALUE_MAX)}"
            )

    lines.extend(["", "**读回核对**"])
    mismatches = [
        item for item in (check.get("mismatches") or []) if isinstance(item, dict)
    ]
    if consistent:
        lines.append(check_ok_line)
    elif mismatches:
        for item in mismatches:
            lines.append(
                f"⚠ {_clean(item.get('field'), 24)}："
                f"写入 {_clean(item.get('written'), _RESULT_VALUE_MAX)}"
                f" ≠ 读回 {_clean(item.get('read_back'), _RESULT_VALUE_MAX)}"
            )
    else:
        lines.append("⚠ 读回核对异常（无明细）")

    degraded = [str(name) for name in (check.get("degraded") or [])]
    # 场景专属降级字段（receipt=物料名称 / gmp=物料批号 / finished=快递号）
    # 走专属提示行，不落入「选项集不匹配」通用行
    if special_field in degraded:
        lines.extend(["", special_hint])
    skipped = [name for name in degraded if name != special_field]
    if skipped:
        lines.append(
            f"ℹ️ 未写入（选项集不匹配，需人工补填）：{_clean('、'.join(skipped), 80)}"
        )

    title = title_ok if consistent else title_mismatch
    return build_card(
        title=title,
        template="green" if consistent else "red",
        elements=[_md("\n".join(lines))],
    )


# ── 主入口：Reply → 卡片 ──

_RENDERERS = {
    "query_stock": render_stock_card,
    "query_material": render_material_card,
    "query_movements": render_movements_card,
    "query_report": render_report_card,
}


def render_reply_card(
    reply: Reply, session: WarehouseAgentSession | None = None
) -> dict[str, Any]:
    """Runner Reply → 交互卡片（gateway 结果卡片入口，ticket 04）。

    - Reply.data = {"tool": 工具名, "result": 结果 dict}（runner 工具循环
      填充）→ 命中已知工具渲染专用卡片；
    - 渲染异常 / 无 data / 未知工具 / result 非 dict → render_text_card
      （title=仓储助手），永不抛错。
    session 参数预留（S2 卡片 patch / 上下文展示），当前不参与渲染。
    """
    data = reply.data
    if isinstance(data, dict):
        renderer = _RENDERERS.get(str(data.get("tool") or ""))
        result = data.get("result")
        if renderer is not None and isinstance(result, dict):
            try:
                return renderer(result, reply_text=reply.text or "")
            except Exception:  # noqa: BLE001 — 渲染兜底：任何异常降级文本卡片
                logger.exception(
                    "仓库 Agent 专用卡片渲染失败，降级文本卡片: tool=%s",
                    data.get("tool"),
                )
    return render_text_card(TEXT_CARD_TITLE, reply.text or "")
