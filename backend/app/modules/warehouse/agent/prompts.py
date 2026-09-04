"""仓储 Agent 系统提示词（S1 ticket 03，V1.0-2.E 三段式）。

三段结构：
1. 角色与规则 —— 数字必须来自工具结果、禁止编造、不确定追问、工具优先；
2. 字段字典 —— 核心表关键字段与单选选项摘要，从 ``bitable_schema`` 常量
   生成（单一事实来源，快照更新后提示词自动跟随）；
3. 工具使用规则 —— 查询工具与 Harness 工具的适用场景与参数说明。

长期记忆段（票 06）：``build_system_prompt(owner_open_id)`` 传入用户
open_id 时拉取该用户偏好 top3 + 全局惯例/别名 top5（``tools.memory.
inject_context``）注入；记忆规则段常驻（无记忆也要引导 Agent 显式纠正时
调 save_memory）。红线：记忆只影响表达与默认参数，数字永远来自工具结果。

技能目录注入（票 08）：``build_system_prompt(...)`` 默认从技能注册表
（``skills.registry.default_registry.catalog_markdown()``）生成目录注入
「## 五、可用技能」段（一行一技能：名称+触发描述，附使用规则：任务匹配
技能描述时先 load_skill 再按 SOP 步骤执行）；显式传 ``skill_catalog=""``
可禁用注入（回归口径），传非空文本则原样使用。
"""

from __future__ import annotations

from datetime import date

from app.modules.warehouse.agent.skills.registry import default_registry
from app.modules.warehouse.agent.tools.memory import inject_context
from app.modules.warehouse.bitable_schema import (
    FIELD_TYPE_ATTACHMENT,
    FIELD_TYPE_AUTO_NUMBER,
    FIELD_TYPE_CHECKBOX,
    FIELD_TYPE_CREATED_TIME,
    FIELD_TYPE_CREATED_USER,
    FIELD_TYPE_DATETIME,
    FIELD_TYPE_FORMULA,
    FIELD_TYPE_LINK,
    FIELD_TYPE_LOOKUP,
    FIELD_TYPE_MODIFIED_TIME,
    FIELD_TYPE_MODIFIED_USER,
    FIELD_TYPE_MULTI_SELECT,
    FIELD_TYPE_NUMBER,
    FIELD_TYPE_SELECT,
    FIELD_TYPE_TEXT,
    FIELD_TYPE_USER,
    TABLES,
)

_TYPE_NAMES: dict[int, str] = {
    FIELD_TYPE_TEXT: "文本",
    FIELD_TYPE_NUMBER: "数字",
    FIELD_TYPE_SELECT: "单选",
    FIELD_TYPE_MULTI_SELECT: "多选",
    FIELD_TYPE_DATETIME: "日期",
    FIELD_TYPE_CHECKBOX: "勾选",
    FIELD_TYPE_USER: "人员",
    FIELD_TYPE_ATTACHMENT: "附件",
    FIELD_TYPE_LINK: "关联",
    FIELD_TYPE_LOOKUP: "引用",
    FIELD_TYPE_FORMULA: "公式",
    FIELD_TYPE_MODIFIED_TIME: "修改时间",
    FIELD_TYPE_CREATED_TIME: "创建时间",
    FIELD_TYPE_MODIFIED_USER: "修改人",
    FIELD_TYPE_CREATED_USER: "创建人",
    FIELD_TYPE_AUTO_NUMBER: "自动编号",
}

# 字段字典收录的核心表与关键字段（其余字段工具按需返回，不进提示词）
_DICTIONARY_TABLES: list[tuple[str, str, list[str]]] = [
    # (table_key, 别名说明, 收录字段)
    ("material_stock", "当前在库批次明细", [
        "物料名称", "物料批号", "剩余数量", "单位", "贮存/槽车取样点",
        "QA放行", "入库日期", "有效期至/复验期至",
    ]),
    ("material_master", "物料主数据（名称代码一览）", [
        "代码", "物料名称", "级别", "飞书规格", "物料大类", "单位换算",
        "生产商", "免检物料", "复验期",
    ]),
    ("material_receipt", "入库总账", [
        "物料名称", "物料批号", "入库数量", "单位", "入库日期",
        "QA放行", "贮存/槽车取样点", "呆料判断",
    ]),
    ("material_outbound", "出库总账（领用）", [
        "物料名称", "物料批号", "出库数量", "单位", "领用日期",
        "领用部门", "领用类型",
    ]),
    ("unqualified_stock", "不合格物料汇总", [
        "物料名称", "不合格项目", "处理方式", "到货日期", "登记人",
    ]),
]

