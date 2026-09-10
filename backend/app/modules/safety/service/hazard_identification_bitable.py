"""危险源辨识自动化多维表格 ↔ 平台镜像 的纯逻辑映射。

Ticket 01：提供 `map_bitable_to_model`（Bitable 记录字段 → 平台 HazardIdentification 镜像字段 dict）。
Ticket 04 在此文件扩展 `HazardIdentificationBitableService`（advance_record / decide_next_script / map_ai_output_to_bitable）。

设计要点（见 spec.md §5/§10）：
- **人工优先**：AI/人工 双份字段取（人工）非空值，否则取（AI）值（脚本4 existing_* 四键例外：
  **AI 优先**，见 `_AI_PRIORITY_MODEL_KEYS`——优化2 后脚本5 输入须读到 AI 润色稿）。
- **公式字段只读镜像**：风险值 D / 风险等级是 Bitable 公式字段（飞书拒绝写入），平台只读。
- **AI 原始值保留在 bitable_snapshot**：完整字段快照，供详情页渲染与全量回读。
- **无部门字段**：Bitable 无「部门」，由调用方注入 `department` 或 `resolve_department(submitter)` 派生，派不到置空。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.modules.safety.schemas.hazard_identifications import get_risk_level

logger = logging.getLogger(__name__)

# 脚本1-7 各输出字段：平台列名 → (AI 字段中文名, 人工字段中文名)
# 取值语义：人工非空取人工，否则取 AI（人工优先）。
_AI_MANUAL_PAIRS: dict[str, tuple[str, str]] = {
    # 脚本1：附件解析与基础作业信息补全
    "specific_activity": ("具体作业活动（AI）", "具体作业活动（人工）"),
    "equipment_facilities": ("设备设施（AI）", "设备设施（人工）"),
    "raw_auxiliary_materials": ("原辅料（AI）", "原辅料（人工）"),
    # 脚本2：AI 危险源辨识（人机料法环）
    "hazard_type": ("危险类型（AI）", "危险类型（人工）"),
    "possible_accident": ("可能导致事故（AI）", "可能导致事故（人工）"),
    "unsafe_behavior": ("不规范作业行为表现（AI）", "不规范作业行为表现（人工）"),
    # 脚本3：固有风险 LEC（真实 Bitable 字段名无空格，与 _LEC_OUTPUT_FIELDS/_D_VALUE_PAIRS 精确一致）
    "l_inherent": ("可能性L（固有）（AI）", "可能性L（固有）（人工）"),
    "e_inherent": ("暴露频率E（固有）（AI）", "暴露频率E（固有）（人工）"),
    "c_inherent": ("严重性C（固有）（AI）", "严重性C（固有）（人工）"),
    # 脚本4：现有控制措施
    "existing_engineering_controls": ("现有工程控制措施（AI）", "现有工程控制措施（人工）"),
    "existing_management_controls": ("现有管理控制措施（AI）", "现有管理控制措施（人工）"),
    "existing_ppe": ("现有个人防护措施（AI）", "现有个人防护措施（人工）"),
    "existing_emergency_measures": ("现有应急措施（AI）", "现有应急措施（人工）"),
    # 脚本5：残余风险 LEC（真实字段名括号混用：半角开+全角闭，人工字段带空格，均精确匹配）
    "l_residual": ("可能性L(残余）（AI）", "可能性L (残余）(人工)"),
    "e_residual": ("暴露频率E(残余）（AI）", "暴露频率E (残余）(人工)"),
    "c_residual": ("严重程度C（残余）（AI）", "严重程度C （残余）(人工)"),
    # 脚本6：建议措施
    "needs_recommendation": ("是否需提出建议措施（AI）", "是否需提出建议措施（人工）"),
    "recommendation_type": ("建议措施类型（AI）", "建议措施类型（人工）"),
    "recommendation_content": ("建议措施内容（AI）", "建议措施内容（人工）"),
    "recommendation_priority": ("建议措施优先级（AI）", "建议措施优先级（人工）"),
    # 脚本7：建议措施后风险（人工字段实际措辞为「采取建议措施」，与 AI 字段不同；C 人工字段括号为半角）
    "l_post": ("L（建议措施采取后）（AI）", "L（采取建议措施）（人工）"),
    "e_post": ("E（建议措施采取后）（AI）", "E（采取建议措施）（人工）"),
    "c_post": ("C（建议措施采取后）（AI）", "C（采取建议措施）(人工)"),
}

# 脚本4（现有控制措施）四键的取值语义例外：**AI 优先**（AI 非空取 AI，否则取人工）。
# 优化2 后脚本4 为「人工先填 → AI 审核润色」，脚本5（残余风险评价）输入须读到 AI 润色稿；
# 其余脚本保持人工优先（_AI_MANUAL_PAIRS 默认语义）。
# 注意：AI 运行前 model 合成值依赖回退仍等于人工原文，与人工优先无异——因此脚本4 触发条件
# 必须直接读 Bitable 原始人工字段（产品决策 R-1），不走 model 合成值（见 _required_inputs_ok 脚本4 特判）。
_AI_PRIORITY_MODEL_KEYS = frozenset({
    "existing_engineering_controls", "existing_management_controls",
    "existing_ppe", "existing_emergency_measures",
})

# D 值（风险值）公式字段：平台列名 → (AI 字段, 人工字段)，只读镜像，人工优先取 float。
# D 在 Bitable 为公式字段（type 20，只读），AI/人工 各一列，读取时人工优先。
_D_VALUE_PAIRS: dict[str, tuple[str, str]] = {
    "d_inherent": ("风险值D（固有）（AI）", "风险值D（固有）（人工）"),
    "d_residual": ("风险值D（残余）（AI）", "风险值D （残余）(人工)"),
    "d_post": ("风险值D（建议措施采取后）（AI）", "风险值 D（采取建议措施后）（人工）"),
}

# 风险等级列 ← 其来源 D 值列（Bitable 公式阈值 160/70/20 与平台 get_risk_level 一致，
# 直接用 D 推导 level_key + label，无需解析公式选项 ID）
_RISK_LEVEL_BY_D: dict[str, str] = {
    "inherent_risk_level": "d_inherent",
    "residual_risk_level": "d_residual",
    "post_risk_level": "d_post",
}

# 管控等级：按 Bitable 管控等级公式口径由固有风险等级 key 推导
# （重大/较大→公司级，一般→部门级，低→班组级；与平台 RISK_LEVELS.control_level 口径不同，以 Bitable 为准）
_CONTROL_BY_LEVEL_KEY: dict[str, str] = {
    "level_1": "公司级",
    "level_2": "公司级",
    "level_3": "部门级",
    "level_4": "班组级",
}

# 脚本8 四类排查内容：平台列名 → Bitable 字段中文名（AI + 人工 各一列）
_SCRIPT8_FIELDS: dict[str, str] = {
    "engineering_check_items_ai": "工程措施排查内容（AI）",
    "engineering_check_items_manual": "工程措施排查内容（人工）",
    "management_check_items_ai": "管理措施排查内容（AI）",
    "management_check_items_manual": "管理措施排查内容（人工）",
    "ppe_check_items_ai": "个人防护措施排查内容（AI）",
    "ppe_check_items_manual": "个人防护措施排查内容（人工）",
    "emergency_check_items_ai": "应急措施排查内容（AI）",
    "emergency_check_items_manual": "应急措施排查内容（人工）",
}

# 基础信息字段（Bitable 无「部门」）
_BASE_FIELDS: dict[str, str] = {
    "position": "岗位（人工）",
    "production_step": "生产步骤（人工）",
    "operation_frequency": "作业频次（人工）",
    # 脚本3.5 福建固有风险评级的人员密度输入（int 列，映射走 _effective_int，见 _INT_MODEL_KEYS）
    "operator_count": "操作人数（人工）",
}

# 审核状态：Bitable 中文 → 平台枚举
_REVIEW_STATUS_MAP = {
    "已审核": "approved",
    "待审核": "pending",
    "已驳回": "rejected",
}


# ── 值规范化（纯函数，不依赖任何 IO）──


def _text(value: Any) -> str:
    """Bitable 字段值 → 纯文本（兼容富文本 list / dict / 标量）。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                parts.append(item.get("text", "") or "")
            elif item is not None:
                parts.append(str(item))
        return "".join(parts).strip()
    if isinstance(value, dict):
        text = value.get("text") or value.get("value") or ""
        return str(text).strip()
    return str(value).strip()


