"""Agent 运行参数注册表 — 运营可调参数的代码唯一事实源。

本文件是 migration 播种来源 + 运行时 fallback：
DB 缺行时 store 回退 ``env_var``（非空时）→ ``default``。

原则：只有运营需要运行时调优的参数才进注册表；防 LLM 上下文膨胀的护栏常量、
Redis 键语义、业务契约映射等保持代码常量（见设计稿 §5.2 不配置化清单）。
本模块零副作用导入，migration 可直接引用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ValueType = Literal["int", "float", "str"]


@dataclass(frozen=True)
class RuntimeKeyInfo:
    """单个运行参数键（key 是稳定标识，DB 只能改值不能新增键）。"""

    key: str
    label: str
    group: str                          # 前端分组（确认与草稿 / Runner / 会话 / 识别 / 提醒 / 提示词）
    value_type: ValueType
    default: Any
    env_var: str                        # "" = 无 env 兜底
    min_value: float | None             # int/float 范围下界（含）
    max_value: float | None             # int/float 范围上界（含）
    max_length: int | None              # str 最大长度
    description: str


_RUNTIME_KEYS: tuple[RuntimeKeyInfo, ...] = (
    RuntimeKeyInfo(
        key="confirm_ttl_seconds",
        label="确认卡片有效期（秒）",
        group="确认与草稿",
        value_type="int",
        default=600,
        env_var="",
        min_value=60,
        max_value=86400,
        max_length=None,
        description="确认卡片与草稿的有效期；过期后点击卡片按钮提示已过期",
    ),
    RuntimeKeyInfo(
        key="draft_ttl_seconds",
        label="草稿有效期（秒）",
        group="确认与草稿",
        value_type="int",
        default=600,
        env_var="",
        min_value=60,
        max_value=86400,
        max_length=None,
        description="草稿独立有效期（与确认 TTL 解耦，可不同步调）",
    ),
    RuntimeKeyInfo(
        key="max_turns",
        label="Runner 轮次上限",
        group="Runner",
        value_type="int",
        default=10,
        env_var="WAREHOUSE_AGENT_MAX_TURNS",
        min_value=1,
        max_value=30,
        max_length=None,
        description="Runner tool-calling 循环轮次上限，超限返回兜底话术",
    ),
    RuntimeKeyInfo(
        key="session_rounds",
        label="会话历史注入轮数",
        group="Runner",
        value_type="int",
        default=12,
        env_var="WAREHOUSE_AGENT_SESSION_ROUNDS",
        min_value=1,
        max_value=50,
        max_length=None,
        description="每次对话注入的历史消息轮数（每轮 user+assistant 两条）",
    ),
    RuntimeKeyInfo(
        key="history_max_messages",
        label="会话历史保留条数",
        group="会话",
        value_type="int",
        default=24,
        env_var="",
        min_value=4,
        max_value=200,
        max_length=None,
        description="会话 history 持久化上限（user+assistant 交替）",
    ),
    RuntimeKeyInfo(
        key="align_fuzzy_min_ratio",
        label="主数据模糊匹配阈值",
        group="识别",
        value_type="float",
        default=0.6,
        env_var="",
        min_value=0.0,
        max_value=1.0,
        max_length=None,
        description="送货单识别后主数据对齐的 difflib 模糊匹配下限；低于此值不命中",
    ),
    RuntimeKeyInfo(
        key="reminder_max_active_per_user",
        label="单用户活跃提醒上限",
        group="提醒",
        value_type="int",
        default=10,
        env_var="",
        min_value=1,
        max_value=100,
        max_length=None,
        description="单用户同时未触发的到点提醒数量上限（防滥用预留）",
    ),
    RuntimeKeyInfo(
        key="system_prompt_override",
        label="系统提示词追加段",
        group="提示词",
        value_type="str",
        default="",
        env_var="WAREHOUSE_AGENT_SYSTEM_PROMPT",
        min_value=None,
        max_value=None,
        max_length=8000,
        description="非空时作为追加段注入系统提示词职责段之后（追加而非替换）；调优不发版",
    ),
    RuntimeKeyInfo(
        key="bitable_writeback_enabled",
        label="多维表格回写开关（0/1）",
        group="多维表格",
        value_type="int",
        default=0,
        env_var="",
        min_value=0,
        max_value=1,
        max_length=None,
        description=(
            "V3.0 分期A 回写总开关：1=库存状态变更/效期冻结先写 Base"
            "（material_receipt.上一状态）、确认门确认后回写 Base；"
            "0=（默认）本地直写、确认门停用建单与确认。"
            "上线前置：与仓储部确认「上一状态」列无自动化占用后再置 1"
        ),
    ),
    RuntimeKeyInfo(
        key="qc_writeback_enabled",
        label="QC 链路回写开关（0/1）",
        group="多维表格",
        value_type="int",
        default=0,
        env_var="",
        min_value=0,
        max_value=1,
        max_length=None,
        description=(
            "V3.0 分期B QC 请验放行闭环开关：1=QA 放行确认门创建与确认回写"
            "（material_receipt.QA放行/QA放行人/放行提交时间）、"
            "出报不合格自动生成不合格记录；0=（默认）以上 Base 写入全部停用。"
            "与分期A总开关解耦，可独立置 1"
        ),
    ),
    RuntimeKeyInfo(
        key="qa_confirm_target",
        label="QA 放行确认门目标",
        group="多维表格",
        value_type="str",
        default="",
        env_var="WAREHOUSE_TEST_CHAT_ID",
        min_value=None,
        max_value=None,
        max_length=64,
        description=(
            "QA 放行确认卡投递目标（群 chat_id 或 ou_ 开头个人 open_id）；"
            "空=回落 env WAREHOUSE_TEST_CHAT_ID（测试群）。"
            "生产环境改为真实 QA 群/人，即时生效"
        ),
    ),
    RuntimeKeyInfo(
        key="bitable_env_mode",
        label="Bitable 坐标环境模式（test/prod）",
        group="多维表格",
        value_type="str",
        default="test",
        env_var="",
        min_value=None,
        max_value=None,
        max_length=8,
        description=(
            "V3.0 分期D 生产版切换开关（§3.3）：test=使用测试版坐标（默认）；"
            "prod=表坐标解析优先取 bitable_env_connections 的 prod 行"
            "（其次沿用既有连接行/env/快照）。非法值 fail-safe 回 test。"
            "切 prod 前置：双跑比对零差异 + 零回写探针（.scratch 探针脚本）"
        ),
    ),
    RuntimeKeyInfo(
        key="sales_target_monthly",
        label="月度目标销量配置（JSON）",
        group="报表",
        value_type="str",
        default="",
        env_var="",
        min_value=None,
        max_value=None,
        max_length=8000,
        description=(
            "发货去向分析的预设销量对比数据源（二期 P1-2，总文档成品⑤）。"
            'JSON 格式：{"YYYY-MM": {"客户名称": 目标数量}}，客户名称须与'
            "成品出库台账销售客户列一致；配置后 shipment_analysis 月度卡对"
            "已配置客户展示 目标/达成率/差异。空=无目标（卡显示未配置提示）"
        ),
    ),
)

RUNTIME_REGISTRY: dict[str, RuntimeKeyInfo] = {k.key: k for k in _RUNTIME_KEYS}
assert len(RUNTIME_REGISTRY) == len(_RUNTIME_KEYS), "运行参数注册表存在重复 key"
for _info in _RUNTIME_KEYS:
    if _info.value_type in ("int", "float"):
        assert _info.min_value is not None and _info.max_value is not None, (
            f"运行参数 {_info.key} 数值类型必须声明范围"
        )
    if _info.value_type == "str":
        assert _info.max_length is not None, f"运行参数 {_info.key} 字符串类型必须声明长度上限"


def get_runtime_key(key: str) -> RuntimeKeyInfo:
    """未知 key 抛 ValueError（消息以「未知参数」开头，404 语义）。"""
    info = RUNTIME_REGISTRY.get(key)
    if info is None:
        raise ValueError(f"未知参数: {key}")
    return info


def iter_runtime_keys() -> tuple[RuntimeKeyInfo, ...]:
    """遍历全部参数键，供 migration 播种 + 遍历视图。"""
    return _RUNTIME_KEYS
