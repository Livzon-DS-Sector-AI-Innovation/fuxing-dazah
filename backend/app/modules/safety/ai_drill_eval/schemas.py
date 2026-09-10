"""演练评估表（AI）数据契约。"""

from __future__ import annotations

from pydantic import BaseModel, Field

VALID_GRADES = ["优秀", "良好", "合格", "不合格"]
VALID_DRILL_TYPES = ["综合演练", "专项演练", "现场处置演练", "桌面演练"]


class DrillEvalInput(BaseModel):
    """评估生成输入：主表关键字段 + 演练方案（设计基准）+ 演练记录表全文。"""

    record_fields: dict[str, str] = Field(default_factory=dict, description="主表字段（仅非空项）")
    plan_text: str = Field(default="", description="演练方案文本（AI 生成版结构化内容 / 定稿附件解析）")
    record_form_text: str = Field(default="", description="演练记录表解析出的纯文本")


class DrillEvalItem(BaseModel):
    """问题整改明细行。"""

    issue: str = Field(default="", description="存在问题")
    action: str = Field(default="", description="整改措施")
    deadline: str = Field(default="", description="完成期限，YYYY.MM.DD，无依据留空")
    done_status: str = Field(default="", description="完成情况：已完成/进行中/未开始")
    rectifier: str = Field(default="", description="整改人姓名，无依据留空")
    confirmer: str = Field(default="", description="确认人姓名，无依据留空")


class DrillEvalOutput(BaseModel):
    """评估表内容（与人工样例逐栏对应）。"""

    # 基本信息区
    drill_name: str = Field(default="", description="演练名称（如「妥布氨水罐区氨水泄漏」）")
    drill_time: str = Field(default="", description="演练时间，YYYY 年 MM 月 DD 日")
    drill_place: str = Field(default="", description="演练地点")
    org_department: str = Field(default="", description="组织部门")
    commander: str = Field(default="", description="现场指挥员")
    recorder: str = Field(default="", description="记录人")
    participants_desc: str = Field(default="", description="参加人员描述")
    participant_count_desc: str = Field(default="", description="参演人数描述（如「详见本次演练签到表」）")
    # 评价区
    drill_type_check: str = Field(default="", description="四选一，见 VALID_DRILL_TYPES，不确定留空")
    overall_comment: str = Field(default="", description="总体评价，多段以 \\n 分隔（目的→过程→效果）")
    grade: str = Field(default="", description="等级评定，见 VALID_GRADES，不确定留空")
    issues: list[DrillEvalItem] = Field(default_factory=list, description="问题整改明细")
    # 落款
    evaluator: str = Field(default="", description="评估人姓名，无依据留空")
    eval_date: str = Field(default="", description="评估日期，YYYY 年 MM 月 DD 日")
