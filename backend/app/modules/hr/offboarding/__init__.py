"""HR 离职管理子包：离职办结单状态机 + 清退会签 + 证明开具/送达签收闭环。

方案见 docs/离职管理-制作方案规划.md。流程主干 = OffboardingCase：
    draft 申请登记 → approving 离职审批（飞书编排/站内降级）
    → clearing 清退会签 → cert_issuing 证明开具（HR 核对）
    → delivering 送达（邮件自动+短信预留）→ signed 员工签字确认
    → closed 办结（档案/证件/花名册/台账四联动）
"""
