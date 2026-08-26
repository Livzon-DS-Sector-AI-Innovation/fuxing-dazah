"""飞书审批实例客户端 —— 兼容 shim。

实际实现收敛在 app/platform/integrations/feishu/approval.py（平台集成层），
本模块保留原有公开符号（list_instance_codes、get_instance、form_widgets_to_fields、
TitleReviewBitableError），并按职称评审约定传入独立应用凭证
（HR_TITLE_REVIEW_FEISHU_*，缺省回落全局应用）。
"""

from typing import Any

from app.core.config import get_settings
from app.modules.hr.title_review.bitable_client import TitleReviewBitableError
from app.platform.integrations.feishu.approval import (
    ApprovalAPIError,
    form_widgets_to_fields,
)

__all__ = [
    "list_instance_codes",
    "get_instance",
    "form_widgets_to_fields",
    "TitleReviewBitableError",
]


def _approval_credentials() -> tuple[str | None, str | None]:
    """审批独立应用凭证（缺省回落全局应用）。"""
    settings = get_settings()
    app_id = settings.HR_TITLE_REVIEW_FEISHU_APP_ID or None
    app_secret = settings.HR_TITLE_REVIEW_FEISHU_APP_SECRET or None
    return app_id, app_secret


async def list_instance_codes(
    approval_code: str,
    start_ms: int,
    end_ms: int,
) -> list[str]:
    """按审批定义编码拉取实例 Code（自动分页 + 按 10 小时分段）。"""
    from app.platform.integrations.feishu.approval import list_instance_codes as _impl

    app_id, app_secret = _approval_credentials()
    try:
        return await _impl(
            approval_code, start_ms, end_ms, app_id=app_id, app_secret=app_secret
        )
    except ApprovalAPIError as exc:
        raise TitleReviewBitableError(str(exc)) from exc


async def get_instance(instance_code: str) -> dict[str, Any]:
    """获取审批实例详情，返回 {status, start_time, form: [{id,name,type,value,...}]}。"""
    from app.platform.integrations.feishu.approval import get_instance as _impl

    app_id, app_secret = _approval_credentials()
    try:
        return await _impl(instance_code, app_id=app_id, app_secret=app_secret)
    except ApprovalAPIError as exc:
        raise TitleReviewBitableError(str(exc)) from exc
