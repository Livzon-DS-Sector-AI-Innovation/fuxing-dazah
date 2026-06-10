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

    # Upload
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 10

    # Energy
    ENERGY_AUTO_COLLECT_ENABLED: bool = False

    # JWT
    JWT_EXPIRE_SECONDS: int = 86400  # 24 hours

    # API
    API_V1_PREFIX: str = "/api/v1"

    # AI / LLM
    AI_API_KEY: str = ""
    AI_BASE_URL: str = "https://api.openai.com/v1"
    AI_MODEL: str = "gpt-4o"
    AI_TIMEOUT: int = 120
    AI_TEMPERATURE: float = 0.1

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