def _float(value: Any) -> float | None:
    """Bitable 数值/文本 → float（无法解析返回 None）。"""
    s = _text(value)
    if not s:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _person_name(value: Any) -> str | None:
    """Bitable person 字段 → 姓名（list[{name,...}] 或 dict）。"""
    items = value if isinstance(value, list) else ([value] if value else [])
    for item in items:
        if isinstance(item, dict):
            name = (item.get("name") or item.get("en_name") or "").strip()
            if name:
                return name
    return None


def _person_id(value: Any) -> str | None:
    """Bitable person 字段 → 飞书 ID（优先 opend_id / open_id / id）。"""
    items = value if isinstance(value, list) else ([value] if value else [])
    for item in items:
        if isinstance(item, dict):
            for key in ("opend_id", "open_id", "id", "user_id"):
                pid = (item.get(key) or "").strip()
                if pid:
                    return pid
    return None


def _lookup(fields: dict[str, Any], *names: str) -> Any:
    """按候选名称顺序取值；全名未命中时做去空白归一化匹配。

    Bitable 字段名可能带细微空格差异，归一化后兜底，避免映射漏配。
    """
    for name in names:
        if name in fields:
            return fields[name]
    norm_map = {_normalize(k): v for k, v in fields.items()}
    for name in names:
        hit = norm_map.get(_normalize(name))
        if hit is not None:
            return hit
    return None


def _normalize(name: str) -> str:
    """字段名归一化：去全部空白（含全角空格）+ 统一全角/半角括号。

    Bitable 字段名存在括号混用（如 `可能性L(残余）（AI）` 半角开 + 全角闭），
    统一为半角后兜底匹配，避免映射漏配。精确字段名仍优先走 `_lookup` 的 `in fields`。
    """
    return "".join(str(name).split()).replace("（", "(").replace("）", ")")


def _effective_text(fields: dict[str, Any], ai_name: str, manual_name: str) -> str | None:
    """人工优先：人工值非空取人工，否则取 AI 值，都为空返回 None。"""
    manual = _text(_lookup(fields, manual_name))
    if manual:
        return manual
    ai = _text(_lookup(fields, ai_name))
    return ai or None


def _effective_text_ai_priority(
    fields: dict[str, Any], ai_name: str, manual_name: str,
) -> str | None:
    """AI 优先：AI 值非空取 AI（润色稿），否则取人工原文，都为空返回 None。

    仅脚本4 四类现有控制措施使用（优化2 产品决策 R-2：脚本5 残余风险评价
    输入读 AI 润色稿）；其余脚本保持 _effective_text 人工优先。
    """
    ai = _text(_lookup(fields, ai_name))
    if ai:
        return ai
    manual = _text(_lookup(fields, manual_name))
    return manual or None


def _effective_float(fields: dict[str, Any], ai_name: str, manual_name: str) -> float | None:
    """人工优先取数值：人工值可解析取人工，否则取 AI 值，都不可解析返回 None。

    与 _effective_text 区别：返回 float（供 L/E/C 等数值列落库，避免字符串写入 float 列报错）。
    """
    manual = _float(_lookup(fields, manual_name))
    if manual is not None:
        return manual
    return _float(_lookup(fields, ai_name))