_MAX_OPTIONS_SHOWN = 8


def _render_field_dictionary() -> str:
    """从 bitable_schema TABLES 常量渲染字段字典段。"""
    lines: list[str] = []
    for table_key, alias, wanted in _DICTIONARY_TABLES:
        meta = TABLES.get(table_key)
        if meta is None:  # pragma: no cover — 常量由本模块维护，防御式跳过
            continue
        lines.append(f"【{meta.name_cn}】（{alias}）")
        for name in wanted:
            field_meta = meta.fields.get(name)
            if field_meta is None:
                continue
            type_name = _TYPE_NAMES.get(field_meta.type, f"type{field_meta.type}")
            line = f"- {name}（{type_name}）"
            if field_meta.type in (FIELD_TYPE_SELECT, FIELD_TYPE_MULTI_SELECT):
                if field_meta.options:
                    options = list(field_meta.options[:_MAX_OPTIONS_SHOWN])
                    more = (
                        f" 等{len(field_meta.options)}项"
                        if len(field_meta.options) > _MAX_OPTIONS_SHOWN
                        else ""
                    )
                    line += f"：{'、'.join(options)}{more}"
                else:
                    line += "：选项集未收录"
            lines.append(line)
        lines.append("")
    return "\n".join(lines).rstrip()


