"""Safety ORM models."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

# 枚举集中定义在 models/enums.py（保持单一定义点）
from app.modules.safety.models.enums import *  # noqa: F401,F403
from app.shared.base_model import BaseModel

# 业务表均软删除（is_deleted），唯一编号约束使用部分唯一索引
# (WHERE is_deleted = false)，避免「软删→重建同编号」触发约束冲突。
# 见 CLAUDE.md「软删除隐形 bug」注意事项。


# ==================== 安全知识库 ====================


class SafetyKnowledgeArticle(BaseModel):
    """安全知识库文章表"""

    __tablename__ = "knowledge_articles"
    __table_args__ = {"schema": "safety"}

    # ── Columns present in DB ──
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="文章标题")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="摘要")
    content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="正文内容")
    tags: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="标签（逗号分隔）")
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, default="other", server_default="other", comment="分类"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="draft", server_default="draft", nullable=False,
        comment="状态: draft/published/archived"
    )
    view_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False, comment="浏览次数"
    )
    attachment_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="附件路径"
    )
    attachment_original_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="附件原始文件名"
    )

    article_no: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="文档编号")
    feishu_record_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True, comment="飞书Bitable记录ID")
    source: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="来源/出处")
    author: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="作者/发布单位")
    publish_date: Mapped[datetime | None] = mapped_column(Date, nullable=True, comment="发布日期")
    implementation_date: Mapped[datetime | None] = mapped_column(Date, nullable=True, comment="实施日期")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False, comment="版本号")
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, comment="被替代为（指向新版本文档）")
    knowledge_card: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, comment="知识卡片JSON")
    card_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="卡片生成时间")
    card_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False, comment="知识卡片版本号")
    full_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="全文内容")
    full_text_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="全文Hash")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False, comment="chunk数量")
    feishu_table_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="飞书多维表格ID")
    feishu_shared_url: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="飞书记录分享链接")


class RegulationChunk(BaseModel):
    """法规条款分块（RAG 检索目标）"""

    __tablename__ = "regulation_chunks"
    __table_args__ = (
        Index("ix_regulation_chunks_article_id", "article_id"),
        Index("ix_regulation_chunks_chunk_index", "chunk_index"),
        Index("ix_regulation_chunks_doc_category", "doc_category"),
        Index("ix_regulation_chunks_priority", "priority"),
        {"schema": "safety"},
    )

    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("safety.knowledge_articles.id"), nullable=False,
        comment="所属法规文档 ID",
    )
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False, comment="条款原文")
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="在文档中的序号")
    doc_title: Mapped[str] = mapped_column(String(500), nullable=False, comment="文档标题")
    doc_category: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="文档类别")
    chapter_title: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="章节标题")
    article_ref: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="条款编号")
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True, comment="向量嵌入（JSON 数组字符串）")
    priority: Mapped[str] = mapped_column(
        String(2), nullable=False, default="P2", server_default="P2", comment="优先级"
    )
    cites_chunk_ids: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True, comment="引用的其他 chunk ID")
    cited_by_chunk_ids: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True, comment="被其他 chunk 引用")
    entity_ids: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True, comment="关联实体 ID 列表")