def _effective_int(fields: dict[str, Any], name: str) -> int | None:
    """单字段（无人工/AI 双份）→ int（无法解析返回 None）。

    用于 operator_count：Bitable 该列为单列（「操作人数（人工）」），
    非 AI/人工 双份结构，不走 _effective_text（会把数值转成字符串，
    导致 FujianRiskInput.operator_count: int 接收 str 报 Pydantic 校验错误）。
    """
    raw = _lookup(fields, name)
    if raw is None:
        return None
    # 兼容 Bitable 数值字段（int/float）与文本字段（"5"）
    if isinstance(raw, (int, float)):
        return int(raw)
    s = _text(raw)
    if not s:
        return None
    try:
        return int(float(s))  # 容忍 "5.0" → 5
    except (TypeError, ValueError):
        return None


# L/E/C 数值列（模型为 float）：映射时必须走 _effective_float，不能当文本写入
_FLOAT_MODEL_KEYS = frozenset({
    "l_inherent", "e_inherent", "c_inherent",
    "l_residual", "e_residual", "c_residual",
    "l_post", "e_post", "c_post",
})

# int 列（模型为 int | None）：映射必须走 _effective_int（_text 会把数值转字符串，
# 导致 FujianRiskInput.operator_count: int 接收 str 报 Pydantic 校验错误）
_INT_MODEL_KEYS = frozenset({"operator_count"})

# 多选项中文标签列（模型为字符串）：多选字段（如 危险类型）API 返回标签列表，须以「、」拼接
_MULTI_SELECT_MODEL_KEYS = frozenset({
    "hazard_type", "recommendation_type",
})


def _join_labels(value: Any) -> str:
    """多选项/富文本 → 中文标签以「、」拼接（单选/文本原样返回）。"""
    if isinstance(value, list):
        labels: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = (item.get("text") or "").strip()
            else:
                text = str(item).strip()
            if text:
                labels.append(text)
        return "、".join(labels)
    return _text(value)


def _effective_labels(fields: dict[str, Any], ai_name: str, manual_name: str) -> str | None:
    """人工优先取多选项中文标签（list → 「、」拼接）。"""
    manual = _join_labels(_lookup(fields, manual_name))
    if manual:
        return manual
    ai = _join_labels(_lookup(fields, ai_name))
    return ai or None


def _review_status(value: Any) -> str:
    """Bitable 审核状态中文 → 平台枚举值。

    列 NOT NULL（Mapped[str]），Bitable 无值时回落列默认「pending」
    （未人工审核 = 待审核），避免镜像写 None 触发 NotNullViolation。
    """
    s = _text(value)
    if not s:
        return "pending"
    return _REVIEW_STATUS_MAP.get(s, s)


# ── 主映射函数 ──


def map_bitable_to_model(
    fields: dict[str, Any],
    *,
    feishu_record_id: str | None = None,
    feishu_url: str | None = None,
    feishu_table_id: str | None = None,
    department: str | None = None,
    resolve_department: Callable[[str], str | None] | None = None,
) -> dict[str, Any]:
    """Bitable 记录字段 → 平台 HazardIdentification 镜像字段 dict（纯逻辑）。

    参数：
        fields: Bitable 记录字段（中文名 → 原始值）。
        feishu_record_id/feishu_url/feishu_table_id: 记录级元信息（由调用方传入）。
        department: 已解析的部门（Bitable 无此字段）；为空时用 resolve_department(submitter) 派生。
        resolve_department: 从提交人姓名派生部门的可注入回调（如 IdentityResolver），保持本函数无 IO。

    返回：平台模型字段 dict（含 bitable_snapshot 完整快照）。
    """
    model: dict[str, Any] = {}

    # 1. 基础信息字段（operator_count 为 int 列，走 _effective_int 防 _text 转字符串）
    for col, fname in _BASE_FIELDS.items():
        if col in _INT_MODEL_KEYS:
            model[col] = _effective_int(fields, fname)
        else:
            model[col] = _text(_lookup(fields, fname)) or None

    # 2. 脚本1-7 输出（默认人工优先；脚本4 existing_* 四键为 AI 优先例外）
    for col, (ai_name, manual_name) in _AI_MANUAL_PAIRS.items():
        if col in _FLOAT_MODEL_KEYS:
            # L/E/C 为模型 float 列：人工优先取数值，不能当文本写入（否则 INSERT 报错）
            model[col] = _effective_float(fields, ai_name, manual_name)
        elif col in _MULTI_SELECT_MODEL_KEYS:
            # 多选项中文标签（危险类型/建议措施类型）：人工优先，list 以「、」拼接
            model[col] = _effective_labels(fields, ai_name, manual_name)
        elif col in _AI_PRIORITY_MODEL_KEYS:
            # 脚本4 现有控制措施（AI 优先）：AI 非空取 AI（润色稿，脚本5 输入自然读到），
            # 否则取人工原文（AI 未运行时 effective 仍注入人工已填措施）
            model[col] = _effective_text_ai_priority(fields, ai_name, manual_name)
        else:
            model[col] = _effective_text(fields, ai_name, manual_name)

    # 3. D 值公式字段（只读镜像，人工优先 float）
    for col, (ai_name, manual_name) in _D_VALUE_PAIRS.items():
        model[col] = _effective_float(fields, ai_name, manual_name)

    # 3b. 风险等级/管控等级：按平台阈值由 D 推导（Bitable 公式阈值 160/70/20 与平台一致）
    #      D 缺失时显式置 None，保证 model 键完整（调用方 Shape 稳定，列可落 NULL）
    for level_col, d_col in _RISK_LEVEL_BY_D.items():
        d = model.get(d_col)
        label_col = level_col.replace("_level", "_label")
        if d is None:
            model[level_col] = None
            model[label_col] = None
            continue
        level = get_risk_level(d)
        model[level_col] = level["key"]
        model[label_col] = level["label"]

    # 3c. 福建固有风险等级（脚本3.5 输出，Bitable 独立单选列 → 平台镜像列）
    model["inherent_risk_level_fj"] = (
        _text(_lookup(fields, _FUJIAN_RISK_FIELD)) or None
    )
    control_key = model.get("inherent_risk_level")
    model["control_level"] = (
        _CONTROL_BY_LEVEL_KEY.get(control_key) if control_key else None
    )

    # 4. 脚本8 四类排查内容（AI + 人工 各一列）
    for col, fname in _SCRIPT8_FIELDS.items():
        model[col] = _text(_lookup(fields, fname)) or None

    # 5. 提交/审核人员（Bitable 字段带「（人工）」后缀）
    model["submitter_name"] = _person_name(_lookup(fields, "提交人员（人工）", "提交人员"))
    model["submitter_feishu_id"] = _person_id(_lookup(fields, "提交人员（人工）", "提交人员"))
    model["reviewer_name"] = _person_name(_lookup(fields, "审核人员（人工）", "审核人员"))
    model["reviewer_feishu_id"] = _person_id(_lookup(fields, "审核人员（人工）", "审核人员"))

    # 6. 部门：优先显式传入，否则从提交人员派生（派不到置空）
    resolved_dept = department
    if not resolved_dept and resolve_department is not None:
        submitter = model.get("submitter_name") or ""
        resolved_dept = resolve_department(submitter)
    model["department"] = (resolved_dept or "").strip() or None

    # 7. 记录级元信息 + AI 流程节点进度 + 各脚本审核状态
    if feishu_record_id:
        model["feishu_record_id"] = feishu_record_id
    if feishu_url:
        model["feishu_url"] = feishu_url
    if feishu_table_id:
        model["feishu_table_id"] = feishu_table_id
    for i in range(1, 8):
        model[f"script{i}_review_status"] = _review_status(
            _lookup(fields, f"脚本{i}（人工审核状态）")
        )
    node = _text(_lookup(fields, "AI流程节点进度"))
    if node:
        # Bitable 中文标签 → 平台枚举（保证前端 AI_NODE_PROGRESS_OPTIONS 可匹配）。
        # 节点缺失时不写该键：ai_node_progress 列 NOT NULL，缺省由 DB 默认 pending_input 承担。
        model["ai_node_progress"] = _NODE_LABEL_TO_ENUM.get(node, node)

    # 7b. 整体状态：Bitable 节点到达「AI 流程结束」→ completed（导出/统计依赖）。
    #      镜像路径无平台自身审核流程，以 Bitable 节点为唯一判定来源；
    #      未结束记录一律 draft（避免残留旧值，spec.md §12 全字段镜像）。
    model["overall_status"] = (
        "completed" if model.get("ai_node_progress") == "completed" else "draft"
    )

    # 8. 完整快照（保留 AI/人工 双份 + 公式结果，供详情页/全量回读）
    model["bitable_snapshot"] = dict(fields)

    return model


