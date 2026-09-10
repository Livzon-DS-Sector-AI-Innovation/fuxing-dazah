"""作业票审核（workticket-review）领域子包。

聚合导出平台工作流客户端及 8 类标准作业票的 processDefinitionKey 常量，
以及票据解析器（WorkTicket / GasRecord / WorkTicketParser）。
"""

from app.modules.safety.workticket_review.client import (
    AUTH_BASIC,
    BASE_URL,
    ORG_CODE,
    PASSWORD_MD5,
    STANDARD_TICKET_TYPES,
    TENANT_ID,
    TICKET_TYPE_KEYS,
    USERNAME,
    WorkTicketPlatformClient,
)
from app.modules.safety.workticket_review.parser import (
    FIELD_MAP,
    GAS_ARRAY_KEYS,
    GAS_COLUMNS,
    GASLESS_TYPES,
    PERSONNEL_ARRAY_KEYS,
    PERSONNEL_COLUMNS,
    GasRecord,
    PersonnelRecord,
    WorkTicket,
    WorkTicketParser,
)
from app.modules.safety.workticket_review.report_builder import (
    MEASURE_ADVICE,
    TICKET_TYPE_NAMES,
    WorkTicketReviewReportBuilder,
)
from app.modules.safety.workticket_review.repository import WorkTicketReviewRepository
from app.modules.safety.workticket_review.rule_engine import (
    DEFAULT_DONGHUO_HOURS,
    DONGHUO_LEVEL_HOURS,
    DURATION_LIMIT_BY_TYPE,
    GAS_BEARING_TYPES,
    RULE_NAME_MAP,
    RuleNo,
    Violation,
    WorkTicketRuleEngine,
)
from app.modules.safety.workticket_review.service import (
    REPORT_GROUP_CHAT_ID,
    WorkTicketReviewService,
)

__all__ = [
    "BASE_URL",
    "USERNAME",
    "PASSWORD_MD5",
    "TENANT_ID",
    "ORG_CODE",
    "AUTH_BASIC",
    "TICKET_TYPE_KEYS",
    "STANDARD_TICKET_TYPES",
    "FIELD_MAP",
    "GAS_ARRAY_KEYS",
    "GAS_COLUMNS",
    "GASLESS_TYPES",
    "WorkTicket",
    "GasRecord",
    "WorkTicketParser",
    "WorkTicketPlatformClient",
    "WorkTicketReviewRepository",
    "WorkTicketReviewReportBuilder",
    "TICKET_TYPE_NAMES",
    "MEASURE_ADVICE",
    "RuleNo",
    "Violation",
    "WorkTicketRuleEngine",
    "DURATION_LIMIT_BY_TYPE",
    "DONGHUO_LEVEL_HOURS",
    "DEFAULT_DONGHUO_HOURS",
    "GAS_BEARING_TYPES",
    "RULE_NAME_MAP",
    "REPORT_GROUP_CHAT_ID",
    "WorkTicketReviewService",
]
