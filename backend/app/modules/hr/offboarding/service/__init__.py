"""离职管理业务服务层（对外入口）。

按职责拆成三个子模块，本包 re-export 公开对象，外部统一写
``from app.modules.hr.offboarding import service``：
- case      办结单：建单/编辑/取消、发起审批、站内登记、清退明细、离岗体检
- certify   证明：核对开具、送达补发、签收（到人事办公室当面手写签名 / 纸质签收登记）
- closing   办结联动（档案/证件/花名册/入职台账/离职台账/劳动合同）

SQLAlchemy async 铁律：UPDATE 后 flush 不 re-fetch 会触发 MissingGreenlet，
各写操作统一经 common.refetch 重查后返回。
"""

from app.modules.hr.offboarding.service.case import (
    cancel_case,
    create_case,
    lead_time_warning,
    ledger_offboarding_type,
    manual_stage_done,
    read_health_check_file,
    record_handover,
    register_health_check,
    replace_clearance_items,
    submit_approval,
    submit_clearance,
    sync_open_cases_from_ledger,
    update_case,
)
from app.modules.hr.offboarding.service.certify import (
    cert_fields,
    issue_certificate,
    read_certificate_pdf,
    register_paper_sign,
    register_signature,
    register_sms_sent,
    resend_delivery,
    validate_signature,
)
from app.modules.hr.offboarding.service.closing import close_case
from app.modules.hr.offboarding.service.common import (
    get_or_404,
    linked_record,
    notify_context,
    upsert_departure_record,
)

__all__ = [
    "cancel_case",
    "cert_fields",
    "close_case",
    "create_case",
    "get_or_404",
    "issue_certificate",
    "lead_time_warning",
    "ledger_offboarding_type",
    "linked_record",
    "manual_stage_done",
    "notify_context",
    "read_certificate_pdf",
    "read_health_check_file",
    "record_handover",
    "register_health_check",
    "register_paper_sign",
    "register_signature",
    "register_sms_sent",
    "replace_clearance_items",
    "resend_delivery",
    "submit_approval",
    "submit_clearance",
    "sync_open_cases_from_ledger",
    "update_case",
    "upsert_departure_record",
    "validate_signature",
]