# ════════════════════════════════════════════════════════════════════
# Ticket 04：纯逻辑编排核心
# ════════════════════════════════════════════════════════════════════

# 状态机常量（与 spec.md §4 / 设计文档一致）
_NODE_FIELD = "AI流程节点进度"
_ATTACHMENT_FIELD = "岗位资料附件（人工）"

# Bitable 节点标签 → 平台 ai_node_progress 枚举（前端筛选/展示用）
# 注意：平台枚举无 pending_script0；脚本1 对应 pending_script1（Bitable 无"待填基础信息"概念）
_NODE_LABEL_TO_ENUM: dict[str, str] = {
    "待危险源信息AI提取": "pending_script1",
    "待AI危险源辨识": "pending_script2",
    "待AI固有风险评价": "pending_script3",
    "待AI输入现有控制措施": "pending_script4",
    "待AI评价残余风险": "pending_script5",
    "待AI提出建议措施": "pending_script6",
    "待AI评价采取措施后的残余风险": "pending_script7",
    "待人工审核检查清单": "pending_script8",
    "AI 流程结束": "completed",
}

_NODE_TO_SCRIPT: dict[str, int] = {
    "待危险源信息AI提取": 1,
    "待AI危险源辨识": 2,
    "待AI固有风险评价": 3,
    "待AI输入现有控制措施": 4,
    "待AI评价残余风险": 5,
    "待AI提出建议措施": 6,
    "待AI评价采取措施后的残余风险": 7,
    "待人工审核检查清单": 8,
}

# 脚本编号 → 自身节点标签（`_NODE_TO_SCRIPT` 的逆映射）。
# 审核驱动推进：脚本N「已审核」后把节点推进到下一脚本时，写的是下一脚本的自身标签。
_SCRIPT_TO_NODE_LABEL: dict[int, str] = {
    1: "待危险源信息AI提取",
    2: "待AI危险源辨识",
    3: "待AI固有风险评价",
    4: "待AI输入现有控制措施",
    5: "待AI评价残余风险",
    6: "待AI提出建议措施",
    7: "待AI评价采取措施后的残余风险",
    8: "待人工审核检查清单",
}

# 脚本2-7 的必要输入（有效值，人工优先）——脚本1（岗位/生产步骤/附件）、脚本4（原始人工字段）
# 与脚本8（人工措施）单独处理（见 _required_inputs_ok 特判）
_SCRIPT_REQUIRED_MODEL_KEYS: dict[int, tuple[str, ...]] = {
    2: ("specific_activity", "equipment_facilities", "raw_auxiliary_materials"),
    3: ("hazard_type", "possible_accident", "unsafe_behavior"),
    # 优化2：脚本4 触发反转——从 LEC 三项改为 4 类现有控制措施（人工）的 model 键。
    # 注意：_required_inputs_ok 对脚本4 特判直接读 Bitable 原始人工字段（AI 优先语义下
    # model 合成值在 AI 运行前为空），此键仅作语义声明，不走通用 model 检查分支。
    4: (
        "existing_engineering_controls", "existing_management_controls",
        "existing_ppe", "existing_emergency_measures",
    ),
    5: (
        "existing_engineering_controls", "existing_management_controls",
        "existing_ppe", "existing_emergency_measures",
    ),
    6: ("l_residual", "e_residual", "c_residual"),
    7: ("recommendation_content",),
}

