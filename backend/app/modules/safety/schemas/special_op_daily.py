"""特殊作业日报 Schema — 风险判定结果、日报请求/响应."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field


class RiskAssessmentResult(BaseModel):
    """单条作业的日报风险判定结果"""
    risk_level: str = Field(..., description="high / medium / low")
    matched_rules: list[str] = Field(default_factory=list)
    is_excluded: bool = False
    exclusion_reason: str | None = None
    inferred_types: list[str] = Field(default_factory=list)


class AIDailyAnalysisResult(BaseModel):
    """AI 日报增强分析结果"""
    summary: str = Field(default="", description="当日风险态势概述")
    enhanced_reasons: dict[str, str] = Field(default_factory=dict, description="report_id → AI 重写的风险描述")
    control_measures: dict[str, str] = Field(default_factory=dict, description="report_id → AI 管控措施")
    enhanced_tips: list[str] = Field(default_factory=list, description="AI 生成的针对性安全提示")


class DailyReportRequest(BaseModel):
    """手动触发日报生成请求"""
    target_date: date | None = Field(None, description="目标日期，默认今天")
    mode: str = Field(default="today", description="today / tomorrow")


class DailyReportResponse(BaseModel):
    """日报生成结果"""
    report_date: date
    mode: str
    total: int
    excluded: int
    high_risk: int = 0
    medium_risk: int = 0
    low_risk: int = 0
    markdown_report: str
    push_results: list[dict] = Field(default_factory=list)
    logs_analyzed: list[uuid.UUID] = Field(default_factory=list)


class DailyReportStats(BaseModel):
    """日报统计"""
    date: str
    total: int
    high: int
    medium: int
    low: int
