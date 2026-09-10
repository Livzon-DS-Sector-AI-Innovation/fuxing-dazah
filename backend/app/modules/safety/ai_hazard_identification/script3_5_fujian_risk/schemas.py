"""脚本3.5 福建固有风险评级 — 输入/输出数据模型。

按《福建省危险化学品企业安全风险分级评估指南（试行）》表5-1 七指标评价体系，
取七指标中最高等级（风险最大化原则）为综合固有风险等级。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# 福建固有风险等级（中文等级名，回写 Bitable + 平台库）
# 顺序对应风险从低到高，便于风险最大化比较（index 越大风险越高）
FUJIAN_RISK_LABELS: tuple[str, ...] = (
    "低风险",      # 蓝
    "一般风险",    # 黄
    "较大风险",    # 橙
    "重大风险",    # 红
)

# 七指标英文键名（与 FujianRiskOutput 字段一一对应，供规则引擎遍历）
FUJIAN_INDICATOR_FIELDS: tuple[str, ...] = (
    "substance",         # 危险物质种类数量 G
    "layout",            # 选址布局
    "environment",       # 周边环境
    "process",           # 危险工艺与重点监管危化品
    "pressure",          # 操作压力
    "temperature",       # 操作温度
    "personnel_level",   # 班组人员密度
)

# 信息不明确时默认按蓝色（低风险）的三项：
# 危险物质种类数量 G（G<1）、选址布局（防火间距满足）、周边环境（无/1个低密度场所）
# 依据：福建省指南表5-1 蓝色风险判定——信息不明确时按最保守（最低风险）档处理
FUJIAN_DEFAULT_BLUE_FIELDS: tuple[str, ...] = (
    "substance",
    "layout",
    "environment",
)


class FujianRiskInput(BaseModel):
    """脚本3.5 输入：基础信息 + 脚本1/2 输出 + operator_count。

    字段来源：
    - 基础信息：department / position / production_step（Bitable「（人工）」列 / 平台 item）
    - 脚本1：specific_activity / equipment_facilities / raw_auxiliary_materials / operation_frequency
    - 脚本2：hazard_type / possible_accident / unsafe_behavior
    - 人员密度输入：operator_count（Bitable 经 _effective_int 转 int；平台直接 item.operator_count）
    """

    department: str = Field(..., description="部门")
    position: str = Field(..., description="岗位")
    production_step: str = Field(..., description="生产步骤")
    specific_activity: str = Field(..., description="具体作业活动（脚本1）")
    equipment_facilities: str = Field(..., description="设备设施（脚本1）")
    raw_auxiliary_materials: str = Field(..., description="原辅料（脚本1）")
    operation_frequency: str | None = Field(None, description="作业频次")
    operator_count: int | None = Field(None, description="操作人数（人员密度指标输入）")
    hazard_type: str = Field(..., description="危险类型（脚本2）")
    possible_accident: str = Field(..., description="可能导致事故（脚本2）")
    unsafe_behavior: str = Field(..., description="不规范作业行为（脚本2）")


class FujianRiskOutput(BaseModel):
    """脚本3.5 输出：七指标等级 + 综合等级 + reasoning（不落库）。

    每个指标字段取值：FUJIAN_RISK_LABELS 之一 或 None（信息不足）。
    - substance/layout/environment（默认蓝三项）：信息不明确时由 auto_correct 补为「低风险」
    - 其余四项：信息不足可为 None
    risk_label 取七指标非 null 项的最高等级（风险最大化原则）；
    后四项全 null → risk_label 为「低风险」（默认蓝三项按蓝色最低档）。
    reasoning 仅用于 AI 审计日志，不落库、不回写 Bitable。
    """

    substance: str | None = Field(
        None, description="危险物质种类数量 G 等级"
    )
    layout: str | None = Field(
        None, description="选址布局等级"
    )
    environment: str | None = Field(
        None, description="周边环境等级"
    )
    process: str | None = Field(
        None, description="危险工艺与重点监管危化品等级"
    )
    pressure: str | None = Field(
        None, description="操作压力等级"
    )
    temperature: str | None = Field(
        None, description="操作温度等级"
    )
    personnel_level: str | None = Field(
        None, description="班组人员密度等级"
    )
    risk_label: str | None = Field(
        None,
        description=(
            "综合固有风险等级（中文等级名：低风险/一般风险/较大风险/重大风险）；"
            "取七指标非 null 项的最高等级"
        ),
    )
    reasoning: str | None = Field(
        None,
        description=(
            "AI 评级推理过程与缺失项说明（不落库，仅 AI 审计日志可见）"
        ),
    )

    @property
    def is_unconfirmed(self) -> bool:
        """七指标全 null → 信息不足待人工确认。"""
        return all(
            getattr(self, f) is None for f in FUJIAN_INDICATOR_FIELDS
        )
