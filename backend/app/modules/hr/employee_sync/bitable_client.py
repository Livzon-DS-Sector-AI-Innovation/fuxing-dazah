"""员工档案多维表格（Bitable）API 客户端 —— 凭证 shim。

实际实现收敛在 app/platform/integrations/feishu/bitable.py（平台集成层）。
本模块在调用点读取员工档案同步独立应用凭证（HR_EMPLOYEE_SYNC_FEISHU_*，
缺省回落全局 FEISHU_*）传入平台适配器——多环境（本地/服务器）可共用
同一个应用对 Base 的授权，避免"本地共享给测试应用、生产用不了"的问题。
"""

import re
from typing import Any

from app.core.config import get_settings
from app.platform.integrations.feishu import bitable as _pb
from app.platform.integrations.feishu.bitable import BitableAPIError

__all__ = [
    "BitableAPIError",
    "active_app_id",
    "clean_app_token",
    "clean_table_id",
    "list_tables",
    "list_fields",
    "list_all_records",
]


def _sync_creds() -> tuple[str | None, str | None]:
    """员工档案同步独立应用凭证（未配置返回 None，平台层回落全局 FEISHU_*）。"""
    settings = get_settings()
    return (
        settings.HR_EMPLOYEE_SYNC_FEISHU_APP_ID or None,
        settings.HR_EMPLOYEE_SYNC_FEISHU_APP_SECRET or None,
    )


def active_app_id() -> str:
    """当前实际生效的 API 应用 ID（错误信息自证用）。"""
    app_id, _ = _sync_creds()
    if app_id:
        return app_id
    return get_settings().FEISHU_APP_ID or "未配置"


def clean_app_token(value: str) -> str:
    """清洗 app_token：容忍直接粘贴完整飞书链接或带查询串的 token。

    混入 "?table=..." 时飞书会把请求路由到应用元数据接口（返回 app 字段、
    无 items），表现为"空表列表"且不报错，故必须在源头剥离。
    """
    v = value.strip()
    m = re.search(r"/base/([A-Za-z0-9]+)", v)
    if m:
        return m.group(1)
    return v.split("?", 1)[0].strip()


def clean_table_id(value: str) -> str:
    """清洗 table_id：容忍粘贴完整链接（取 table= 参数）或带查询串的 id。"""
    v = value.strip()
    m = re.search(r"[?&]table=([A-Za-z0-9]+)", v)
    if m:
        return m.group(1)
    v = v.split("?", 1)[0].strip()
    if "/" in v:
        v = v.rsplit("/", 1)[-1]
    return v


async def list_tables(app_token: str, *, page_size: int = 100) -> list[dict[str, Any]]:
    app_id, app_secret = _sync_creds()
    return await _pb.list_tables(
        clean_app_token(app_token), page_size=page_size, app_id=app_id, app_secret=app_secret,
    )


async def list_fields(
    app_token: str, table_id: str, *, page_size: int = 100
) -> list[dict[str, Any]]:
    app_id, app_secret = _sync_creds()
    return await _pb.list_fields(
        clean_app_token(app_token), clean_table_id(table_id), page_size=page_size,
        app_id=app_id, app_secret=app_secret,
    )


async def list_all_records(
    app_token: str,
    table_id: str,
    *,
    page_size: int = 500,
    filter_expr: str | None = None,
) -> list[dict[str, Any]]:
    app_id, app_secret = _sync_creds()
    return await _pb.list_all_records(
        clean_app_token(app_token), clean_table_id(table_id), page_size=page_size,
        filter_expr=filter_expr, app_id=app_id, app_secret=app_secret,
    )