# 脚本3.5 福建固有风险等级回写目标字段（用户确认字段名为「（福建AI）」后缀，
# 非快照中的「固有风险等级（福建）」；白名单与回写目标统一用此常量，避免散落硬编码）
_FUJIAN_RISK_FIELD = "固有风险等级（福建AI）"

# 各脚本的（AI）输出 Bitable 字段（幂等判定 + 回写白名单的数据源）
_SCRIPT_AI_OUTPUT_FIELDS: dict[int | float, tuple[str, ...]] = {
    1: ("具体作业活动（AI）", "设备设施（AI）", "原辅料（AI）"),
    2: ("危险类型（AI）", "可能导致事故（AI）", "不规范作业行为表现（AI）"),
    3: ("可能性L（固有）（AI）", "暴露频率E（固有）（AI）", "严重性C（固有）（AI）"),
    4: (
        "现有工程控制措施（AI）", "现有管理控制措施（AI）",
        "现有个人防护措施（AI）", "现有应急措施（AI）",
    ),
    5: ("可能性L(残余）（AI）", "暴露频率E(残余）（AI）", "严重程度C（残余）（AI）"),
    6: (
        "是否需提出建议措施（AI）", "建议措施类型（AI）",
        "建议措施内容（AI）", "建议措施优先级（AI）",
    ),
    7: ("L（建议措施采取后）（AI）", "E（建议措施采取后）（AI）", "C（建议措施采取后）（AI）"),
    8: (
        "工程措施排查内容（AI）", "管理措施排查内容（AI）",
        "个人防护措施排查内容（AI）", "应急措施排查内容（AI）",
    ),
    # 脚本3.5：福建固有风险等级（脚本3 附属评估，float 键；自动纳入 _ALLOWED_AI_FIELDS 白名单）
    3.5: (_FUJIAN_RISK_FIELD,),
}

# 非 LEC 脚本：AI 输出属性 → Bitable（AI）字段名
_OUTPUT_FIELDS: dict[int | float, dict[str, str]] = {
    1: {
        "specific_activity": "具体作业活动（AI）",
        "equipment_facilities": "设备设施（AI）",
        "raw_auxiliary_materials": "原辅料（AI）",
    },
    2: {
        "hazard_type": "危险类型（AI）",
        "possible_accident": "可能导致事故（AI）",
        "unsafe_behavior": "不规范作业行为表现（AI）",
    },
    4: {
        "engineering_controls": "现有工程控制措施（AI）",
        "management_controls": "现有管理控制措施（AI）",
        "ppe": "现有个人防护措施（AI）",
        "emergency_measures": "现有应急措施（AI）",
    },
    6: {
        "needs_recommendation": "是否需提出建议措施（AI）",
        "recommendation_type": "建议措施类型（AI）",
        "recommendation_content": "建议措施内容（AI）",
        "recommendation_priority": "建议措施优先级（AI）",
    },
    8: {
        "engineering_items": "工程措施排查内容（AI）",
        "management_items": "管理措施排查内容（AI）",
        "ppe_items": "个人防护措施排查内容（AI）",
        "emergency_items": "应急措施排查内容（AI）",
    },
    # 脚本3.5：只回写 risk_label（综合等级中文名）；七指标明细 + reasoning 不回写 Bitable
    3.5: {
        "risk_label": _FUJIAN_RISK_FIELD,
    },
}

# LEC 脚本（3/5/7）：output.lec.{attr} → Bitable（AI）字段名（D 值/等级为公式字段，绝不回写）
_LEC_OUTPUT_FIELDS: dict[int, dict[str, str]] = {
    3: {
        "l_value": "可能性L（固有）（AI）",
        "e_value": "暴露频率E（固有）（AI）",
        "c_value": "严重性C（固有）（AI）",
    },
    5: {
        "l_value": "可能性L(残余）（AI）",
        "e_value": "暴露频率E(残余）（AI）",
        "c_value": "严重程度C（残余）（AI）",
    },
    7: {
        "l_value": "L（建议措施采取后）（AI）",
        "e_value": "E（建议措施采取后）（AI）",
        "c_value": "C（建议措施采取后）（AI）",
    },
}
_LEC_SCRIPTS = frozenset({3, 5, 7})

# 回写白名单：所有（AI）输出字段 + 节点进度（硬边界，map_ai_output_to_bitable 校验）
_ALLOWED_AI_FIELDS = frozenset(
    field
    for fields in _SCRIPT_AI_OUTPUT_FIELDS.values()
    for field in fields
)

# Bitable 中为多选（MultiSelect, type=4）的（AI）输出字段：写入值必须是 list[选项名]
# （实测 危险类型（AI）/建议措施类型（AI）为多选，写字符串会报 MultiSelectFieldConvFail）
_BITABLE_MULTI_SELECT_FIELDS = frozenset({
    "危险类型（AI）", "建议措施类型（AI）", _FUJIAN_RISK_FIELD,
})


def _coerce_bitable_value(fname: str, val: Any) -> Any:
    """Bitable 字段值规范化：多选字段 → list[选项名]，其余原样返回。

    - 危险类型（AI）/建议措施类型（AI）：平台 model 为「、」连接的字符串，按「、」拆分
    - 固有风险等级（福建AI）：脚本3.5 输出为单个中文等级名，包成单元素 list
    否则 MultiSelectFieldConvFail。
    """
    if fname in _BITABLE_MULTI_SELECT_FIELDS and isinstance(val, str):
        if fname == _FUJIAN_RISK_FIELD:
            return [val.strip()] if val.strip() else []
        parts = [t.strip() for t in val.strip().split("、") if t.strip()]
        return parts if parts else []
    return val


