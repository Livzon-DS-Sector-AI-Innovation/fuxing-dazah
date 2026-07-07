"""知识图谱 ORM 模型 — 图节点与边。

表：
- safety.knowledge_graph_nodes: 图谱节点（法规文档/条款/安全实体/分类/概念）
- safety.knowledge_graph_edges: 图谱边（引用/补充/替代/归属/相关/冲突）
"""

import uuid as _uuid

from sqlalchemy import Double, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import BaseModel


class KnowledgeGraphNode(BaseModel):
    """知识图谱节点。

    节点类型 (node_type):
      - document: 法规文档（关联 knowledge_articles）
      - clause:   法规条款（关联 knowledge_articles 的特定条款）
      - entity:   安全实体（设备/状态/场所/作业/物料/标准）
      - category: 分类节点（如"防爆电气"）
      - concept:  抽象概念（如"双重预防机制"）

    实体类别 (entity_type, 仅 node_type=entity):
      - equipment / condition / location / operation / material / standard
    """

    __tablename__ = "knowledge_graph_nodes"
    __table_args__ = {"schema": "safety"}

    # ── 基本信息 ──
    name: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="节点名称（规范术语）",
    )
    node_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="节点类型: document/clause/entity/category/concept",
    )
    aliases: Mapped[list | None] = mapped_column(
        ARRAY(Text), nullable=True, comment="同义词/别名列表",
    )

    # ── 关联 ──
    article_id: Mapped[_uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True,
        comment="关联 knowledge_articles.id（document/clause 类型时填充）",
    )
    entity_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="实体类别: equipment/condition/location/operation/material/standard",
    )

    # ── AI 生成内容 ──
    ai_summary: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI 对该节点的简短描述",
    )
    confidence: Mapped[float | None] = mapped_column(
        Double, nullable=True, comment="AI 生成的置信度 (0.0-1.0)",
    )

    # ── 状态 ──
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ai_generated", server_default="ai_generated",
        comment="ai_generated / human_confirmed / deprecated / merged",
    )
    merged_into_id: Mapped[_uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
        comment="合并到另一个节点的 ID",
    )

    # ── 元数据 ──
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True, comment="扩展元数据",
    )

    # ── 关系 (ORM only, 无 FK 约束) ──
    outgoing_edges: Mapped[list["KnowledgeGraphEdge"]] = relationship(
        "KnowledgeGraphEdge",
        foreign_keys="KnowledgeGraphEdge.source_node_id",
        back_populates="source_node",
        lazy="selectin",
    )
    incoming_edges: Mapped[list["KnowledgeGraphEdge"]] = relationship(
        "KnowledgeGraphEdge",
        foreign_keys="KnowledgeGraphEdge.target_node_id",
        back_populates="target_node",
        lazy="selectin",
    )


class KnowledgeGraphEdge(BaseModel):
    """知识图谱边 — 节点之间的关系。

    关系类型 (relation_type):
      - cites:           引用（doc A 明确引用了 doc B）
      - supplements:     补充（doc A 是对 doc B 的细化/补充）
      - replaces:        替代（doc A 替代了 doc B）
      - belongs_to:      归属（实体 X 属于分类 Y）
      - related_to:      相关（语义相关但无明确引用）
      - conflicts_with:  冲突（两个文档规定有矛盾）

    状态 (status):
      - ai_generated:     AI 自动生成
      - human_confirmed:  人工已确认
      - human_deleted:    人工已删除（软删除）
      - human_added:      人工手动新增
    """

    __tablename__ = "knowledge_graph_edges"
    __table_args__ = (
        UniqueConstraint("source_node_id", "target_node_id", "relation_type"),
        {"schema": "safety"},
    )

    # ── 两端节点 ──
    source_node_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("safety.knowledge_graph_nodes.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="源节点 ID",
    )
    target_node_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("safety.knowledge_graph_nodes.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="目标节点 ID",
    )

    # ── 关系描述 ──
    relation_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True,
        comment="cites / supplements / replaces / belongs_to / related_to / conflicts_with",
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI 对关系的简短解释",
    )
    evidence_text: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="支持该关系的原文片段",
    )

    # ── AI 评分 ──
    confidence: Mapped[float | None] = mapped_column(
        Double, nullable=True, comment="AI 生成的置信度 (0.0-1.0)",
    )

    # ── 状态 ──
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ai_generated", server_default="ai_generated",
        comment="ai_generated / human_confirmed / human_deleted / human_added",
    )

    # ── 元数据 ──
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True, comment="扩展元数据",
    )

    # ── ORM 关系 ──
    source_node: Mapped["KnowledgeGraphNode"] = relationship(
        "KnowledgeGraphNode",
        foreign_keys=[source_node_id],
        back_populates="outgoing_edges",
    )
    target_node: Mapped["KnowledgeGraphNode"] = relationship(
        "KnowledgeGraphNode",
        foreign_keys=[target_node_id],
        back_populates="incoming_edges",
    )
