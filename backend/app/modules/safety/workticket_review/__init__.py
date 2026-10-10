"""作业票审核（workticket-review）领域子包。

聚合导出平台工作流客户端及 8 类标准作业票的 processDefinitionKey 常量，
以及票据解析器（WorkTicket / GasRecord / WorkTicketParser）。
"""

from app.modules.safety.workticket_review.client import (
    STANDARD_TICKET_TYPES,
    TICKET_TYPE_KEYS,
    WorkTicketPlatformClient,
    platform_auth_basic,
    platform_base_url,
    platform_org_code,
    platform_password_md5,
    platform_tenant_id,
    platform_username,
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
    WorkTicketReviewService,
    report_group_chat_id,
)

__all__ = [
    "platform_base_url",
    "platform_username",
    "platform_password_md5",
    "platform_tenant_id",
    "platform_org_code",
    "platform_auth_basic",
    "TICKET_TYPE_KEYS",
    "STANDARD_TICKET_TYPES",
    "FIELD_MAP",
    "GAS_ARRAY_KEYS",
    "GAS_COLUMNS",
    "GASLESS_TYPES",
    "PERSONNEL_ARRAY_KEYS",
    "PERSONNEL_COLUMNS",
    "PersonnelRecord",
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
    "WorkTicketReviewService",
    "report_group_chat_id",
]
