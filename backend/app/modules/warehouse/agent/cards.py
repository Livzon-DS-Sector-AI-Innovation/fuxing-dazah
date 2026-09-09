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
    return _build_card(title=title, template="blue", elements=[_md(markdown or "")])


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


def render_material_card(
    data: dict[str, Any], *, reply_text: str = ""
) -> dict[str, Any]:
    """物料主数据卡片：单条块式全字段，多条行式精选列表格。"""
    rows = _list_rows(data)
    elements = _summary_elements(reply_text)
    if not rows:
        elements.append(
            _md("未查询到符合条件的物料主数据。\n可换个名称/代码关键词试试。")
        )
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


def render_movements_card(
    data: dict[str, Any], *, reply_text: str = ""
) -> dict[str, Any]:
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
        elements.append(
            _md("未查询到符合条件的出入库记录。\n可放宽日期范围或换物料关键词试试。")
        )
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
                        "text": {
                            "tag": "plain_text",
                            "content": CONFIRM_SEND_BUTTON_LABEL,
                        },
                        "type": "primary",
                        "value": {**value_base, "action": "confirm"},
                    },
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": CANCEL_SEND_BUTTON_LABEL,
                        },
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
    """物料对齐行：none → 未匹配警告；非 none → 标准名+代码+大类（缺字段降级）。"""
    match = str(aligned.get("match_confidence") or "")
    if match == "none":
        return "⚠ 物料名称未匹配主数据，请核对"
    if not match and not aligned:
        return ""  # aligned 缺失（防御）：整段降级省略
    name = _clean(aligned.get("material_name"), 60)
    code = _clean(aligned.get("code"), 30)
    category = _clean(aligned.get("material_category"), 20)
    return f"**物料对齐**：{name}（代码 {code}｜大类 {category}）"


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
    return _build_card(
        title=GMP_CONFIRM_CARD_TITLE,
        template="orange",
        elements=[
            _md("\n".join(lines)),
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": CONFIRM_GMP_BUTTON_LABEL,
                        },
                        "type": "primary",
                        "value": {**value_base, "action": "confirm"},
                    },
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": CANCEL_GMP_BUTTON_LABEL,
                        },
                        "value": {**value_base, "action": "cancel"},
                    },
                ],
            },
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
    return _build_card(
        title=FINISHED_CONFIRM_CARD_TITLE,
        template="orange",
        elements=[
            _md("\n".join(lines)),
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": CONFIRM_FINISHED_BUTTON_LABEL,
                        },
                        "type": "primary",
                        "value": {**value_base, "action": "confirm"},
                    },
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": CANCEL_FINISHED_BUTTON_LABEL,
                        },
                        "value": {**value_base, "action": "cancel"},
                    },
                ],
            },
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
    # 保留原卡片的字段清单（确认卡正文 index 0），去掉按钮与引导行
    for el in confirm_card.get("elements", []):
        content = str(el.get("content") or "")
        if "确认前请核对" in content or "确认登记" in content:
            continue
        elements.append(el)
    return {
        "config": {"update_multi": True},
        "header": {"title": {"tag": "plain_text", "content": title}, "template": "blue"},
        "elements": elements,
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
    return _build_card(
        title=RECEIPT_CONFIRM_CARD_TITLE,
        template="orange",
        elements=[
            _md("\n".join(lines)),
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": CONFIRM_RECEIPT_BUTTON_LABEL,
                        },
                        "type": "primary",
                        "value": {**value_base, "action": "confirm"},
                    },
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": CANCEL_RECEIPT_BUTTON_LABEL,
                        },
                        "value": {**value_base, "action": "cancel"},
                    },
                ],
            },
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

# 读回核对一致提示行（按 scene 的核对字段口径）
RECEIPT_CHECK_OK_LINE = "✅ 数量/批号/单位/供应商 与 Base 读回一致"
GMP_CHECK_OK_LINE = "✅ 批号/数量/单位 与 Base 读回一致"
FINISHED_CHECK_OK_LINE = "✅ 批号/出库量/单位/客户 与 Base 读回一致"

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
    """写入字段展示值格式化：毫秒时间戳（飞书 datetime 写入契约）转 YYYY-MM-DD。"""
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
    return _build_card(
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