# 脚本8 输入：现有控制措施（人工）→ 注入执行器的字段名
_SCRIPT8_MANUAL_MEASURES: tuple[tuple[str, str], ...] = (
    ("现有工程控制措施（人工）", "engineering_controls"),
    ("现有管理控制措施（人工）", "management_controls"),
    ("现有个人防护措施（人工）", "ppe"),
    ("现有应急措施（人工）", "emergency_measures"),
)

# 各脚本「有效输出」的 model 键（人工优先：脚本1-7 的 model 值已人工优先；
# 脚本8 AI/人工各一列并存，任一侧非空即视为有输出）。供"脚本是否完整"（输出+已审核）判定。
_SCRIPT_OUTPUT_MODEL_KEYS: dict[int, tuple[str, ...]] = {
    1: ("specific_activity", "equipment_facilities", "raw_auxiliary_materials"),
    2: ("hazard_type", "possible_accident", "unsafe_behavior"),
    3: ("l_inherent", "e_inherent", "c_inherent"),
    4: (
        "existing_engineering_controls", "existing_management_controls",
        "existing_ppe", "existing_emergency_measures",
    ),
    5: ("l_residual", "e_residual", "c_residual"),
    6: (
        "needs_recommendation", "recommendation_type",
        "recommendation_content", "recommendation_priority",
    ),
    7: ("l_post", "e_post", "c_post"),
    8: (
        "engineering_check_items_ai", "engineering_check_items_manual",
        "management_check_items_ai", "management_check_items_manual",
        "ppe_check_items_ai", "ppe_check_items_manual",
        "emergency_check_items_ai", "emergency_check_items_manual",
    ),
}


def _attachment_source(value: Any) -> str | None:
    """Bitable 附件字段值 → 附件 URL/文件 token（兼容字符串/富文本/链接对象）。"""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        for item in value:
            src = _attachment_source(item)
            if src:
                return src
        return None
    if isinstance(value, dict):
        for key in ("url", "link", "text", "token", "file_token", "value"):
            hit = value.get(key)
            if hit:
                s = _text(hit)
                if s:
                    return s
        return None
    s = _text(value)
    return s or None


