"""EHS变更 service 包（原 service/ehs_change.py 拆分，CLAUDE.md 拆目录规范）。

change.py — EhsChangeService（EHS变更申请/审批）
urs.py    — URSService（URS 智能审核，设备采购 EHS 合规审核）
"""

from app.modules.safety.service.ehs_change.change import EhsChangeService
from app.modules.safety.service.ehs_change.urs import URSService

__all__ = ["EhsChangeService", "URSService"]
