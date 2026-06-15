from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # dazah-backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
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
    FEISHU_SYNC_ROOT_DEPT_ID: str = ""   # 部门同步的根部门 ID（API 触发）
    FEISHU_SYNC_MEMBER_DEPT_ID: str = ""  # 成员同步的目标部门 ID（每日 00:00）

    # Feishu WebSocket 长连接（接收消息/事件推送）
    FEISHU_WS_ENABLED: bool = True

    # Feishu 设备模块交互机器人（独立应用凭证）
    EQUIPMENT_FEISHU_APP_ID: str = ""
    EQUIPMENT_FEISHU_APP_SECRET: str = ""
    EQUIPMENT_FEISHU_WS_ENABLED: bool = True

    # Upload
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 10

    # Energy
    ENERGY_AUTO_COLLECT_ENABLED: bool = False

    # Maintenance Plan — 自动生成工单
    MAINTENANCE_PLAN_AUTO_ENABLED: bool = True

    # JWT
    JWT_EXPIRE_SECONDS: int = 86400  # 24 hours

    # Feishu Bitable — HR 模块多维表格同步
    FEISHU_BOT_NAME: str = ""
    FEISHU_BITABLE_APP_TOKEN: str = ""
    FEISHU_BITABLE_EMPLOYEE_TABLE_ID: str = ""
    FEISHU_BITABLE_DEPARTMENT_TABLE_ID: str = ""
    FEISHU_BITABLE_OFFBOARDING_TABLE_ID: str = ""
    FEISHU_BITABLE_ONBOARDING_TABLE_ID: str = ""
    FEISHU_BITABLE_DEPARTURE_TABLE_ID: str = ""
    FEISHU_BITABLE_APPROVAL_TABLE_ID: str = ""

    # Training Notification Bitable
    FEISHU_BITABLE_TRAINING_NOTIFICATION_APP_TOKEN: str = ""
    FEISHU_BITABLE_TRAINING_NOTIFICATION_TABLE_ID: str = ""

    # AI — HR 离职分析
    MOONSHOT_API_KEY: str = ""
    AI_MODEL: str = "kimi-k2.5"
    AI_SYSTEM_PROMPT: str = (
        "你是「小H」，原料药工厂人事管理助手。"
        "只基于查询结果回答人事问题，禁止编造。"
        "回答极其简洁，只陈述事实，不分析、不解释、不推理。"
        "禁止出现'根据规则'、'依据以上信息'等元话语。"
    )

    # API
    API_V1_PREFIX: str = "/api/v1"

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
                "以下 .env 配置项缺失或无效，请检查:\n  "
                + "\n  ".join(missing),
            )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.check()
    return settings
