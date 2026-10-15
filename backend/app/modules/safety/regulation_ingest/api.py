"""法规收录 API 端点（契约①接收侧）。

- POST /regulation-ingest/candidates — 接收 ragplus 推送的候选批次
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.safety.app_config.store import store as _app_config_store
from app.modules.safety.regulation_ingest.schemas import IngestCandidatesRequest
from app.modules.safety.regulation_ingest.service import RegulationIngestService
from app.shared.schemas import ApiResponse

regulation_ingest_router = APIRouter()

_INGEST_SECRET_KEY = "SAFETY_REGULATION_INGEST_SECRET"


def _verify_ingest_secret(x_ingest_secret: str | None = Header(None)) -> None:
    """校验契约①推送 secret（仅当已配置时生效；env > DB 活行，app_config）。"""
    secret = _app_config_store.get_str(_INGEST_SECRET_KEY, "")
    if secret and x_ingest_secret != secret:
        raise HTTPException(status_code=401, detail="Invalid ingest secret")


@regulation_ingest_router.post(
    "/regulation-ingest/candidates",
    response_model=ApiResponse,
    summary="接收 ragplus 爬虫候选批次（契约①）",
)
async def receive_candidates(
    body: IngestCandidatesRequest,
    db: AsyncSession = Depends(get_db),
    _authenticated: None = Depends(_verify_ingest_secret),
) -> ApiResponse:
    """接收 ragplus-x 推送的候选法规批次并同步跑收录处理链。

    处理链：预去重（vs Bitable 台账）→ AI 批量相关性判定 → 写台账 +
    修订编排 → 生命周期回执（契约②）→ doc_map 登记 → 飞书推送；
    逐条处置结果随响应返回；同批重放幂等。
    """
    service = RegulationIngestService(db)
    resp = await service.ingest_candidates(body)
    message = (
        f"收录完成：{len(resp.results)} 条"
        if resp.accepted
        else f"未受理：{resp.reason}"
    )
    return ApiResponse(code=200, data=resp.model_dump(mode="json"), message=message)
