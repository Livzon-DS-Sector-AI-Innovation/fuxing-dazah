"""HR turnover analysis schemas."""

from datetime import date

from pydantic import BaseModel


class TurnoverRawData(BaseModel):
    period_start: date
    period_end: date
    onboarding_count: int
    onboarding_by_department: dict[str, int]
    onboarding_by_job_category: dict[str, int]
    onboarding_by_education: dict[str, int]
    departure_count: int
    departure_by_reason: dict[str, int]
    departure_by_department: dict[str, int]
    departure_by_job_category: dict[str, int]
    current_headcount: int


class TurnoverMetrics(BaseModel):
    net_change: int
    initial_headcount: int
    turnover_rate: float


class AiSuggestion(BaseModel):
    suggestion: str
    evidence: str


class TurnoverAnalysisResponse(BaseModel):
    raw_data: TurnoverRawData
    metrics: TurnoverMetrics
    ai_summary: str
    ai_suggestions: list[AiSuggestion]
