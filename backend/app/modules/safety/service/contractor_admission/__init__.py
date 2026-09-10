"""相关方准入 service 包（原 service/contractor_admission.py 目录化，CLAUDE.md 拆目录规范）。

service.py — ContractorAdmissionService（Bitable 同步 upsert / 软删除 / AI 审核编排）
"""

from app.modules.safety.service.contractor_admission.service import (
    ContractorAdmissionService,
)

__all__ = ["ContractorAdmissionService"]
