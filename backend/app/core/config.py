import os
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
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

    # HR 专属飞书应用凭证：员工档案 bitable 同步与职称评审审批同步共用
    # 同一应用时只需配这一对，下面两对专用变量留空自动回填本值。
    HR_FEISHU_APP_ID: str = ""
    HR_FEISHU_APP_SECRET: str = ""

    # 职称评审：独立飞书应用凭证（审批同步用：approval:approval:readonly / approval:definition；
    # 缺省回落 HR_FEISHU_* → 全局应用）。多维表格读写与通知卡片始终使用全局应用。
    HR_TITLE_REVIEW_FEISHU_APP_ID: str = ""
    HR_TITLE_REVIEW_FEISHU_APP_SECRET: str = ""
    HR_TITLE_REVIEW_FEISHU_WS_ENABLED: bool = False

    # 员工档案多维表格同步：独立应用凭证（bitable 读写；缺省回落 HR_FEISHU_* → 全局应用）。
    # 多环境共用一个应用时可让本地与服务器共用同一份 Base 授权。
    HR_EMPLOYEE_SYNC_FEISHU_APP_ID: str = ""
    HR_EMPLOYEE_SYNC_FEISHU_APP_SECRET: str = ""

    # 职称评审定时对账开关（默认开启；关闭后仅保留手动「同步」按钮）
    HR_TITLE_REVIEW_SYNC_ENABLED: bool = True

    # HR AI（DeepSeek）：出题/人事问答/面试评价/胜任度分析统一使用一个 key
    HR_AI_API_KEY: str = ""
    HR_AI_MODEL: str = "deepseek-chat"

    # 绩效飞书通知开关（自评/领导评分提交后通知，默认关闭）
    HR_PERFORMANCE_NOTIFY: bool = False

    @model_validator(mode="after")
    def _hr_feishu_creds_fallback(self) -> "Settings":
        """HR 专属凭证统一配置：专用变量留空时回填 HR_FEISHU_*。

        职称评审与员工档案同步通常共用同一个 HR 飞书应用，.env 里
        重复写两遍同一对值容易漏改一处处；旧环境（如服务器
        .env.production）直接配专用变量的继续生效，不受影响。
        """
        if self.HR_FEISHU_APP_ID:
            if not self.HR_TITLE_REVIEW_FEISHU_APP_ID:
                self.HR_TITLE_REVIEW_FEISHU_APP_ID = self.HR_FEISHU_APP_ID
                self.HR_TITLE_REVIEW_FEISHU_APP_SECRET = self.HR_FEISHU_APP_SECRET
            if not self.HR_EMPLOYEE_SYNC_FEISHU_APP_ID:
                self.HR_EMPLOYEE_SYNC_FEISHU_APP_ID = self.HR_FEISHU_APP_ID
                self.HR_EMPLOYEE_SYNC_FEISHU_APP_SECRET = self.HR_FEISHU_APP_SECRET
        return self

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
    ENERGY_WORKSHOP_ALERT_ENABLED: bool = False
    ENERGY_DAILY_PUSH_ENABLED: bool = False
    ENERGY_NITROGEN_PUSH_ENABLED: bool = False

    # Maintenance Plan — 自动生成工单
    MAINTENANCE_PLAN_AUTO_ENABLED: bool = True

    # Meter — 检定到期飞书自动提醒
    METER_CALIBRATION_AUTO_NOTIFY_ENABLED: bool = False

    # Meter AI — DeepSeek 视觉识别报告字段（校准报告 PDF 内容识别）
    METER_AI_BASE_URL: str = ""
    METER_AI_API_KEY: str = ""
    METER_AI_MODEL: str = "deepseek-v4-flash-vision-exp"

    # QA AI 文档实体分析（OpenAI-compatible；关闭或无 key 时只保留解析/人工流程）
    QA_AI_ENABLED: bool = False
    QA_AI_API_KEY: str = ""
    QA_AI_BASE_URL: str = "https://api.openai.com/v1"
    QA_AI_MODEL: str = "gpt-4o-mini"
    QA_AI_TIMEOUT_SECONDS: int = 120
    QA_AI_MAX_TOKENS: int = 4096
    QA_AI_MAX_RETRIES: int = 2
    QA_AI_PROMPT_VERSION: str = "qa-entity-v1"
    QA_AI_SCHEMA_VERSION: str = "qa-entity-schema-v1"

    # QA 新上传/重提取统一使用 MinerU v4 异步 API；旧运行记录仍可保留
    # native provider 值用于历史兼容。API token 只从部署环境注入。
    QA_MD_EXTRACT_PROVIDER: str = "mineru"
    QA_MD_EXTRACT_API_TOKEN: str = ""

    # 液相加密计算表服务端兜底密码：前端未填密码且文件加密时使用。
    # 密码只放部署环境，不出现在前端代码（git 历史泄露过一次，待轮换）。
    QUALITY_LC_EXCEL_PASSWORD: str = ""

    # JWT
    JWT_EXPIRE_SECONDS: int = 86400  # 24 hours

    # Permission System
    ADMIN_EMPLOYEE_NOS: list[str] = []

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

    # Warehouse — 仓储模块专属飞书应用（仓库管理机器人）与 Agent 模型
    WAREHOUSE_FEISHU_APP_ID: str = ""
    WAREHOUSE_FEISHU_APP_SECRET: str = ""
    # 仓储机器人专属飞书事件 WS 长连接开关（main.py 门控，独立于平台/安全模块连接）
    WAREHOUSE_FEISHU_WS_ENABLED: bool = False
    # V1.0 数据面：4 个测试版 Base token
    WAREHOUSE_FEISHU_BITABLE_MATERIAL_APP_TOKEN: str = ""
    WAREHOUSE_FEISHU_BITABLE_GMP_APP_TOKEN: str = ""
    WAREHOUSE_FEISHU_BITABLE_PROD_APP_TOKEN: str = ""
    WAREHOUSE_FEISHU_BITABLE_SALES_APP_TOKEN: str = ""
    # Agent 单模型位（视觉 + function calling，DeepSeek 兼容网关）
    WAREHOUSE_AGENT_BASE_URL: str = ""
    WAREHOUSE_AGENT_API_KEY: str = ""
    WAREHOUSE_AGENT_MODEL: str = ""
    WAREHOUSE_AGENT_TIMEOUT: int = 120
    # Agent 备用模型（主模型 401/429/5xx/超时自动降级；三项齐备才启用）
    WAREHOUSE_AGENT_BACKUP_API_KEY: str = ""
    WAREHOUSE_AGENT_BACKUP_BASE_URL: str = ""
    WAREHOUSE_AGENT_BACKUP_MODEL: str = ""
    # 系统提示词追加段（runtime_configs.system_prompt_override 缺行时兜底）
    WAREHOUSE_AGENT_SYSTEM_PROMPT: str = ""
    # 系统告警目标群（scheduler_task_configs.system_alert.target 缺行时兜底）
    WAREHOUSE_ALERT_CHAT_ID: str = ""
    # 冒烟测试目标群（可选；配置后 test_live_smoke 真发一条卡片）
    WAREHOUSE_TEST_CHAT_ID: str = ""
    # 五金库领料审批通道（M3，设计 §五）：feishu=提交即代发起「福兴电子领/
    # 退料单审批」（需配 HARDWARE_APPROVAL_CODE，未配置自动落 manual）；
    # manual=部门主管在领用中心点确认（审批结果代录）。状态机对通道无感。
    HARDWARE_APPROVAL_CHANNEL: str = "manual"
    HARDWARE_APPROVAL_CODE: str = ""
    # 审批实例对账任务开关（每小时拉近 2h 实例补摄取）：本地联调置 false——
    # 防生产真实实例被摄取进本地库污染测试数据（轮询/WS 事件不受影响）。
    HARDWARE_APPROVAL_RECONCILE_ENABLED: bool = True
    # 「主管及以上审批」节点 id（发起人自选）：定义改版后节点 id 变化时覆盖；
    # 空=使用 approval_channel.APPROVER_NODE_ID 默认值。
    HARDWARE_APPROVAL_NODE_ID: str = ""
    # 发起人口径（已弃用）：2026-11-19 起统一按 identity.users.feishu_user_id
    # 解析创建审批实例的 user_id；此键保留仅为兼容历史 env。
    HARDWARE_APPROVAL_USER_KEY: str = "user_id"
    # 五金库报废审批（2026-11-25：报废出库并入申领出库路径，发起自选审批人）：
    # 复用「福兴电子领/退料单审批」的报废分支——业务部门在飞书后台给定义加
    # 分流选项「报废」+五个控件（发起部门/发起人/报废条件及说明/报废明细/
    # 报废单号）后，把选项 value 填 KIND_VALUE、控件 id 填 WIDGETS，提交时即把
    # 飞书审批单发给所选审批人；未配置=审批人在平台「申请单据 → 待审批」点通过。
    HARDWARE_SCRAP_KIND_VALUE: str = ""
    HARDWARE_SCRAP_FORM_WIDGETS: str = ""
    # 五金库退料审批（2026-11-26：从已发料领料单发起退料）：复用同一审批定义的
    # 「五金库退料-平台」分支（退料部门/退料人/原领料单号/退料明细/退库单号/
    # 退料说明六个普通控件——明细表 fieldList API 不可写，同领料平台分支口径）。
    # 配齐即启用：提交退料单时把飞书审批单发给所选审批人；未配置=平台点通过。
    HARDWARE_RETURN_KIND_VALUE: str = ""
    HARDWARE_RETURN_FORM_WIDGETS: str = ""
    # 五金库 direct 类高置信自动入账（M9 observe→auto 阶段1，默认关；§9.3
    # 红线：仅 direct 类、全部行置信≥阈值、无照片初筛异常标记才自动 accepted；
    # stocked 类永不自动。env/runtime 双通道——runtime_configs 键优先）。
    HARDWARE_OCR_AUTO_DIRECT_ENABLED: bool = False
    HARDWARE_OCR_AUTO_DIRECT_MIN_CONFIDENCE: float = 0.9
    # 五金库物资目录镜像（平台→Bitable 单向同步；「五金库物资目录（平台镜像·
    # 单向）」base/table，领/退料审批表单的引用数据源。清空任一值=同步自空转）。
    HARDWARE_MIRROR_BASE_TOKEN: str = "U8h6b5puUaHH7Hsf7focp9fGnze"
    HARDWARE_MIRROR_TABLE_ID: str = "tblK7MkjceniZOjX"
    # 五金库月度用量管控表（部门×月份×物资 需求vs用量比对行自动回填；Base
    # 复用镜像 BASE_TOKEN，本值=「月度用量管控」table。默认空=任务自空转）。
    HARDWARE_USAGE_TABLE_ID: str = ""
    # 五金库紧急领料（2026-11-20 改版：审批打标+先发后批）仓管加急卡通知
    # 目标：逗号分隔 open_id/chat_id（send_card_to_target 按前缀分流私发/群
    # 发）。默认胡永晟+姚薇娜（2026-11-23 拍板：五金劳保仓管员/组长；ou_ 为
    # 仓储应用作用域——identity.feishu_open_id 是库存作用域，跨应用发送会
    # 99991672，须以仓储凭证 contact API 解析为准）。
    HARDWARE_URGENT_NOTIFY_TARGETS: str = (
        "ou_32d59e1f55f87d5405fca52711f8534b,"  # 胡永晟（五金劳保组组长）
        "ou_7ed75f21cab0ed89c545563f3ca4bc70"  # 姚薇娜（五金劳保仓管员）
    )
    # 仓库机器人 open_id（部署身份：gateway 去重排除自身消息；未配置回退 gateway 代码常量）
    WAREHOUSE_FEISHU_BOT_OPEN_ID: str = ""
    # Runner tool-calling 循环上限 / 会话历史注入轮数（S1 ticket 03）
    WAREHOUSE_AGENT_MAX_TURNS: int = 10
    WAREHOUSE_AGENT_SESSION_ROUNDS: int = 12


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.check()
    return settings
