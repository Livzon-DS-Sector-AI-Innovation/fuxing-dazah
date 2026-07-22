"""Safety knowledge article request and response schemas."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.modules.safety.schemas.enums import (
    KnowledgeCategory,
)


class SafetyKnowledgeArticleBase(BaseModel):
    """安全知识库文章基础模式"""

    article_no: str | None = Field(None, max_length=64, description="文档编号（可自动生成）")
    title: str = Field(..., max_length=255, description="文章标题")
    summary: str | None = Field(None, description="摘要")
    content: str | None = Field(None, description="正文内容")
    tags: str | None = Field(None, max_length=500, description="标签（逗号分隔）")
    source: str | None = Field(None, max_length=255, description="来源/出处")
    author: str | None = Field(None, max_length=255, description="作者/发布单位")
    publish_date: date | None = Field(None, description="发布日期")
    implementation_date: date | None = Field(None, description="法规实施日期")
    notes: str | None = Field(None, description="备注")
    category: KnowledgeCategory = Field(KnowledgeCategory.OTHER, description="分类")


class SafetyKnowledgeArticleCreate(SafetyKnowledgeArticleBase):
    """创建知识库文章"""

    pass


class SafetyKnowledgeArticleUpdate(BaseModel):
    """更新知识库文章"""

    article_no: str | None = Field(None, max_length=64, description="文档编号")
    title: str | None = Field(None, max_length=255, description="文章标题")
    summary: str | None = Field(None, description="摘要")
    content: str | None = Field(None, description="正文内容")
    tags: str | None = Field(None, max_length=500, description="标签（逗号分隔）")
    source: str | None = Field(None, max_length=255, description="来源/出处")
    author: str | None = Field(None, max_length=255, description="作者/发布单位")
    publish_date: date | None = Field(None, description="发布日期")
    implementation_date: date | None = Field(None, description="法规实施日期")
    notes: str | None = Field(None, description="备注")
    category: KnowledgeCategory | None = Field(None, description="分类")
    status: str | None = Field(None, max_length=32, description="状态")
    superseded_by_id: uuid.UUID | None = Field(None, description="替代关系")
    knowledge_card: dict | None = Field(None, description="AI 知识卡片 JSON（6 维度结构化内容）")
    card_version: int | None = Field(None, description="知识卡片版本号")


class SafetyKnowledgeArticleResponse(SafetyKnowledgeArticleBase):
    """安全知识库文章响应"""

    id: uuid.UUID
    feishu_record_id: str | None = None
    version: int = 1
    superseded_by_id: uuid.UUID | None = None
    superseded_by_title: str | None = None
    status: str
    view_count: int = 0
    attachment_path: str | None = None
    attachment_original_name: str | None = None
    created_by: uuid.UUID | None = None
    updated_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    knowledge_card: dict | None = None
    card_version: int = 1

    class Config:
        from_attributes = True


# ── 知识卡片内容（6 维度） ──


class KnowledgeCardContent(BaseModel):
    """知识卡片 6 维度结构化内容"""

    hazard_type_definitions: str | None = Field(None, description="隐患分类定义（人/物/环/管）")
    hazard_category_criteria: str | None = Field(None, description="隐患类别判定标准")
    hazard_level_criteria: str | None = Field(None, description="隐患级别分级标准")
    key_defect_examples: str | None = Field(None, description="典型缺陷示例")
    rectification_requirements: str | None = Field(None, description="整改措施要求")
    legal_basis_clauses: str | None = Field(None, description="可引用的法律依据条文")


class GenerateCardResponse(BaseModel):
    """AI 生成知识卡片响应"""

    knowledge_card: KnowledgeCardContent
    card_version: int
    message: str = "知识卡片生成成功"


class AgentUsageStatsResponse(BaseModel):
    """Agent 知识注入使用统计"""

    article_id: uuid.UUID
    article_title: str
    total_injections_30d: int = Field(0, description="近30天注入总次数")
    by_agent: dict = Field(default_factory=dict, description="按 Agent 分类的注入次数")
    last_injected_at: str | None = Field(None, description="最近一次注入时间")


class BatchGenerateCardsRequest(BaseModel):
    """批量生成知识卡片请求"""

    article_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=50, description="文档 ID 列表")


class BatchGenerateCardsResponse(BaseModel):
    """批量生成知识卡片响应"""

    success_count: int = 0
    failed_count: int = 0
    results: list[dict] = Field(default_factory=list, description="各文档生成结果 {id, success, message}")


# ── AI PPT 生成 ──


class GeneratePptRequest(BaseModel):
    """PPT 生成请求"""

    template: str = Field("training", description="PPT 模板类型: training / briefing / audit")
    style: str = Field("professional", description="配色风格: professional / modern / minimal")


class GeneratePptResponse(BaseModel):
    """PPT 生成响应"""

    download_url: str = Field(..., description="PPT 文件下载 URL")
    file_name: str = Field(..., description="文件名")
    page_count: int = Field(0, description="PPT 页数")
    message: str = "PPT 生成成功"


class PptGenerationRecord(BaseModel):
    """PPT 生成历史记录"""

    id: str
    file_name: str
    template: str
    style: str
    page_count: int
    download_url: str
    created_at: str


class PptHistoryResponse(BaseModel):
    """PPT 生成历史列表"""

    records: list[PptGenerationRecord] = Field(default_factory=list)


# ── AI 摘要生成 ──


class GenerateSummaryResponse(BaseModel):
    """AI 摘要生成响应"""

    summary: str = Field(..., description="AI 生成的结构化摘要")
    message: str = "摘要生成成功"


# ── AI 智能解析 ──

class SafetyKnowledgeArticleParseResponse(BaseModel):
    """AI 解析文档元数据响应"""

    title: str = Field(..., description="文档标题")
    category: KnowledgeCategory = Field(..., description="知识分类")
    summary: str = Field(..., description="摘要（≤200字）")
    tags: str = Field("", description="标签（逗号分隔）")
    source: str = Field("", description="来源/出处")
    author: str = Field("", description="作者/发布单位")
    publish_date: str | None = Field(None, description="发布日期 (YYYY-MM-DD)")
    content_preview: str = Field("", description="正文内容预览（前500字）")
    full_content: str = Field("", description="文档全文内容")


# ── 重复检测 ──

class DuplicateCheckRequest(BaseModel):
    """重复检测请求"""

    title: str = Field(..., description="待检测的文档标题")
    content: str | None = Field(None, description="待检测的文档正文（可选）")


class DuplicateArticleItem(BaseModel):
    """相似文档条目"""

    id: uuid.UUID
    article_no: str | None = None
    title: str
    category: str
    similarity_reason: str | None = None  # 相似原因简述


class DuplicateCheckResponse(BaseModel):
    """重复检测响应"""

    has_duplicates: bool = False
    duplicates: list[DuplicateArticleItem] = []


# ── 版本管理 ──

class VersionChainItem(BaseModel):
    """版本链条目"""

    id: uuid.UUID
    article_no: str | None = None
    title: str
    version: int
    status: str
    is_current: bool = False  # 是否为当前最新版本
    created_at: datetime


class NewVersionResponse(BaseModel):
    """新建版本响应"""

    new_article: SafetyKnowledgeArticleResponse
    version_chain: list[VersionChainItem]


# ── 语义搜索 ──

class SemanticSearchResult(BaseModel):
    """语义搜索结果"""

    id: uuid.UUID
    article_no: str | None = None
    title: str
    category: str
    summary: str | None = None
    tags: str | None = None
    status: str
    match_reason: str | None = None  # AI 给出的匹配理由


# ── Bitable 同步 ──


class KnowledgeSyncResponse(BaseModel):
    """Bitable 同步结果"""

    created: int = 0
    updated: int = 0
    deleted: int = 0
    total_bitable: int = 0
    total_platform: int = 0
