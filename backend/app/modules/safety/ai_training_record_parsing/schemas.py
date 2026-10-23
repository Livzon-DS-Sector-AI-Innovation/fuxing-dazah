"""AI 签到/成绩单解析插件 — 输入/输出数据结构（链3，vision）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

DOC_SIGN_IN = "签到表"
DOC_SCORE = "成绩单"
DOC_UNKNOWN = "无法识别"
DOC_TYPES = (DOC_SIGN_IN, DOC_SCORE, DOC_UNKNOWN)

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"
CONFIDENCE_LEVELS = (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW)


class TrainingRecordParseInput(BaseModel):
    """解析输入 — 培训行上下文 + 签到表附件图片（data URI）"""

    training_name: str = Field(default="", description="培训名称")
    expected_count: str = Field(default="", description="应到人数（展示文本）")
    assessment: str = Field(default="", description="考核方式")
    image_data_uri: str = Field(..., description="签到表/成绩单图片 data URI")


class TrainingRecordParseOutput(BaseModel):
    """解析输出 — 结构化转录结果（回填口径由编排层按 confidence 分级）"""

    doc_type: str = Field(default=DOC_UNKNOWN, description="签到表|成绩单|无法识别")
    attendance_count: int | None = Field(
        default=None, description="实到人数（单据无出勤信息为 None）"
    )
    names: list[str] = Field(default_factory=list, description="名单逐名转录")
    passed_count: int | None = Field(
        default=None, description="合格人数（无明确及格线为 None）"
    )
    scores: list[dict[str, Any]] = Field(
        default_factory=list, description="分数明细（只抄录不推算）"
    )
    confidence: str = Field(
        default=CONFIDENCE_LOW, description="high|medium|low"
    )
    unrecognized: list[str] = Field(
        default_factory=list, description="辨认不清的姓名"
    )
    notes: str = Field(default="", description="识别情况说明")
