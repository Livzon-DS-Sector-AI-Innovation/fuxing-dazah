"""知识图谱 Pydantic Schema — API 请求/响应模型。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ═══════════════════════════════════════════════════════════════
# 枚举常量
# ═══════════════════════════════════════════════════════════════

NODE_TYPES: list[str] = ["document", "clause", "entity", "category", "concept"]
ENTITY_TYPES: list[str] = ["equipment", "condition", "location", "operation", "material", "standard"]
RELATION_TYPES: list[str] = [
    "cites", "supplements", "replaces", "belongs_to", "related_to", "conflicts_with",
]
NODE_STATUSES: list[str] = ["ai_generated", "human_confirmed", "deprecated", "merged"]
EDGE_STATUSES: list[str] = ["ai_generated", "human_confirmed", "human_deleted", "human_added"]


# ═══════════════════════════════════════════════════════════════
# 节点
# ═══════════════════════════════════════════════════════════════

class GraphNodeBase(BaseModel):
    """图谱节点基础字段。"""
    name: str = Field(..., max_length=500, description="节点名称")
    node_type: str = Field(..., pattern="^(document|clause|entity|category|concept)$", description="节点类型")
    aliases: list[str] | None = Field(default=None, description="别名列表")
    article_id: UUID | None = Field(default=None, description="关联文档 ID")
    entity_type: str | None = Field(
        default=None,
        pattern="^(equipment|condition|location|operation|material|standard)$",
        description="实体类别",
    )
    ai_summary: str | None = Field(default=None, description="AI 生成摘要")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0, description="AI 置信度")
    status: str = Field(
        default="ai_generated",
        pattern="^(ai_generated|human_confirmed|deprecated|merged)$",
        description="节点状态",
    )
    merged_into_id: UUID | None = Field(default=None, description="合并目标节点 ID")
    metadata: dict | None = Field(default=None, description="扩展元数据")


class GraphNodeCreate(GraphNodeBase):
    """创建图谱节点。"""


class GraphNodeUpdate(BaseModel):
    """更新图谱节点（所有字段可选）。"""
    name: str | None = Field(default=None, max_length=500)
    node_type: str | None = Field(default=None, pattern="^(document|clause|entity|category|concept)$")
    aliases: list[str] | None = None
    article_id: UUID | None = None
    entity_type: str | None = Field(
        default=None, pattern="^(equipment|condition|location|operation|material|standard)$",
    )
    ai_summary: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: str | None = Field(default=None, pattern="^(ai_generated|human_confirmed|deprecated|merged)$")
    merged_into_id: UUID | None = None
    metadata: dict | None = None


class GraphNodeResponse(BaseModel):
    """图谱节点 API 响应。"""
    id: UUID
    name: str
    node_type: str
    aliases: list[str] | None = None
    article_id: UUID | None = None
    entity_type: str | None = None
    ai_summary: str | None = None
    confidence: float | None = None
    status: str
    merged_into_id: UUID | None = None
    metadata: dict | None = Field(default=None, validation_alias="metadata_")
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════
# 边
# ═══════════════════════════════════════════════════════════════

class GraphEdgeBase(BaseModel):
    """图谱边基础字段。"""
    source_node_id: UUID = Field(..., description="源节点 ID")
    target_node_id: UUID = Field(..., description="目标节点 ID")
    relation_type: str = Field(
        ...,
        pattern="^(cites|supplements|replaces|belongs_to|related_to|conflicts_with)$",
        description="关系类型",
    )
    description: str | None = Field(default=None, description="关系说明")
    evidence_text: str | None = Field(default=None, description="原文证据")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0, description="AI 置信度")
    status: str = Field(
        default="ai_generated",
        pattern="^(ai_generated|human_confirmed|human_deleted|human_added)$",
        description="边状态",
    )
    metadata: dict | None = Field(default=None, description="扩展元数据")


class GraphEdgeCreate(GraphEdgeBase):
    """创建图谱边。"""


class GraphEdgeUpdate(BaseModel):
    """更新图谱边（所有字段可选）。"""
    relation_type: str | None = Field(
        default=None,
        pattern="^(cites|supplements|replaces|belongs_to|related_to|conflicts_with)$",
    )
    description: str | None = None
    evidence_text: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: str | None = Field(
        default=None, pattern="^(ai_generated|human_confirmed|human_deleted|human_added)$",
    )
    metadata: dict | None = None


class GraphEdgeResponse(BaseModel):
    """图谱边 API 响应。"""
    id: UUID
    source_node_id: UUID
    target_node_id: UUID
    relation_type: str
    description: str | None = None
    evidence_text: str | None = None
    confidence: float | None = None
    status: str
    metadata: dict | None = Field(default=None, validation_alias="metadata_")
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════
# 完整图
# ═══════════════════════════════════════════════════════════════

class FullGraphResponse(BaseModel):
    """完整图数据 — 供前端 React Flow 渲染。"""
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]
    stats: dict = Field(
        default_factory=lambda: {
            "total_nodes": 0,
            "total_edges": 0,
            "by_type": {},
            "by_status": {},
        },
    )


# ═══════════════════════════════════════════════════════════════
# AI 生成
# ═══════════════════════════════════════════════════════════════

class GraphGenerateRequest(BaseModel):
    """AI 图生成请求。"""
    document_ids: list[UUID] | None = Field(
        default=None, description="指定文档 ID 列表，不传则全量生成",
    )
    force_rebuild: bool = Field(
        default=False, description="是否强制重建（清除已有 AI 生成数据）",
    )


class GraphGenerateStatus(BaseModel):
    """AI 图生成状态。"""
    task_id: str
    status: str  # pending / running / completed / failed
    progress: str | None = None  # "正在提取实体: 42/203"
    nodes_generated: int = 0
    edges_generated: int = 0
    errors: list[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# 搜索 & 展开
# ═══════════════════════════════════════════════════════════════

class GraphSearchRequest(BaseModel):
    """图搜索请求。"""
    query: str = Field(..., min_length=1, max_length=500, description="搜索关键词（实体名/法规名）")
    node_types: list[str] | None = Field(default=None, description="限定节点类型")
    limit: int = Field(default=20, ge=1, le=100)


class GraphExpandRequest(BaseModel):
    """图展开请求 — 从指定节点展开 N-hop 邻居。"""
    node_id: UUID = Field(..., description="起始节点 ID")
    hops: int = Field(default=1, ge=1, le=3, description="展开跳数")
    relation_types: list[str] | None = Field(default=None, description="限定关系类型")
    max_nodes: int = Field(default=50, ge=1, le=200)
