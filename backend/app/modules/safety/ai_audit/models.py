"""AI 调用审计 ORM。

``safety.ai_call_audits`` 为 append-only 审计表：

- 不做软删除（``is_deleted`` 继承自 BaseModel 但恒为 false，任何业务代码不得置位）
- 唯一允许的删除是归档脚本（>12 个月导出 MinIO 后物理删除）
- 关联字段（resource_id / user_id）按项目规范不建数据库级外键
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel

# 场景枚举（宽松存储为字符串，便于新增场景无需 migration）
SCENARIO_HAZARD_IDENTIFICATION = "hazard_identification"
SCENARIO_HAZARD_ID_BITABLE = "hazard_id_bitable"  # 危险源辨识 Bitable 事件流（与 hazard_identification 区分：后者为隐患识别）
SCENARIO_RECTIFICATION_REVIEW = "rectification_review"
SCENARIO_AGENT_CHAT = "agent_chat"
SCENARIO_KNOWLEDGE_CHAT = "knowledge_chat"
SCENARIO_GRAPH_BUILD = "graph_build"
SCENARIO_REGULATION_CRAWL = "regulation_crawl"
SCENARIO_DRILL_PLAN_GENERATION = "drill_plan_generation"
SCENARIO_DRILL_REPORT_GENERATION = "drill_report_generation"  # 已废弃，保留兼容
SCENARIO_DRILL_ISSUE_PARSING = "drill_issue_parsing"
SCENARIO_DRILL_PLAN_PARSING = "drill_plan_parsing"
SCENARIO_DRILL_EVAL_PARSING = "drill_eval_parsing"  # 旧人工链路，已废弃，保留兼容
SCENARIO_DRILL_EVAL_GENERATION = "drill_eval_generation"
SCENARIO_EMBEDDING = "embedding"
SCENARIO_RERANK = "rerank"
SCENARIO_MEMORY_EXTRACTION = "memory_extraction"
SCENARIO_DAILY_REPORT_ANALYSIS = "daily_report_analysis"
SCENARIO_EHS_CHANGE_REVIEW = "ehs_change_review"
SCENARIO_CONTRACTOR_ADMISSION_REVIEW = "contractor_admission_review"  # 相关方准入 AI 审核
SCENARIO_URS_REVIEW = "urs_review"
SCENARIO_MSDS_EXTRACTION = "msds_extraction"
SCENARIO_SOP_GENERATION = "sop_generation"
SCENARIO_SOP_REVIEW = "sop_review"
SCENARIO_OH_EXAM_REPORT_PARSING = "oh_exam_report_parsing"
SCENARIO_OH_TRANSFER_HAZARD_DIFF = "oh_transfer_hazard_diff"
SCENARIO_FIRE_ALARM_ANALYSIS = "fire_alarm_analysis"  # 消防报警逐条/日报汇总/周报汇总 AI 分析
SCENARIO_CENTRAL_ALARM_ANALYSIS = "central_alarm_analysis"  # 中控报警逐条/日报汇总 AI 分析
SCENARIO_CHEMICAL_INVENTORY_RISK_SCAN = "chemical_inventory_risk_scan"  # 危化品库存 AI 风险扫描
SCENARIO_UNKNOWN = "unknown"


class AICallAudit(BaseModel):
    """一次 AI 调用的完整审计记录。"""

    __tablename__ = "ai_call_audits"
    __table_args__ = (
        Index("idx_ai_audits_scenario_created", "scenario", "created_at"),
        Index("idx_ai_audits_resource", "resource_type", "resource_id"),
        Index("idx_ai_audits_trace", "trace_id"),
        Index("idx_ai_audits_created_at", "created_at"),
        {"schema": "safety"},
    )

    # ── 链路 ──
    trace_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="业务操作级 trace（二期切换 OTel trace_id）"
    )
    scenario: Mapped[str] = mapped_column(
        String(64), default=SCENARIO_UNKNOWN,
        comment="hazard_identification / rectification_review / agent_chat / knowledge_chat / graph_build / unknown",
    )
    resource_type: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="hazard / knowledge_article / session 等"
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="业务对象 ID（如 hazard_id），无 FK 约束"
    )
    session_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="Agent 会话 ID"
    )
    channel: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="调用渠道：web / feishu / system"
    )

    # ── 主体（等保五元组的 user/ip/时间；时间用 created_at） ──
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="identity.users.id，无 FK 约束"
    )
    user_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ── 调用 ──
    model: Mapped[str] = mapped_column(String(128), comment="deepseek-v4-flash / qwen-vl-max 等")
    prompt_version: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="system prompt 内容 sha256 前 12 位"
    )
    input_text: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="messages 序列化全文（超限截断）"
    )
    input_truncated: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    output_text: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="模型输出全文（超限截断）"
    )
    output_truncated: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    # ── 量化 ──
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_hit_tokens: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="DeepSeek prompt_cache_hit_tokens（前缀命中 token 数）"
    )
    cache_miss_tokens: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="DeepSeek prompt_cache_miss_tokens（前缀未命中 token 数）"
    )

    # ── 结果与依据 ──
    status: Mapped[str] = mapped_column(
        String(16), default="success", comment="success / failed"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    degradation_level: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="RAG 检索降级级别：full / llm_expanded / text_only / fallback 等"
    )
    cited_sources: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, comment="引用法规 [{doc_title, article_ref}, ...]"
    )
    guard_hits: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, comment="禁语命中列表"
    )
    extra: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="场景专有字段（pending_action / approved / document_ids 等）"
    )
