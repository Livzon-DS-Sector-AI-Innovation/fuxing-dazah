"""抄表消息解析分层（facilities-p2 票 03，DESIGN §5.1）。

① 模板解析（确定性优先）：多行「指标 数值 [单位]」抄表文本 + 显式设备
   编号提取（GL-01 / RQ-2 式，含中文「N号锅炉」→ GL-N 归一）；
② AI 解析兜底：文本结构化 / 图片抽数，产出必须过合法性校验（指标在
   受控清单、数值可转 float）才采信。

三态出口：readings（可落库）/ chat（闲聊跳过，不计失败）/ 不可用
   （抛错或校验不过 → pending_review）。受控指标集由调用方注入
   （= 生效规则 metric 并集，动态含 app_config 覆写）。
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# 指标别名归一（表内口径以规则引擎 metric 为准）
METRIC_ALIASES: dict[str, str] = {
    "蒸汽压力": "汽压",
    "压力": "汽压",
    "排烟温度": "炉膛温度",
}

# 单位归一（中文/异写 → 标准）
UNIT_ALIASES: dict[str, str] = {
    "兆帕": "MPa", "mpa": "MPa", "Mpa": "MPa",
    "毫米": "mm", "MM": "mm",
    "度": "℃", "°C": "℃", "c": "℃", "摄氏度": "℃",
}

# 「[设备编号] 指标 数值 [单位]」行式（编号前缀可选；指标可带冒号分隔）
_LINE_RE = re.compile(
    r"^(?:[A-Za-z]{1,6}-\d{1,5}\s*[:：，]?\s*)?"
    r"(?P<metric>[\u4e00-\u9fa5A-Za-z]{2,8})\s*[:：]?\s*"
    r"(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z℃°%兆帕毫米]{1,4})?\s*$"
)

# 显式设备编号：字母段-数字段（GL-01 / RQ-2）；「N号锅炉」归一 GL-N
_EQ_RE = re.compile(r"\b([A-Za-z]{1,6})-?(\d{1,5})\b")
_CN_BOILER_RE = re.compile(r"(\d{1,2})号锅炉")


def effective_metric_set() -> set[str]:
    """受控指标集 = 默认规则 + 覆写规则的 metric 并集（动态读配置）。"""
    from app.modules.safety.app_config.store import store
    from app.modules.safety.telemetry.rules import effective_rules

    return {r.metric for r in effective_rules(store.get_str("SAFETY_TELEMETRY_RULES") or None)}


def _merged_aliases() -> dict[str, str]:
    """内置别名 + SAFETY_TELEMETRY_METRIC_ALIASES 覆写合并（非法 JSON 忽略）。"""
    import json as _json

    from app.modules.safety.app_config.store import store

    raw = store.get_str("SAFETY_TELEMETRY_METRIC_ALIASES", "")
    if not raw:
        return METRIC_ALIASES
    try:
        override = _json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("SAFETY_TELEMETRY_METRIC_ALIASES 非法 JSON，忽略覆写")
        return METRIC_ALIASES
    if not isinstance(override, dict):
        return METRIC_ALIASES
    return {**METRIC_ALIASES, **{str(k): str(v) for k, v in override.items()}}


def normalize_metric(raw: str, allowed: set[str]) -> str | None:
    """指标原词 → 标准指标名（别名归一后须在受控集内；否则 None）。"""
    name = _merged_aliases().get(raw, raw)
    return name if name in allowed else None


def normalize_unit(raw: str | None) -> str | None:
    if not raw:
        return None
    return UNIT_ALIASES.get(raw, raw)


def extract_equipment_no(text: str) -> str | None:
    """文本中的显式设备编号（字母-数字式优先；「N号锅炉」→ GL-N）。"""
    m = _EQ_RE.search(text)
    if m:
        return f"{m.group(1).upper()}-{m.group(2)}"
    m2 = _CN_BOILER_RE.search(text)
    if m2:
        return f"GL-{m2.group(1)}"
    return None


def template_parse(text: str | None, *, allowed: set[str]) -> list[dict] | None:
    """模板解析：至少一行「指标 数值」命中才算模板命中（None=未命中走 AI）。

    返回 readings（不含设备归属——归属由调用方统一处理）。
    """
    if not text:
        return None
    readings: list[dict] = []
    for line in text.splitlines():
        line = line.strip().strip("，。,")
        if not line:
            continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        metric = normalize_metric(m.group("metric"), allowed)
        if metric is None:
            continue
        readings.append({
            "metric": metric,
            "value": float(m.group("value")),
            "unit": normalize_unit(m.group("unit")),
        })
    return readings or None


def _validated_reading(
    raw: dict,
    allowed: set[str],
    allowed_equipment: set[str] | None = None,
) -> dict | None:
    """AI 单条读数 → 合法读数（指标受控 + 数值可转 float + 设备受控；
    否则 None）。allowed_equipment 非空时，AI 给出的设备编号必须在
    monitored 集内才采信（DESIGN §5.1 合法性校验）；None = 不校验
    （台账未连接的降级口径）。"""
    metric = normalize_metric(str(raw.get("metric", "") or ""), allowed)
    if metric is None:
        return None
    try:
        value = float(raw.get("value"))
    except (TypeError, ValueError):
        return None
    equipment = str(raw.get("equipment_no") or "").strip() or None
    if equipment and allowed_equipment is not None and equipment not in allowed_equipment:
        return None
    return {
        "equipment_no": equipment,
        "metric": metric,
        "value": value,
        "unit": normalize_unit(raw.get("unit")),
    }


def validate_ai_result(
    result: dict,
    *,
    allowed: set[str],
    allowed_equipment: set[str] | None = None,
) -> list[dict] | None:
    """AI 整体产出 → 合法 readings；type=chat 返回 []（闲聊）；
    有 readings 但全部非法 → None（pending 口径：AI 看到了抄表但抽不出
    可信数值，不能当闲聊丢弃）。"""
    if not isinstance(result, dict):
        return None
    if result.get("type") == "chat":
        return []
    raw_list = result.get("readings")
    if not isinstance(raw_list, list) or not raw_list:
        return None
    readings = [
        r
        for r in (
            _validated_reading(i, allowed, allowed_equipment)
            for i in raw_list
            if isinstance(i, dict)
        )
        if r is not None
    ]
    return readings or None


# ── 真实 AI 解析（文本 / 图片）─────────────────────────────────────

_TEXT_PROMPT = (
    "你是锅炉抄表数据抽取器。判断下面这条锅炉群消息：若包含设备读数"
    "（汽压/水位/炉膛温度等，含设备编号则提取），抽取为 JSON："
    '{"type":"readings","readings":[{"equipment_no":"GL-01或null","metric":"汽压",'
    '"value":0.8,"unit":"MPa"}]}；若是闲聊/通知等无读数消息，只返回 '
    '{"type":"chat"}。消息内容：\n'
)


async def ai_parse_text(text: str) -> dict:
    """文本 AI 解析（audited text 模型；返回 validate 前的原始 dict）。"""
    import json

    from app.modules.safety.service.config import create_ai_service

    service = create_ai_service("text")
    content = await service.chat(
        [{"role": "user", "content": _TEXT_PROMPT + text}],
        response_format="json_object",
        temperature=0.1,
    )
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return {"type": "unreadable"}


_VISION_PROMPT = (
    "这是锅炉群里的抄表截图/报表。抽取图中全部仪表读数为 JSON："
    '{"type":"readings","readings":[{"equipment_no":"GL-01或null","metric":'
    '"汽压","value":0.8,"unit":"MPa"}]}；若图中没有任何仪表数值，返回 '
    '{"type":"chat"}。'
)


async def ai_parse_image(image_path: str) -> dict:
    """图片 AI 解析（VisionService 管线；返回原始 dict）。"""
    from app.modules.safety.service.config import create_ai_service
    from app.modules.safety.vision.service import VisionService

    vision = VisionService(create_ai_service("vision"))
    result = await vision.analyze_parsed(
        text_prompt=_VISION_PROMPT,
        image_urls=[image_path],
        expected_keys=["type", "readings"],
    )
    if isinstance(result, dict):
        return result
    return {"type": "unreadable"}
