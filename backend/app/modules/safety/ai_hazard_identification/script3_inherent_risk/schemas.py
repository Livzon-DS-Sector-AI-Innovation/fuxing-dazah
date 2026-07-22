"""脚本3 LEC固有风险评价 — 输入/输出数据模型。

LEC 评估法：风险值 D = L（可能性）× E（暴露频率）× C（严重性）

LECOutput 为脚本3/5/7 共用结构。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ═══════════════════════════════════════════════════════════════
# 共享 LEC 输出模型（脚本3/5/7 共用）
# ═══════════════════════════════════════════════════════════════

class LECOutput(BaseModel):
    """LEC 风险评价输出（脚本3/5/7 共用结构）。

    风险等级判定：
    - D ≥ 320  → level_1（重大风险）
    - 160 ≤ D < 320 → level_2（较大风险）
    - 70 ≤ D < 160 → level_3（一般风险）
    - D < 70 → level_4（低风险）
    """

    l_value: float | None = Field(
        None, ge=0.1, le=10, description="可能性 L（0.1~10）"
    )
    e_value: float | None = Field(
        None, ge=0.5, le=10, description="暴露频率 E（0.5~10）"
    )
    c_value: float | None = Field(
        None, ge=1, le=100, description="严重性 C（1~100）"
    )
    d_value: float | None = Field(
        None, description="风险值 D = L × E × C"
    )
    risk_level: str | None = Field(
        None, description="风险等级 key（level_1 / level_2 / level_3 / level_4）"
    )
    risk_label: str | None = Field(
        None, description="风险等级中文名（一级/重大风险 等）"
    )

    @property
    def is_unconfirmed(self) -> bool:
        """任一项为 None 表示信息不足 → 待人工确认。"""
        return any(
            v is None
            for v in [self.l_value, self.e_value, self.c_value]
        )


# ═══════════════════════════════════════════════════════════════
# LEC 合法值范围
# ═══════════════════════════════════════════════════════════════

VALID_L_VALUES = [0.1, 0.2, 0.5, 1, 2, 3, 6, 10]
VALID_E_VALUES = [0.5, 1, 2, 3, 6, 10]
VALID_C_VALUES = [1, 2, 3, 7, 15, 40, 100]

# LEC 评分参照表（注入 Prompt）
LEC_SCORING_GUIDE = """
L（可能性）:
  10 — 完全可以预料
   6 — 相当可能
   3 — 可能，但不经常
   1 — 可能性小，完全意外
 0.5 — 很不可能，可以设想
 0.2 — 极不可能
 0.1 — 实际不可能

E（暴露频率）:
  10 — 连续暴露
   6 — 每天工作时间内暴露
   3 — 每周一次，或偶然暴露
   2 — 每月一次暴露
   1 — 每年几次暴露
 0.5 — 非常罕见地暴露

C（严重性）:
 100 — 大灾难，10 人以上死亡
  40 — 灾难，3-9 人死亡
  15 — 非常严重，1-2 人死亡
   7 — 严重，重伤/致残
   3 — 重大，需医院治疗
   1 — 引人注目，需简单处理
"""

# 风险等级表
RISK_LEVEL_TABLE = """
风险等级判定:
  D ≥ 320       → level_1（一级/重大风险）   — 公司级管控
  160 ≤ D < 320 → level_2（二级/较大风险）   — 部门级管控
   70 ≤ D < 160 → level_3（三级/一般风险）   — 班组/岗位级管控
         D < 70 → level_4（四级/低风险）      — 班组/岗位级管控
"""


# ═══════════════════════════════════════════════════════════════
# 脚本3 输入/输出
# ═══════════════════════════════════════════════════════════════

class InherentRiskInput(BaseModel):
    """脚本3 输入：基础信息 + 脚本1+2输出（经人工确认）。"""

    department: str = Field(..., description="部门")
    position: str = Field(..., description="岗位")
    production_step: str = Field(..., description="生产步骤")
    specific_activity: str = Field(..., description="具体作业活动（脚本1）")
    equipment_facilities: str = Field(..., description="设备设施（脚本1）")
    raw_auxiliary_materials: str = Field(..., description="原辅料（脚本1）")
    operation_frequency: str | None = Field(None, description="作业频次")
    hazard_type: str = Field(..., description="危险类型（脚本2）")
    possible_accident: str = Field(..., description="可能导致事故（脚本2）")
    unsafe_behavior: str = Field(..., description="不规范行为（脚本2）")


class InherentRiskOutput(BaseModel):
    """脚本3 输出：固有风险 LEC 评价结果。"""

    lec: LECOutput = Field(..., description="LEC 评价结果（固有风险）")
