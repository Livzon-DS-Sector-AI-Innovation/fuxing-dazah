"""仓储 Agent 查询结果卡片渲染器（S1 ticket 04）。

Runner 的 Reply → 飞书交互卡片。卡片为旧版 interactive 结构
（config/header/elements，与 gateway._build_card 同构），
``notification.send_card`` / ``send_card_to_user`` 直接可发。

渲染策略（ticket 04）：
- Reply.data 携带结构化工具结果（runner 工具循环填充：最后使用的工具名 +
  原始结果 dict，见 runner.Reply 注释）→ 按工具名分发专用卡片：
  query_stock → 库存卡片（批号/剩余数量/单位/库位/三态列）；
  query_material → 物料主数据卡片（单条块式全字段 / 多条行式表格）；
  query_movements → 出入库汇总卡片（方向聚合 + 明细表）；
  query_report → 呆料/不合格清单卡片（report_type 区分标题）；
- 无 data / 未知工具 / result 非 dict → ``render_text_card`` 文本卡片兜底
  （即票02 的「仓储助手」markdown 卡片行为）；
- 渲染防御：任何渲染异常降级文本卡片，**永不因渲染抛错中断回复**。

lark_md 约定：旧版卡片 markdown 元素不支持表格语法，表格用「全角｜分隔的
行式伪表格」呈现（表头行 + 序号数据行，\n 换行）；单元格统一经 ``_clean``
清洗（去 markdown 特殊字符/换行、超长截断，空值显示 -），防止数据内容
破坏排版或撑爆卡片体积。明细默认前 10 条（对齐工具层 DETAIL_LIMIT），
超出追加「共 N 条，回复「更多」查看」提示（S1 不做真分页，仅提示）。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.modules.warehouse.agent.runner import Reply
from app.modules.warehouse.models import WarehouseAgentSession

logger = logging.getLogger(__name__)

# 兜底文本卡片标题（与 gateway 票02 行为一致）
TEXT_CARD_TITLE = "仓储助手"

# 明细最多展示行数（对齐 tools/query.py 的 DETAIL_LIMIT）
MAX_DETAIL_ROWS = 10

# LLM 文字回复在专用卡片顶部的截断长度（超出以 … 结尾）
REPLY_TEXT_MAX = 600

# 单元格默认截断长度 / note 截断长度
_CELL_MAX = 40
_NOTE_MAX = 200

# 库存卡片表头（全角分隔行式伪表格；测试断言用）
STOCK_TABLE_HEADER = "物料｜批号｜剩余数量｜单位｜库位｜三态"

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


def _build_card(
    *, title: str, template: str, elements: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": template,
        },
        "elements": elements,
    }


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
    """专用卡片顶部的 LLM 文字回复（保留其总结价值），后随分割线。"""
    text = (reply_text or "").strip()
    if not text:
        return []
    return [_md(_clip(text, REPLY_TEXT_MAX)), {"tag": "hr"}]


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


def _generic_table(rows: list[dict[str, Any]], max_rows: int = MAX_DETAIL_ROWS) -> str:
    """通用行式伪表格：列取首条记录的键（工具输出的中文键即展示名）。"""
    if not rows:
        return ""
    columns = [str(key) for key in rows[0].keys()]
    lines = ["｜".join(columns)]
    for index, rec in enumerate(rows[:max_rows], 1):
        lines.append(f"{index}. " + "｜".join(_clean(rec.get(col)) for col in columns))
    return "\n".join(lines)


# ── 兜底文本卡片（票02 行为保持）──


def render_text_card(title: str, markdown: str) -> dict[str, Any]:
    """通用 markdown 文本卡片（无结构化数据/渲染降级时的兜底）。"""
    return _build_card(
        title=title, template="blue", elements=[_md(markdown or "")]
    )


# ── 1. 库存卡片 ──

_EMPTY_STOCK_TEXT = (
    "未查询到符合条件的库存记录。\n"
    "可换个关键词试试，或放宽筛选条件（如不限 QA 放行状态 / 临期范围）。"
)


def _stock_row(index: int, rec: dict[str, Any]) -> str:
    qty = _clean(rec.get("剩余数量"), 16)
    cells = [
        _clean(rec.get("物料名称")),
        _clean(rec.get("物料批号")),
        f"**{qty}**" if qty != "-" else qty,
        _clean(rec.get("单位"), 10),
        _clean(rec.get("贮存位置"), 24),
        _status_mark(_clean(rec.get("QA放行"), 10)),
    ]
    return f"{index}. " + "｜".join(cells)


def _stock_table(rows: list[dict[str, Any]], total: int | None) -> str:
    lines = [STOCK_TABLE_HEADER]
    for index, rec in enumerate(rows[:MAX_DETAIL_ROWS], 1):
        lines.append(_stock_row(index, rec))
    hint = _truncation_hint(total, min(len(rows), MAX_DETAIL_ROWS))
    if hint:
        lines.append(hint)
    return "\n".join(lines)


def render_stock_card(data: dict[str, Any], *, reply_text: str = "") -> dict[str, Any]:
    """库存查询结果卡片：批号/剩余数量/单位/库位/三态。"""
    rows = _list_rows(data)
    elements = _summary_elements(reply_text)
    if not rows:
        elements.append(_md(_EMPTY_STOCK_TEXT))
        return _build_card(title="📦 库存查询", template="blue", elements=elements)
    elements.append({"tag": "hr"})
    elements.append(_md(_stock_table(rows, _total_of(data))))
    note = _note_of(data)
    if note:
        elements.extend(_note_elements(note))
    return _build_card(title="📦 库存查询", template="blue", elements=elements)


# ── 2. 物料主数据卡片 ──

_MATERIAL_TABLE_HEADER = "物料｜代码｜级别｜规格｜大类｜生产商"
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


def render_material_card(data: dict[str, Any], *, reply_text: str = "") -> dict[str, Any]:
    """物料主数据卡片：单条块式全字段，多条行式精选列表格。"""
    rows = _list_rows(data)
    elements = _summary_elements(reply_text)
    if not rows:
        elements.append(_md("未查询到符合条件的物料主数据。\n可换个名称/代码关键词试试。"))
        return _build_card(title="🧪 物料信息", template="blue", elements=elements)
    elements.append({"tag": "hr"})
    if len(rows) == 1:
        elements.append(_md(_material_block(1, rows[0])))
        shown = 1
    else:
        lines = [_MATERIAL_TABLE_HEADER]
        for index, rec in enumerate(rows[:MAX_DETAIL_ROWS], 1):
            cells = [
                _clean(rec.get("物料名称")),
                _clean(rec.get("代码"), 20),
                _clean(rec.get("级别"), 16),
                _clean(rec.get("规格"), 24),
                _clean(rec.get("物料大类"), 16),
                _clean(rec.get("生产商"), 24),
            ]
            lines.append(f"{index}. " + "｜".join(cells))
        shown = min(len(rows), MAX_DETAIL_ROWS)
        elements.append(_md("\n".join(lines)))
    hint = _truncation_hint(_total_of(data), shown)
    if hint:
        elements.append(_md(hint))
    note = _note_of(data)
    if note:
        elements.extend(_note_elements(note))
    return _build_card(title="🧪 物料信息", template="blue", elements=elements)


# ── 3. 出入库汇总卡片 ──


def _movement_section_lines(heading: str, rows: Any) -> list[str]:
    """单方向汇总节：`📥 入库汇总` + 聚合行（物料｜数量 单位）。"""
    if not isinstance(rows, list) or not rows:
        return []
    dict_rows = _dict_rows(rows)
    if not dict_rows:
        return []
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
    return lines


def _movement_detail_lines(heading: str, rows: Any) -> list[str]:
    """单方向明细节：`📥 入库明细` + 通用表格 + 记录数提示。"""
    if not isinstance(rows, list) or not rows:
        return []
    dict_rows = _dict_rows(rows)
    if not dict_rows:
        return []
    icon = "📥" if "入库" in heading else "📤" if "出库" in heading else "•"
    table = _generic_table(dict_rows)
    if not table:
        return []
    return [f"{icon} **{heading}**", table]


def render_movements_card(data: dict[str, Any], *, reply_text: str = "") -> dict[str, Any]:
    """出入库总账卡片：按方向的聚合汇总数字 + 明细表。"""
    elements = _summary_elements(reply_text)
    body: list[str] = []
    summary = _list_field(data, "summary")
    records = _list_field(data, "records")
    for section in summary:
        if isinstance(section, dict):
            for heading, rows in section.items():
                body.extend(_movement_section_lines(str(heading), rows))
    for section in records:
        if isinstance(section, dict):
            for heading, rows in section.items():
                body.extend(_movement_detail_lines(str(heading), rows))
    if not body:
        elements.append(_md("未查询到符合条件的出入库记录。\n可放宽日期范围或换物料关键词试试。"))
        return _build_card(title="🔄 出入库汇总", template="blue", elements=elements)
    total = _total_of(data)
    if total is not None and total > MAX_DETAIL_ROWS:
        body.append(_truncation_hint(total, MAX_DETAIL_ROWS))
    elements.append({"tag": "hr"})
    elements.append(_md("\n\n".join(body)))
    note = _note_of(data)
    if note:
        elements.extend(_note_elements(note))
    return _build_card(title="🔄 出入库汇总", template="blue", elements=elements)


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
        return _build_card(title=title, template=template, elements=elements)
    elements.append({"tag": "hr"})
    elements.append(_md(_generic_table(rows)))
    hint = _truncation_hint(_total_of(data), min(len(rows), MAX_DETAIL_ROWS))
    if hint:
        elements.append(_md(hint))
    note = _note_of(data)
    if note:
        elements.extend(_note_elements(note))
    return _build_card(title=title, template=template, elements=elements)


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
    return _build_card(
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
    return _build_card(
        title=SEND_PREVIEW_CARD_TITLE,
        template="orange",
        elements=[
            _md("\n".join(lines)),
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": CONFIRM_SEND_BUTTON_LABEL},
                        "type": "primary",
                        "value": {**value_base, "action": "confirm"},
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": CANCEL_SEND_BUTTON_LABEL},
                        "value": {**value_base, "action": "cancel"},
                    },
                ],
            },
        ],
    )


def render_outgoing_card(title: str, content: str) -> dict[str, Any]:
    """确认后真正外发的卡片（send_card 工具的最终投递内容）。"""
    return _build_card(
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
    return _build_card(
        title=REMINDER_CARD_TITLE, template="yellow", elements=[_md("\n".join(lines))]
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
                    "仓库 Agent 专用卡片渲染失败，降级文本卡片: tool=%s", data.get("tool")
                )
    return render_text_card(TEXT_CARD_TITLE, reply.text or "")
