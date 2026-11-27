"""HR 飞书原生审批统一凭证：HR 审批应用（福兴职称审批）。

职称评审拉取、劳动合同续签、离职管理的原生审批共用同一个有审批权限的 HR 应用：
读 HR_TITLE_REVIEW_FEISHU_*（config 校验器在留空时已回填 HR_FEISHU_*）。
全局平台应用不配审批权限（审批 API 报 99991672 Access denied），多维表格 /
消息卡片等非审批能力仍走全局应用，不受本文件影响。
"""

from app.core.config import get_settings


def approval_credentials() -> tuple[str | None, str | None]:
    """审批 API 凭证（均未配置时回落全局应用）。"""
    settings = get_settings()
    return (
        settings.HR_TITLE_REVIEW_FEISHU_APP_ID or None,
        settings.HR_TITLE_REVIEW_FEISHU_APP_SECRET or None,
    )
