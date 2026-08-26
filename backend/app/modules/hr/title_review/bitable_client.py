"""职称评审多维表格（Bitable）API 客户端 —— 兼容 shim。

实际实现收敛在 app/platform/integrations/feishu/bitable.py（平台集成层）。
本模块在调用点读取 HR 独立应用凭证（HR_TITLE_REVIEW_FEISHU_*，缺省回落全局），
传入平台适配器；对外签名与原实现一致，service/事件处理器/测试无需改动。
"""

from typing import Any

from app.core.config import get_settings
from app.platform.integrations.feishu import bitable as _pb
from app.platform.integrations.feishu.bitable import BitableAPIError

# 兼容旧异常名（业务代码与测试均 catch 此名字）
TitleReviewBitableError = BitableAPIError


def _hr_creds() -> tuple[str | None, str | None]:
    """HR 独立飞书应用凭证（未配置返回 None，平台层回落全局 FEISHU_*）。"""
    settings = get_settings()
    return (
        settings.HR_TITLE_REVIEW_FEISHU_APP_ID or None,
        settings.HR_TITLE_REVIEW_FEISHU_APP_SECRET or None,
    )


async def subscribe_bitable(app_token: str) -> None:
    app_id, app_secret = _hr_creds()
    await _pb.subscribe_bitable(app_token, app_id=app_id, app_secret=app_secret)


async def batch_create_records(
    app_token: str, table_id: str, records: list[dict[str, Any]]
) -> list[str]:
    app_id, app_secret = _hr_creds()
    return await _pb.batch_create_records(
        app_token, table_id, records, app_id=app_id, app_secret=app_secret
    )


async def update_record(
    app_token: str, table_id: str, record_id: str, fields: dict[str, Any]
) -> None:
    app_id, app_secret = _hr_creds()
    await _pb.update_record(
        app_token, table_id, record_id, fields,
        app_id=app_id, app_secret=app_secret,
    )


async def list_all_records(
    app_token: str,
    table_id: str,
    *,
    page_size: int = 500,
    filter_expr: str | None = None,
) -> list[dict[str, Any]]:
    app_id, app_secret = _hr_creds()
    return await _pb.list_all_records(
        app_token, table_id, page_size=page_size, filter_expr=filter_expr,
        app_id=app_id, app_secret=app_secret,
    )


async def list_tables(app_token: str, *, page_size: int = 100) -> list[dict[str, Any]]:
    app_id, app_secret = _hr_creds()
    return await _pb.list_tables(
        app_token, page_size=page_size, app_id=app_id, app_secret=app_secret
    )


async def list_fields(
    app_token: str, table_id: str, *, page_size: int = 100
) -> list[dict[str, Any]]:
    app_id, app_secret = _hr_creds()
    return await _pb.list_fields(
        app_token, table_id, page_size=page_size,
        app_id=app_id, app_secret=app_secret,
    )


async def create_grid_view(
    app_token: str,
    table_id: str,
    view_name: str,
    filter_info: dict[str, Any] | None = None,
) -> str:
    app_id, app_secret = _hr_creds()
    return await _pb.create_grid_view(
        app_token, table_id, view_name, filter_info,
        app_id=app_id, app_secret=app_secret,
    )


__all__ = [
    "TitleReviewBitableError",
    "subscribe_bitable",
    "batch_create_records",
    "update_record",
    "list_all_records",
    "list_tables",
    "list_fields",
    "create_grid_view",
]