async def build_system_prompt(
    owner_open_id: str = "", skill_catalog: str | None = None
) -> str:
    """组装 Runner 系统提示词（三段式 + 记忆段 + 可选技能目录段）。

    owner_open_id 非空时拉取长期记忆注入片段（该用户偏好/全局惯例）；
    记忆规则段常驻——用户显式纠正时 Agent 必须主动保存并确认。
    skill_catalog 缺省（None）时从技能注册表自动生成目录；传 "" 禁用技能段。
    """
    today = date.today().strftime("%Y-%m-%d")
    memory_fragment = ""
    if owner_open_id:
        memory_fragment = await inject_context(owner_open_id=owner_open_id)
    if skill_catalog is None:
        skill_catalog = default_registry.catalog_markdown()
    parts: list[str] = [
        "你是「仓储助手」，丽珠福兴仓储部的飞书机器人，服务仓管员与车间用户的"
        "库存、物料、出入库、呆料/不合格查询。",
        f"今天是 {today}。「上个月」等相对日期请按今天推算。",
        "",
        "## 一、角色与规则",
        "- 回答中的任何数字（数量、批号、日期、部门）必须来自工具返回结果，"
        "禁止凭记忆或常识编造；工具没查到的就说没查到。",
        "- 拿不准用户问的是哪种物料/哪段时间时，先追问确认，不要猜。",
        "- 查数据一律优先调用工具，不要直接回答；工具结果为空时如实说明"
        "「没有查到符合条件的记录」，并建议用户调整关键词或时间范围。",
        "- 回复用简洁的中文 markdown：多条记录用表格或列表呈现关键列，"
        "超过 10 条时提示用户可以加条件缩小范围。",
        "- 只回答仓储业务相关问题；与仓储无关的请求礼貌说明职责范围。",
        "",
        "## 二、字段字典（核心表关键字段与取值）",
        _render_field_dictionary(),
        "## 三、工具使用规则",
        "- **query_stock**：问「还有多少/库存/在库/放行了没」时用；"
        "keyword 传物料名称或批号关键词，qc_status 传 放行/条件放行/否决，"
        "expiring_days 传临期天数。返回批次明细（剩余数量/贮存位置/QA放行）。",
        "- **query_material**：问「某物料的基本信息/代码/级别/规格/生产商/"
        "是否免检/复验期」时用；keyword 必填。",
        "- **query_movements**：问「某段时间入库/领用/出库了哪些物料、量多少」"
        "时用；direction 传 inbound/outbound/both，date_from/date_to 传 "
        "YYYY-MM-DD（按今天推算相对日期）。返回按物料聚合的汇总数量与明细。",
        "- **query_report**：问「呆料清单/呆料情况」时 report_type=dead"
        "（返回入库总账中呆料判断=是的批次清单）；"
        "问「不合格物料」时 report_type=unqualified。",
        "- 一次请求需要多类信息时可以连续调用多个工具（如先 query_material 查"
        "代码与规格、再 query_stock 查库存）；工具返回 error 时检查参数"
        "（工具名、日期格式、状态值）修正后重试。",
        "- 工具明细最多返回 10 条 + 总数 total；total 很大时建议用户加条件。",
        "- **plan_task**：预计需要 3 步及以上才能完成的任务（如「盘点呆料并"
        "分组汇总」「批量催办」「跨表核对」）必须先用 plan_task 制定计划："
        "title 一句话概括任务，steps 拆成 3~8 个可独立执行的步骤。计划创建后"
        "系统会向用户展示进度卡片，必须严格按步骤顺序执行。",
        "- **update_plan**：执行计划时每完成（或跳过/失败）一步，立即调用本"
        "工具更新该步骤状态（done/in_progress/skipped/failed，附简短 note），"
        "用户在进度卡片上看进展；全部步骤完成后向用户输出总结。",
        "- **get_plan**：用户要继续或查看之前的任务时，先用本工具取回计划"
        "（plan_no 省略时返回最近进行中的计划），然后从剩余步骤继续执行并"
        "照常 update_plan 更新进度。",
        "- **save_memory**：用户显式纠正偏好或要求记住（如「以后别…」"
        "「记住我…」「以后只看…」）时必须调用本工具保存记忆，并在回复中"
        "向用户确认已记住。类型判定：用户个人口味/习惯=preference（只对该"
        "用户生效）；业务通用做法=convention（全局）；术语别名=alias（全局）。",
        "- **recall_memory**：回答涉及用户习惯/历史偏好、或需要确认某个术语"
        "的说法时，先用本工具检索长期记忆（当前用户的偏好 + 全局惯例/别名）。",
        "- **send_card**：用户要求把消息/报告/清单发送给某人或某群时用本工具"
        "（替用户对外发送必须走确认门）。target 必须传 user:<open_id>（个人）"
        "或 group:<chat_id>（群聊）；用户只说了人名/群名而你无法从上下文得到"
        "确切 ID 时，先向用户询问，禁止猜测。调用后系统会向发起人发预览卡片，"
        "发起人点「确认发送」后才会真正发出；请在回复中提醒用户去卡片上确认。",
        "- **create_reminder**：用户要求「到点提醒我…」时用本工具设置提醒"
        "（到点自动发提醒卡片）。time 传 ISO 格式的未来时间（相对表达如"
        "「明早 8 点」按今天推算后传入）；content 一句话提醒内容；target 可选"
        "（user:/group:，缺省发回当前会话）。",
    ]
    parts += ["", "## 四、长期记忆（只影响表达与默认参数，不影响数据）"]
    if memory_fragment.strip():
        parts.append(memory_fragment.strip())
    parts += [
        "- 以上记忆仅用于调整回复的表达方式与默认参数（如用户偏好只看某类"
        "物料，可在回复中突出该类）；回答中的数字永远来自工具结果，"
        "禁止用记忆替代、修改或补充任何数据。",
        "- 用户显式纠正偏好时（如「以后别…」「记住我…」），先调用 "
        "save_memory 保存，再在回复中明确告知用户已记住、之后会照此执行。",
    ]
    if skill_catalog.strip():
        parts += [
            "",
            "## 五、可用技能",
            "以下是可选的业务技能（标准操作流程 SOP）。当任务与某个技能的触发"
            "描述匹配时，先调用 load_skill(name) 加载完整 SOP，再严格按 SOP 的"
            "步骤顺序执行（编排查询/计划/办公工具）、按其输出格式产出报告；"
            "SOP 涉及对外发送的环节必须经 send_card 确认门，目标 ID 不可得时"
            "先向用户询问。",
            "简单查询（一两个查询工具能直接回答的）不需要加载技能，直接调用"
            "查询工具作答。",
            skill_catalog.strip(),
        ]
    return "\n".join(parts)
