"""质量模块专属飞书客户端（独立凭证，与全局飞书集成隔离）。"""

import logging
import os
from pathlib import Path

import lark_oapi as lark
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_env_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
_app_env = os.getenv("APP_ENV", "development")
_env_path = _env_dir / f".env.{_app_env}"
if _env_path.exists():
    load_dotenv(_env_path, override=True)

QUALITY_FEISHU_APP_ID = os.getenv("QUALITY_FEISHU_APP_ID", "")
QUALITY_FEISHU_APP_SECRET = os.getenv("QUALITY_FEISHU_APP_SECRET", "")
# 白名单群/用户（逗号分隔），空 = 不限制
QUALITY_FEISHU_CHAT_IDS = [
    c.strip() for c in os.getenv("QUALITY_FEISHU_CHAT_IDS", "").split(",") if c.strip()
]
QUALITY_FEISHU_USER_IDS = [
    u.strip() for u in os.getenv("QUALITY_FEISHU_USER_IDS", "").split(",") if u.strip()
]
# 允许新建任务的用户 open_id 白名单（逗号分隔），空 = 不限制建任务权限
QUALITY_FEISHU_CREATE_USER_IDS = [
    u.strip() for u in os.getenv("QUALITY_FEISHU_CREATE_USER_IDS", "").split(",") if u.strip()
]


def feishu_configured() -> bool:
    return bool(QUALITY_FEISHU_APP_ID and QUALITY_FEISHU_APP_SECRET)


def build_client() -> lark.Client:
    if not feishu_configured():
        raise RuntimeError("质量模块飞书配置缺失：请设置 QUALITY_FEISHU_APP_ID / QUALITY_FEISHU_APP_SECRET")
    return (
        lark.Client.builder()
        .app_id(QUALITY_FEISHU_APP_ID)
        .app_secret(QUALITY_FEISHU_APP_SECRET)
        .domain(lark.FEISHU_DOMAIN)
        .app_type(lark.AppType.SELF)
        .build()
    )
