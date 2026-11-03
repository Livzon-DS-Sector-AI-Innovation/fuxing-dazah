"""Super-agent 底座持久化模型（PG schema ``superagent``）。

表清单按设计文档 §5 分切片落位（迁移 A/B/C/D 各管一批，播种一律
ON CONFLICT DO NOTHING）：

- 迁移 A（事件层）：agent_sources / agent_source_cursors / agent_triggers / agent_threads
- 迁移 B（副作用层）：agent_effects / agent_outbox / agent_health
- 迁移 C（任务域）：agent_tasks / agent_task_subscriptions / agent_inputs
- 迁移 D（策略层）：agent_policies / agent_decisions

项目规范：外键通过字段命名约定关联，不创建数据库级 FK 约束；
平台级表不带 created_by/updated_by（对齐 audit schema 惯例）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Identity,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import Base


class AgentSource(Base):
    """Source 注册实例（kind=插件稳定标识；一行=一个事件来源实例）。"""

    __tablename__ = "agent_sources"
    __table_args__ = (
        Index("uq_agent_sources_name", "name", unique=True),
        {"schema": "superagent"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    kind: Mapped[str] = mapped_column(String(64), comment="插件稳定标识（cron_tick/bitable_poll/...）")
    name: Mapped[str] = mapped_column(String(128), comment="实例名（唯一）")
    config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}",
                                         comment="实例配置（schedule/filters/通道等，按 kind 解释）")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false",
                                          comment="实例级开关（每轮热查）")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )


class AgentSourceCursor(Base):
    """持久化读位（source_id+name 唯一；推进仅在所覆盖 Trigger 全部落库后，同事务）。"""

    __tablename__ = "agent_source_cursors"
    __table_args__ = (
        Index("uq_agent_source_cursors", "source_id", "name", unique=True),
        {"schema": "superagent"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), comment="关联 agent_sources.id",
    )
    name: Mapped[str] = mapped_column(String(128), comment="读位名（如 last_tick / last_modified）")
    value: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}",
                                        comment="读位值（水位/指纹等 JSON）")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )


class AgentTrigger(Base):
    """不可变事件（(source_id, external_id) 唯一 = DB 级幂等；disposition 追加式）。

    payload 一切消息文本是不可信数据，永不参与授权判定（红线⑦）。
    channel（回哪里）约定存于 payload["channel"]。
    """

    __tablename__ = "agent_triggers"
    __table_args__ = (
        Index("uq_agent_triggers_external", "source_id", "external_id", unique=True),
        Index("ix_agent_triggers_thread", "thread_key"),
        Index("ix_agent_triggers_received_at", "received_at"),
        {"schema": "superagent"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), comment="关联 agent_sources.id",
    )
    external_id: Mapped[str] = mapped_column(String(512), comment="来源侧幂等键（job:计划时间 / record_id:指纹）")
    thread_key: Mapped[str] = mapped_column(String(512), comment="归属线程键")
    actor: Mapped[dict | None] = mapped_column(JSONB, nullable=True,
                                               comment="来源原生身份（id/type/name；授权只看结构化字段）")
    human: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false",
                                        comment="是否人")
    addressed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false",
                                            comment="是否点名（@/直接请求）")
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}",
                                          comment="事件载荷（channel 约定在 payload.channel；文本不可信）")
    disposition: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]",
                                              comment="追加式处置轨迹 [{step,at,reason}]")
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="落库时间",
    )


class AgentThread(Base):
    """同话题事件的时间序集合（thread_key 唯一；一条飞书话题/一条 Bitable 记录=一线程）。"""

    __tablename__ = "agent_threads"
    __table_args__ = (
        Index("uq_agent_threads_key", "thread_key", unique=True),
        {"schema": "superagent"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    thread_key: Mapped[str] = mapped_column(String(512), comment="线程键")
    label: Mapped[str | None] = mapped_column(String(256), nullable=True, comment="展示名")
    url: Mapped[str | None] = mapped_column(Text, nullable=True, comment="跳转链接")
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    last_trigger_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最近 Trigger 落库时间",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )


# ═══════════════════════════════════════════════════════════════
# 迁移 C（任务域）
# ═══════════════════════════════════════════════════════════════


class AgentTask(Base):
    """任务 —— 一次被授权的工作（概念名「任务」，刻意避开作业票 work_ticket 撞名）。

    阶段不落库：所有观测口径统一走 derive_stage(stage_facts) 纯函数现算。
    mandate 记录授权依据（policy_version/scope/strength/命中规则/发起人来源身份）。
    """

    __tablename__ = "agent_tasks"
    __table_args__ = (
        Index("ix_agent_tasks_status", "status"),
        Index("ix_agent_tasks_origin_trigger", "origin_trigger_id"),
        {"schema": "superagent"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    short_name: Mapped[str] = mapped_column(String(128), comment="短名（人类可读标识）")
    title: Mapped[str] = mapped_column(String(256), comment="任务标题")
    executor: Mapped[str] = mapped_column(String(64), comment="程序执行器名（注册制）")
    origin_trigger_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="开单来源 Trigger",
    )
    mandate: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}",
                                          comment="授权依据（版本/范围/强度/规则/发起人）")
    stage_facts: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default="{}",
        comment="阶段推导输入事实（最新报告/未读输入/是否等人）",
    )
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open",
                                        comment="open/ended")
    outcome: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="终态结果")
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )


class AgentTaskSubscription(Base):
    """任务订阅 —— 开单即订阅 origin Thread；ended 任务保留订阅（人的消息可唤醒）。"""

    __tablename__ = "agent_task_subscriptions"
    __table_args__ = (
        Index("uq_agent_task_subscriptions", "task_id", "thread_key", unique=True),
        Index("ix_agent_task_subscriptions_thread", "thread_key"),
        {"schema": "superagent"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), comment="关联 agent_tasks.id")
    thread_key: Mapped[str] = mapped_column(String(512), comment="订阅的线程键")
    context_only: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false",
        comment="仅上下文订阅（不授新权）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )


class AgentInput(Base):
    """任务输入 —— Trigger 直通/系统消息（policy_changed 等）。

    read_at 语义对齐仓库「计入会话历史才算读」：执行器消费后才置。
    """

    __tablename__ = "agent_inputs"
    __table_args__ = (
        Index("ix_agent_inputs_task_read", "task_id", "read_at"),
        Index("ix_agent_inputs_trigger", "trigger_id"),
        {"schema": "superagent"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), comment="关联 agent_tasks.id")
    trigger_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="来源 Trigger（系统输入为空）",
    )
    kind: Mapped[str] = mapped_column(String(32), default="trigger", server_default="trigger",
                                      comment="trigger/system")
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="投递时间",
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="计入会话历史（被消费）时间",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )


# ═══════════════════════════════════════════════════════════════
# 迁移 D（策略层）
# ═══════════════════════════════════════════════════════════════


class AgentPolicy(Base):
    """Policy 版本 —— 不可变（rules+accept_mode+admission 哈希成版本号）。

    当前版本 = 最新 created_at 行（不另建 KV 指针表）。
    """

    __tablename__ = "agent_policies"
    __table_args__ = (
        Index("uq_agent_policies_version", "version_hash", unique=True),
        {"schema": "superagent"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    version_hash: Mapped[str] = mapped_column(String(64), comment="内容哈希（版本号）")
    rules: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]",
                                        comment="规则声明（rule_id/enabled/conditions/action）")
    accept_mode: Mapped[str] = mapped_column(String(16), default="observe", server_default="observe",
                                             comment="off/observe/auto（全局，可按规则覆写）")
    admission: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}",
                                            comment="Gate 三维准入表（默认保守）")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )


class AgentDecision(Base):
    """研判决策 —— observe 回放数据源（would_accept 的 Decision 摘要）。

    explicit 请求任何模式都受理（对人的承诺）；inferred 受 accept_mode 管辖。
    """

    __tablename__ = "agent_decisions"
    __table_args__ = (
        Index("ix_agent_decisions_trigger", "trigger_id"),
        Index("ix_agent_decisions_replay", "replay", "created_at"),
        {"schema": "superagent"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    trigger_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), comment="关联 agent_triggers.id")
    eval_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="同批研判分组 id",
    )
    rule_id: Mapped[str] = mapped_column(String(64), comment="命中/评估的规则 id")
    outcome: Mapped[str] = mapped_column(String(16),
                                         comment="accept/stop/ignore/unavailable")
    would_accept: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false",
                                               comment="observe 模式回放：评估是否通过")
    reason: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}",
                                         comment="证据（命中条件/门槛/防重复开工检查）")
    policy_version: Mapped[str] = mapped_column(String(64), comment="决策时 Policy 版本")
    mode: Mapped[str] = mapped_column(String(16), comment="决策时模式 off/observe/auto")
    replay: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false",
                                         comment="历史回放标注（不污染在线 observe 计数）")
    resolution: Mapped[str | None] = mapped_column(String(16), nullable=True,
                                                   comment="处置：promoted/dismissed（人工）")
    resolved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )


# ═══════════════════════════════════════════════════════════════
# 迁移 B（副作用层）
# ═══════════════════════════════════════════════════════════════


class AgentEffect(Base):
    """外部副作用队列 —— 一切副作用先入库后执行（可对账、重启不丢）。

    待处理 (kind, dedupe_key) 部分唯一：重复入队=替换 payload 并立即到期；
    SKIP LOCKED 领取；失败指数退避；Later 不计失败；连续 3 次失败健康告警。
    行内 payload 携带的地址（chat_id 等）是唯一权威，任何下游不可覆盖。
    """

    __tablename__ = "agent_effects"
    __table_args__ = (
        Index(
            "uq_agent_effects_pending", "kind", "dedupe_key", unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_agent_effects_due", "status", "next_due_at"),
        {"schema": "superagent"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    kind: Mapped[str] = mapped_column(String(64), comment="效果类型（注册制 handler 名）")
    dedupe_key: Mapped[str] = mapped_column(String(512), comment="幂等键（同键待处理仅一行）")
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}",
                                          comment="载荷（含权威地址；文本不可信）")
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending",
                                        comment="pending/running/done/failed")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0",
                                          comment="失败次数（Later 不计）")
    next_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="下次到期时间",
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )


class AgentOutboxMessage(Base):
    """会话内保序消息 —— 同 (task, conversation) 严格按 seq 顺序发送。

    先发的失败不堵别家（不同 conversation 互不阻塞）；channel 行内地址
    不可被下游（含总卡聚合）覆盖——修「push 指定群被总卡吞 chat_id」事故根因。
    """

    __tablename__ = "agent_outbox"
    __table_args__ = (
        Index("uq_agent_outbox_seq", "seq", unique=True),
        Index("ix_agent_outbox_conv", "conversation", "status", "seq"),
        Index("ix_agent_outbox_task", "task_id"),
        {"schema": "superagent"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    seq: Mapped[int] = mapped_column(BigInteger, Identity(), comment="入队序（同会话严格保序依据）")
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True,
                                                      comment="关联 agent_tasks.id（可空）")
    conversation: Mapped[str] = mapped_column(String(512), comment="会话键（排序粒度）")
    channel: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}",
                                          comment="权威地址（chat_id/open_id 等；不可覆盖）")
    purpose: Mapped[str] = mapped_column(String(64), default="message", comment="用途标签")
    body: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending",
                                        comment="pending/sent/dropped")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="队头重试节流到期时间（保序：后续消息等待队头）",
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dropped_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )


class AgentHealth(Base):
    """组件健康 —— 一组件一行认领制（拒绝重复认领，防多写者漂移）。"""

    __tablename__ = "agent_health"
    __table_args__ = (
        Index("uq_agent_health_component", "component", unique=True),
        {"schema": "superagent"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    component: Mapped[str] = mapped_column(String(64), comment="组件名（source:<name>/effects/outbox/watchdog）")
    state: Mapped[str] = mapped_column(String(16), default="paused", server_default="paused",
                                       comment="ready/error/paused")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(128), nullable=True,
                                                   comment="认领者（host:pid）")
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