class HazardIdentificationBitableService:
    """危险源辨识自动化：Bitable 记录 ↔ 平台 AI 执行的纯逻辑编排核心。

    职责（对应 spec.md §3）：
    - `decide_next_script`：状态机判定当前应执行的脚本（1-8），条件不满足返回 None。
    - `map_ai_output_to_bitable`：AI 输出 → Bitable 回写字段（硬边界：只写（AI）字段 + 节点进度）。
    - `map_attachment_for_script1`：脚本1 附件 URL/文件 token → 本地文本（注入解析器）。
    - `advance_record`：判定 → 构建输入 → 注入执行 → 回写映射，返回 Bitable 回写 dict。

    全部逻辑为无 IO 纯函数 + 注入接口：
    - `run_script`: async (script_number, effective_input_dict) -> AI 输出对象
      （生产注入 orchestrator 适配器，测试注入 fake）。
    - `attachment_parser`: (attachment_url_or_token) -> 文本 | None（脚本1 附件下载+解析）。
    """

    def __init__(
        self,
        *,
        run_script: Callable[..., Any] | None = None,
        attachment_parser: Callable[[str], Awaitable[str | None]] | None = None,
    ):
        self.run_script = run_script
        self.attachment_parser = attachment_parser

    # ── 状态机判定 ──

    def decide_next_script(self, fields: dict[str, Any]) -> int | None:
        """判定当前节点脚本是否可执行（1-8）；任一触发条件不满足返回 None。

        触发条件（设计文档 §4.2，全部满足才执行）：
        1. `AI流程节点进度` 匹配当前脚本；
        2. 前置脚本 1..N-1 全部「已审核」且有效输出已存在（全链门控，防跳步）；
        3. 必要输入非空；
        4. 本脚本 AI 输出为空（幂等）+ 本脚本未「已审核」（防重跑已审核脚本）。
        """
        script = self._script_from_node(fields)
        if script is None:
            return None
        if self._script_runnable(fields, map_bitable_to_model(fields), script):
            return script
        return None

    @staticmethod
    def _script_from_node(fields: dict[str, Any]) -> int | None:
        """从 Bitable 节点标签解析当前脚本编号（1-8）；「AI 流程结束」/未知节点返回 None。

        状态机以 Bitable 中文节点标签为准，先读原始字段标签，再兜底反查枚举
        （防御 _NODE_LABEL_TO_ENUM 变动）。
        """
        script = _NODE_TO_SCRIPT.get(_text(fields.get(_NODE_FIELD)))
        if script is None:
            enum_val = (map_bitable_to_model(fields).get("ai_node_progress") or "").strip()
            label = next((k for k, v in _NODE_LABEL_TO_ENUM.items() if v == enum_val), None)
            script = _NODE_TO_SCRIPT.get(label or "")
        return script

    def _review_approved(self, fields: dict[str, Any], script: int) -> bool:
        """脚本N（人工审核状态）是否「已审核」。"""
        return (
            _review_status(_lookup(fields, f"脚本{script}（人工审核状态）")) == "approved"
        )

    def _script_output_present(
        self, model: dict[str, Any], script: int,
    ) -> bool:
        """脚本N 有效输出（AI 或人工，人工优先）是否任一非空。"""
        return any(
            v is not None and v != ""
            for v in (model.get(k) for k in _SCRIPT_OUTPUT_MODEL_KEYS[script])
        )

    def _script_complete(
        self, fields: dict[str, Any], model: dict[str, Any], script: int,
    ) -> bool:
        """脚本N 是否完整：有效输出已存在 且 已「已审核」。"""
        return self._script_output_present(model, script) and self._review_approved(
            fields, script
        )

    def _script_skipped(
        self, fields: dict[str, Any], model: dict[str, Any], script: int,
    ) -> bool:
        """脚本N 是否按业务规则跳过（无需执行，视为完成可越过）。

        脚本7（建议措施后风险评价）在「无需提出建议措施」（有效需要建议=否）时跳过：
        没有建议措施内容，无法也无必要做措施后 LEC 评价（设计文档 §4.8 触发条件
        「建议措施内容（人工）非空」隐含此跳过）。
        """
        if script != 7:
            return False
        return (
            _effective_text(fields, "是否需提出建议措施（AI）", "是否需提出建议措施（人工）")
            == "否"
        )

    def _script_done(
        self, fields: dict[str, Any], model: dict[str, Any], script: int,
    ) -> bool:
        """脚本N 是否完成或按规则跳过（可越过推进节点）。"""
        return self._script_complete(fields, model, script) or self._script_skipped(
            fields, model, script
        )

    def _all_previous_complete(
        self, fields: dict[str, Any], model: dict[str, Any], script: int,
    ) -> bool:
        """前置脚本 1..N-1 是否全部完成（或按规则跳过）（全链门控）。"""
        return all(self._script_done(fields, model, p) for p in range(1, script))

    def _script_runnable(
        self, fields: dict[str, Any], model: dict[str, Any], script: int,
    ) -> bool:
        """脚本N 是否可执行：全链完整 + 必要输入非空 + 本脚本未产出 + 本脚本未审核。

        跳过脚本（如脚本7 无需建议）永远不可执行——由对账直接越过，不运行。
        """
        if self._script_skipped(fields, model, script):
            return False  # 无需执行（如脚本7 无需建议）
        if not self._all_previous_complete(fields, model, script):
            return False
        if not self._required_inputs_ok(fields, model, script):
            return False
        if self._ai_output_present(fields, script):
            return False  # 幂等：本脚本 AI 输出已存在
        if self._review_approved(fields, script):
            return False  # 已审核但无输出 = 异常，不得重跑
        return True

    # ── AI 输出 → Bitable 回写 ──

    def map_ai_output_to_bitable(
        self, script: int | float, ai_output: Any,
    ) -> dict[str, Any]:
        """AI 输出 → Bitable 回写字段（仅 AI 输出，不写节点）。

        硬边界（spec.md §10）：只回写各脚本「（AI）」输出字段；
        绝不写（人工）字段、公式字段（D 值/风险等级/管控等级）、提交/审核人员字段。
        节点推进由 advance_record 按「审核通过后推进」约定（设计文档 §4.2）对账负责，不在此处写。
        越界即抛 ValueError（程序错误，测试兜底）。
        """
        result: dict[str, Any] = {}
        if script in _LEC_SCRIPTS:
            lec = getattr(ai_output, "lec", None)
            if lec is not None:
                for attr, fname in _LEC_OUTPUT_FIELDS[script].items():
                    val = getattr(lec, attr, None)
                    if val is not None:
                        result[fname] = _coerce_bitable_value(fname, val)
        else:
            mapping = _OUTPUT_FIELDS.get(script)
            if mapping:
                for attr, fname in mapping.items():
                    val = getattr(ai_output, attr, None)
                    if val is not None:
                        result[fname] = _coerce_bitable_value(fname, val)

        # 硬边界校验：越界字段一律视为程序错误
        extra = set(result) - _ALLOWED_AI_FIELDS
        if extra:
            raise ValueError(
                f"回写越界字段（禁止写人工/公式/人员字段）: {sorted(extra)} script={script}"
            )
        return result

    # ── 脚本1 附件解析 ──

    async def map_attachment_for_script1(
        self, fields: dict[str, Any], *, record_id: str | None = None,
    ) -> str | None:
        """读取 Bitable 岗位资料附件（人工）→ 注入解析器 → 本地文本。

        附件为空/下载失败/解析失败 → 返回 None（节点保持等待，不执行脚本1）。
        `record_id` 非空时向解析器传递 Bitable 附件上下文（record_id + 字段名），
        使其能构建 bitablePerm `extra` 下载真实附件；否则回退 URL/裸 token 下载。
        """
        source = _attachment_source(_lookup(fields, _ATTACHMENT_FIELD))
        if not source:
            return None
        if self.attachment_parser is None:
            return None
        try:
            if record_id:
                text = await self.attachment_parser(
                    {
                        "url": source,
                        "record_id": record_id,
                        "field_name": _ATTACHMENT_FIELD,
                    }
                )
            else:
                text = await self.attachment_parser(source)
        except Exception as e:  # 附件下载/解析失败不致命，保持等待
            logger.warning("脚本1 附件解析失败: %s", e)
            return None
        return text if text else None

    # ── 主入口：判定 → 构建输入 → 注入执行 → 回写 ──

    async def advance_record(
        self, fields: dict[str, Any], *, record_id: str | None = None,
    ) -> dict[str, Any] | None:
        """推进一条 Bitable 记录（审核驱动 + 卡死自愈对账），返回 Bitable 回写字段。

        三态（设计文档 §4.2 / 附录 B）：
        - **推进节点**：当前节点脚本「有效输出已存在 + 已审核」→ 节点推进到下一脚本；
          1..8 全部完整 → 推进到「AI 流程结束」（卡死自愈）。
        - **运行脚本**：首个未完整脚本可执行（全链完整 + 输入非空 + 未产出 + 未审核）→ 注入执行，
          回写 AI 输出；节点不变，等本脚本审核通过后再由事件驱动推进。
        - **等待**：前置链断裂 / 本脚本等审 / 附件解析失败 / AI 未产出 → 返回 None（仅镜像，不写 Bitable）。

        返回的回写 dict 只含（AI）字段 + 节点推进（硬边界由 map_ai_output_to_bitable 校验）。
        """
        script = self._script_from_node(fields)
        model = map_bitable_to_model(fields)
        if script is None:
            # 节点=「AI 流程结束」或未知节点：附录 B 检查 completed 是否名不副实
            if model.get("ai_node_progress") == "completed":
                self._log_completed_anomaly(fields, model)
            return None
        if not self._all_previous_complete(fields, model, script):
            # 前置链断裂（某前置脚本未完整）→ §4.2「不得执行，记录等待日志」
            self._log_wait_reason(fields, model, script)
            return None

        # 自愈对账：越过每个「完成或按规则跳过」（输出+已审核 / 无需建议）的脚本，节点推进到首个未就绪脚本
        target = script
        while target <= 8 and self._script_done(fields, model, target):
            target += 1

        writeback: dict[str, Any] = {}
        if target > 8:
            # 1..8 全部完整 → 推进到「AI 流程结束」（卡死自愈）
            writeback[_NODE_FIELD] = "AI 流程结束"
            return writeback
        if target != script:
            # 审核驱动推进节点到首个未完整脚本
            writeback[_NODE_FIELD] = _SCRIPT_TO_NODE_LABEL[target]

        # 首个未完整脚本可执行 → 运行（仅本脚本；节点不变，等其审核通过后再推进）
        if self._script_runnable(fields, model, target):
            if self.run_script is None:
                return writeback or None
            effective = self._build_script_input(fields, target)
            if target == 1:
                attachment = await self.map_attachment_for_script1(
                    fields, record_id=record_id,
                )
                if not attachment:
                    return writeback or None
                effective["attachment_text"] = attachment
            output = await self.run_script(target, effective)
            if output is not None:
                writeback.update(self.map_ai_output_to_bitable(target, output))

                # ── 脚本3.5：福建固有风险评级（脚本3 附属评估，不进状态机、不占审核）──
                # 幂等：福建字段已回填则不重跑；失败返回 None 不影响脚本3 LEC 回写（writeback 已含 L/E/C）
                if target == 3 and not self._ai_output_present(fields, 3.5):
                    fj_output = await self.run_script(3.5, effective)
                    if fj_output is not None and getattr(fj_output, "risk_label", None):
                        # 多选字段(type=4)：必须转 list[选项名]（否则 MultiSelectFieldConvFail）
                        writeback[_FUJIAN_RISK_FIELD] = _coerce_bitable_value(
                            _FUJIAN_RISK_FIELD, fj_output.risk_label
                        )
                    else:
                        logger.warning(
                            "脚本3.5 福建固有风险评级无有效输出（risk_label 缺失），"
                            "不阻断脚本3 LEC 回写"
                        )

                return writeback
        return writeback or None

    # ── 内部辅助 ──

    def _log_completed_anomaly(
        self, fields: dict[str, Any], model: dict[str, Any],
    ) -> None:
        """附录 B：节点已「AI 流程结束」但脚本8未完整（无输出或未审核）→ 状态异常，记日志等人工修复。"""
        if not self._script_complete(fields, model, 8):
            logger.error(
                "危险源辨识状态异常: 节点=AI 流程结束但脚本8未完整（无输出或未审核）; "
                "submitter=%s",
                model.get("submitter_name") or "?",
            )

    def _log_wait_reason(
        self, fields: dict[str, Any], model: dict[str, Any], script: int,
    ) -> None:
        """前置链断裂等待日志（§4.2「若未审核通过，不得执行，记录等待日志」）。"""
        broken = [
            p for p in range(1, script)
            if not self._script_done(fields, model, p)
        ]
        logger.warning(
            "危险源辨识前置未就绪，跳过执行: script=%s 前置未完整=%s submitter=%s",
            script, broken, model.get("submitter_name") or "?",
        )

    def _required_inputs_ok(
        self, fields: dict[str, Any], model: dict[str, Any], script: int,
    ) -> bool:
        """脚本必要输入是否非空。

        脚本1：岗位/生产步骤/附件；脚本4：4 类现有控制措施（人工）**原始字段**；
        脚本8：4 类现有控制措施（人工）；其余：脚本 N-1 输出的有效值。
        """
        if script == 1:
            return (
                bool(model.get("position"))
                and bool(model.get("production_step"))
                and bool(_text(_lookup(fields, _ATTACHMENT_FIELD)))
            )
        if script in (4, 8):
            # 脚本4：优化2 触发反转——4 类人工已填才触发 AI 润色（产品决策 R-1：
            #   触发读原始人工字段，不走 model 合成值——AI 优先语义下 AI 运行前
            #   model 值与人工原文等同，直接读 Bitable 原始字段语义最清晰）
            # 脚本8：排查清单输入同样要求 4 类现有控制措施（人工）已填
            return all(
                bool(_text(_lookup(fields, fname)))
                for fname, _ in _SCRIPT8_MANUAL_MEASURES
            )
        for key in _SCRIPT_REQUIRED_MODEL_KEYS[script]:
            val = model.get(key)
            if val is None:
                return False
            if isinstance(val, str) and not val.strip():
                return False
        return True

    def _ai_output_present(self, fields: dict[str, Any], script: int | float) -> bool:
        """本脚本任一（AI）输出字段是否已非空（幂等控制）。"""
        return any(
            bool(_text(_lookup(fields, fname)))
            for fname in _SCRIPT_AI_OUTPUT_FIELDS[script]
        )

    def _build_script_input(
        self, fields: dict[str, Any], script: int,
    ) -> dict[str, Any]:
        """构建注入执行器的输入（有效值字典，人工优先）。

        脚本 1-7：平台模型有效值（不含快照）；脚本 8：专取 4 类现有控制措施（人工）。
        """
        if script == 8:
            return {
                model_attr: _text(_lookup(fields, fname)) or ""
                for fname, model_attr in _SCRIPT8_MANUAL_MEASURES
            }
        model = map_bitable_to_model(fields)
        model.pop("bitable_snapshot", None)
        return model
