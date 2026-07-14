import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # dazah-backend/


def _get_env_file() -> str:
    """根据 APP_ENV 选择对应的 .env 文件，默认为 development。"""
    app_env = os.getenv("APP_ENV", "development")
    env_file = str(_PROJECT_ROOT / f".env.{app_env}")
    print(f"Loading environment variables from: {env_file}")
    return env_file


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_get_env_file(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    APP_NAME: str = "dazah-backend"
    APP_ENV: str = "development"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/dazah"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Audit
    AUDIT_RETENTION_DAYS: int = 7

    # Feishu SSO — 全部从 .env 读取，不设默认值，避免部署时漏配
    FEISHU_APP_ID: str = ""
    FEISHU_APP_SECRET: str = ""
    FEISHU_REDIRECT_URI: str = ""
    FRONTEND_URL: str = ""

    # Feishu 设备部
    FEISHU_EQUIPMENT_DEPT_ID: str = ""
    FEISHU_EQUIPMENT_CHAT_ID: str = "oc_ba1a54a70a0d611315f29581621c50b5"

    # Feishu 组织架构同步
    FEISHU_SYNC_ROOT_DEPT_ID: str = ""  # 部门同步的根部门 ID（API 触发）
    FEISHU_SYNC_MEMBER_DEPT_ID: str = ""  # 成员同步的目标部门 ID（每日 00:00）

    # Feishu WebSocket 长连接（接收消息/事件推送）
    FEISHU_WS_ENABLED: bool = True

    # Feishu 安全模块机器人（独立应用凭证）
    SAFETY_FEISHU_APP_ID: str = ""
    SAFETY_FEISHU_APP_SECRET: str = ""

    # Upload
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 10

    # MinIO / S3-compatible object storage
    MINIO_ENABLED: bool = False
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET_PREFIX: str = "dazah"
    MINIO_SECURE: bool = False

    # Energy
    ENERGY_AUTO_COLLECT_ENABLED: bool = False

    # Maintenance Plan — 自动生成工单
    MAINTENANCE_PLAN_AUTO_ENABLED: bool = True

    # Meter — 检定到期飞书自动提醒
    METER_CALIBRATION_AUTO_NOTIFY_ENABLED: bool = False

    # JWT
    JWT_EXPIRE_SECONDS: int = 86400  # 24 hours

    # Permission System
    ADMIN_EMPLOYEE_NOS: list[str] = []

    # HR 模块 — 飞书多维表格同步
    HR_BITABLE_APP_TOKEN: str = ""
    HR_BITABLE_EMPLOYEE_TABLE_ID: str = ""
    HR_BITABLE_DEPARTMENT_TABLE_ID: str = ""
    HR_BITABLE_OFFBOARDING_TABLE_ID: str = ""
    HR_BITABLE_ONBOARDING_TABLE_ID: str = ""
    HR_BITABLE_DEPARTURE_TABLE_ID: str = ""
    HR_BITABLE_APPROVAL_TABLE_ID: str = ""

    # HR 模块 — AI 离职分析
    HR_AI_API_KEY: str = ""
    HR_AI_MODEL: str = "deepseek-chat"
    HR_AI_SYSTEM_PROMPT: str = (
        "你是「小H」，原料药工厂人事管理助手。"
        "只基于查询结果回答人事问题，禁止编造。"
        "回答极其简洁，只陈述事实，不分析、不解释、不推理。"
        "禁止出现'根据规则'、'依据以上信息'等元话语。"
    )

    # MCP — AI Agent 认证
    MCP_AGENT_API_KEYS: str = ""

    # API
    API_V1_PREFIX: str = "/api/v1"

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_ENABLED_MODULES: str = ""  # 逗号分隔，如 "safety,equipment"，空 = 全部启用
    LOG_DISABLED_MODULES: str = ""  # 逗号分隔，如 "energy,hr"，空 = 不禁用任何模块
    LOG_THIRD_PARTY_LEVEL: str = "WARNING"  # 三方库统一日志级别
    LOG_THIRD_PARTY_HANDLER_LEVEL: str = "WARNING"  # 三方库 handler 级过滤阈值
    LOG_ROOT_LEVEL: str = "WARNING"  # root logger 兜底级别
    LOG_DIR: str = "logs"  # 生产环境日志文件目录

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    def check(self) -> None:
        """启动时校验关键配置，避免漏配导致运行时异常。"""
        missing: list[str] = []
        if not self.SECRET_KEY:
            missing.append("SECRET_KEY")
        if not self.FEISHU_APP_ID:
            missing.append("FEISHU_APP_ID")
        if not self.FEISHU_APP_SECRET:
            missing.append("FEISHU_APP_SECRET")
        if not self.FEISHU_REDIRECT_URI:
            missing.append("FEISHU_REDIRECT_URI")
        if not self.FRONTEND_URL:
            missing.append("FRONTEND_URL")
        if missing:
            raise RuntimeError(
                "以下 .env 配置项缺失或无效，请检查:\n  " + "\n  ".join(missing),
            )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.check()
    return settings
