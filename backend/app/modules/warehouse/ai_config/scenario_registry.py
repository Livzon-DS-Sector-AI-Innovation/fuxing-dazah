"""AI 场景注册表 — 仓库 Agent LLM 调用场景的代码唯一事实源。

场景 = 业务功能级开关（不是每次调用一个场景）。仓库当前两条 LLM 业务链路：

- ``agent_chat``：Runner tool-calling 主循环（查询/计划/记忆/草稿收集/办公工具）；
- ``receipt_recognition``：送货单识别管线（方向预判 + 字段识别，审计以
  resource 字段区分 rotate_detect / receipt_parse）。

单模型位设计：模型既跑文本又跑视觉，``allowed_profiles`` 恒为
(agent, agent_backup)，``model_type`` 仅作信息性标注。

缺行 = 默认开启（enabled=True、model_profile=NULL → 主模型），未注册场景默认放行。
本模块零副作用导入，migration 可直接引用。
"""

from __future__ import annotations

from dataclasses import dataclass

# 场景 id → (中文标签, 一句话说明, model_type, channel)
_SCENARIO_FUNCTIONS: dict[str, tuple[str, str, str, str]] = {
    "agent_chat": (
        "仓库助手对话",
        "Runner tool-calling 主循环（查询/计划/记忆/草稿收集/办公工具）",
        "text",
        "feishu",
    ),
    "receipt_recognition": (
        "送货单识别入库",
        "图片方向预判 + 送货单字段识别（审计以 resource 区分两次调用）",
        "vision",
        "feishu",
    ),
}


@dataclass(frozen=True)
class ScenarioInfo:
    """单个 AI 调用场景（scenario 是稳定 key，DB 只能改值不能新增场景）。"""

    scenario: str
    label: str
    description: str
    model_type: str                    # text / vision（信息性；单模型位不派生白名单）
    channel: str                       # web / feishu / system / mixed


def get_scenario(scenario: str) -> ScenarioInfo:
    """未知场景抛 ValueError（消息以「未知场景」开头，404 语义）。"""
    info = SCENARIO_REGISTRY.get(scenario)
    if info is None:
        raise ValueError(f"未知场景: {scenario}")
    return info


def get_scenario_info(scenario: str) -> ScenarioInfo:
    """set_scenario 写路径别名（与 safety 命名对齐）。"""
    return get_scenario(scenario)


def iter_scenarios() -> tuple[ScenarioInfo, ...]:
    """遍历全部场景，供 migration 播种 + 遍历视图。"""
    return _SCENARIO_INFOS


def allowed_profiles_for(scenario: str) -> tuple[str, ...]:
    """绑定白名单：单模型位恒为 (agent, agent_backup)。"""
    return ("agent", "agent_backup")


def default_profile_for(scenario: str) -> str:
    """场景默认 profile（白名单首元素 = 主模型）。"""
    return "agent"


_SCENARIO_INFOS: tuple[ScenarioInfo, ...] = tuple(
    ScenarioInfo(scenario=sid, label=label, description=desc, model_type=mt, channel=ch)
    for sid, (label, desc, mt, ch) in _SCENARIO_FUNCTIONS.items()
)

SCENARIO_REGISTRY: dict[str, ScenarioInfo] = {s.scenario: s for s in _SCENARIO_INFOS}
assert len(SCENARIO_REGISTRY) == len(_SCENARIO_FUNCTIONS), "场景注册表存在重复 scenario"
