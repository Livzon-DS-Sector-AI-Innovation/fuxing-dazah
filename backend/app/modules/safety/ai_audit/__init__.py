"""AI 调用审计（合规留痕层）。

四套 AI 系统（隐患识别 / 整改初审 / 业务 Agent / 知识库 RAG）+ 图谱构建等
所有 AI 调用的审计留痕，满足：

- 《网络安全法》第二十一条：日志留存不少于 6 个月（本表在线保留 12 个月 + 归档）
- 《生成式人工智能服务管理暂行办法》第十七条：数据处理路径与决策依据可追溯
- GB/T 45654-2025：指令 / 输出摘要 / 策略命中 / 人工干预留痕

分层：
- ``models.py``          — ``safety.ai_call_audits`` ORM（append-only，无软删除语义）
- ``context.py``         — contextvars 审计上下文（scenario / resource / user / trace_id）
- ``audited_client.py``  — AuditedAIService：覆写 chat/chat_vision 捕获 usage 并落表
- ``store.py``           — 审计写入 + 查询 / 统计（repository + service 职责）
- ``schemas.py``         — API 契约

写入原则：独立 session、失败仅告警不阻塞业务、业务事务回滚不影响审计。
"""

from app.modules.safety.ai_audit.audited_client import write_audit_record
from app.modules.safety.ai_audit.context import (
    AIAuditContext,
    ai_audit_scope,
    current_audit_ctx,
)
from app.modules.safety.ai_audit.models import AICallAudit

__all__ = [
    "AICallAudit",
    "AIAuditContext",
    "ai_audit_scope",
    "current_audit_ctx",
    "write_audit_record",
]
