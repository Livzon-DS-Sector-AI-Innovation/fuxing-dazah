"""HR turnover analysis API endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.response import success_response
from app.modules.hr.ai_service import AiChatService
from app.modules.hr.analysis_service import TurnoverAnalysisService

router = APIRouter(prefix="/turnover-analysis", tags=["HR人员流动分析"])


def get_turnover_analysis_service(
    session: AsyncSession = Depends(get_db),
) -> TurnoverAnalysisService:
    settings = get_settings()
    ai_service = AiChatService(
        api_key=settings.HR_AI_API_KEY,
        model=settings.HR_AI_MODEL,
    )
    return TurnoverAnalysisService(session, ai_service)


@router.get("", summary="人员流动分析")
async def get_turnover_analysis(
    service: TurnoverAnalysisService = Depends(get_turnover_analysis_service),
):
    """分析最近6个月老厂人员流动数据并生成AI报告."""
    result = await service.analyze()
    return success_response(data=result.model_dump(mode="json"))
