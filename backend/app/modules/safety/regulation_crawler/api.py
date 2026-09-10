"""法规抓取 API 端点。

- POST /webhook/changedetection — 接收 changedetection.io 变更通知
- POST /crawl — 手动触发抓取（需认证）
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.regulation_crawler.schemas import (
    ChangeDetectionWebhookRequest,
    ManualCrawlRequest,
)
from app.modules.safety.regulation_crawler.service import RegulationCrawlerService

regulation_crawler_router = APIRouter()

_WEBHOOK_SECRET = os.getenv("SAFETY_REGULATION_CRAWLER_WEBHOOK_SECRET", "")


def _verify_webhook_secret(x_webhook_secret: str | None = Header(None)) -> None:
    """校验 Webhook shared secret（仅当环境变量已配置时生效）。"""
    if _WEBHOOK_SECRET and x_webhook_secret != _WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


@regulation_crawler_router.post(
    "/regulation-crawler/webhook/changedetection",
    response_model=ApiResponse,
    summary="changedetection.io 变更通知 Webhook",
)
async def changedetection_webhook(
    body: ChangeDetectionWebhookRequest,
    db: AsyncSession = Depends(get_db),
    _authenticated: None = Depends(_verify_webhook_secret),
) -> ApiResponse:
    """接收 changedetection.io 的页面变更通知。

    changedetection.io Docker 实例监控政府法规页面，
    检测到变更时向此端点发送 JSON POST。

    处理链路：
    1. 验证变更是否为实质性变更（过滤时间戳/格式噪音）
    2. AI 提取法规字段（标题、文号、日期、发布机关等）
    3. 写入飞书多维表格「法规标准清单」
    4. 返回爬取摘要（或 None 表示跳过）
    """
    service = RegulationCrawlerService(db)
    result = await service.process_changedetection_webhook(body)

    if result is None:
        return ApiResponse(code=200, message="No substantive change detected")

    return ApiResponse(
        data=result.model_dump(),
        message=f"Crawled {result.crawled_count} items, {result.new_count} new",
    )


@regulation_crawler_router.post(
    "/regulation-crawler/crawl",
    response_model=ApiResponse,
    summary="手动触发法规抓取",
)
async def manual_crawl(
    body: ManualCrawlRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> ApiResponse:
    """手动触发法规源抓取。

    可选指定 source_url 或 source_type 以限制抓取范围。
    不指定则遍历所有已注册的数据源。

    需认证（通过 get_current_user 依赖注入）。
    """
    source_url = body.source_url if body else None
    source_type = body.source_type if body else None

    service = RegulationCrawlerService(db)
    result = await service.crawl_sources(source_url=source_url, source_type=source_type)

    return ApiResponse(
        data=result.model_dump(),
        message=f"Crawled {result.crawled_count} items, {result.new_count} new, "
        f"{result.skipped_duplicate} skipped",
    )
