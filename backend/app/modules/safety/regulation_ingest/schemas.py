"""法规收录契约 v1 模型（双仓冻结，不得单端增改——升版须双仓同步）。

契约① ragplus→dazah 候选推送；② dazah→ragplus 生命周期回执；
③ dazah→ragplus 爬虫状态查询。字段口径唯一事实源：
docs/DESIGN-法规采集迁移ragplus-x与监控中心接入-功能改进计划-20261015.md §2.3。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ═══════════════════════════════════════════════════════════════
# 契约①：候选推送（ragplus → dazah）
# ═══════════════════════════════════════════════════════════════


class CandidateMetadata(BaseModel):
    """候选元数据（ragplus 侧 LLM+schema 提取产物）。"""

    doc_no: str | None = Field(default=None, description="文号")
    issued_at: str | None = Field(default=None, description="发布日期 (YYYY-MM-DD)")
    puborg: str | None = Field(default=None, description="发布机关")
    effective_at: str | None = Field(default=None, description="实施日期 (YYYY-MM-DD)")


class CandidateAttachment(BaseModel):
    """候选原文附件（ragplus 侧已暂存的 PDF 等）。"""

    file_id: str | None = Field(default=None, description="ragplus 侧附件 id")
    filename: str | None = Field(default=None, description="附件文件名")


class IngestCandidateItem(BaseModel):
    """单条候选法规。"""

    candidate_id: str = Field(..., description="ragplus 候选 id（回执寻址用）")
    source: str = Field(..., description="来源标识（10 政务源之一）")
    url: str = Field(..., description="原文 URL")
    title: str = Field(..., description="法规标题")
    metadata: CandidateMetadata = Field(default_factory=CandidateMetadata, description="元数据")
    attachment: CandidateAttachment = Field(default_factory=CandidateAttachment, description="附件")
    content_digest: str | None = Field(default=None, description="正文摘要（供 AI 判定）")
    old_version_hint: str | None = Field(
        default=None, description="旧版法规标题提示（修订/替代场景）",
    )
    discovered_at: str | None = Field(default=None, description="发现时间 (ISO 8601)")


class IngestCandidatesRequest(BaseModel):
    """契约①请求体：一个爬取 run 的候选批次。"""

    run_id: str = Field(..., description="ragplus 侧爬取 run_id（幂等锚点）")
    items: list[IngestCandidateItem] = Field(default_factory=list, description="候选列表")


class IngestItemResult(BaseModel):
    """单条候选处置结果（契约①响应项）。"""

    candidate_id: str
    action_taken: str = Field(
        description="promote | reject | duplicate | pending | error",
    )
    reason: str = Field(default="", description="处置原因")
    bitable_record_id: str | None = Field(default=None, description="写入台账的 record_id")


class IngestCandidatesResponse(BaseModel):
    """契约①响应体：同步处理完后逐条返回（质询拍板口径）。"""

    accepted: bool = Field(description="批次是否被处理（总闸关=False）")
    run_log_id: str | None = Field(default=None, description="本仓留痕行 id")
    reason: str | None = Field(default=None, description="未受理原因（accepted=False 时）")
    results: list[IngestItemResult] = Field(default_factory=list, description="逐条处置结果")


# ═══════════════════════════════════════════════════════════════
# 契约②：生命周期回执（dazah → ragplus）
# ═══════════════════════════════════════════════════════════════

LIFECYCLE_PROMOTE = "promote"
LIFECYCLE_REJECT = "reject"
LIFECYCLE_ARCHIVE_SUPERSEDED = "archive_superseded"


class LifecycleReceiptRequest(BaseModel):
    """契约②请求体：候选生命周期指令。"""

    action: str = Field(description="promote | reject | archive_superseded")
    reason: str = Field(default="", description="处置原因")
    replace_candidate_id: str | None = Field(
        default=None, description="修订场景：被替代的旧候选 id",
    )


# ═══════════════════════════════════════════════════════════════
# 收录执行链模型（自 regulation_crawler/schemas.py 迁入，退役保留段）
# ═══════════════════════════════════════════════════════════════

class CrawledRegulation(BaseModel):
    """单条爬取的法规（写入 Bitable 前的中间态）。"""

    # ── 基础字段（V1.0） ──
    title: str = Field(..., description="法规名称")
    document_number: str | None = Field(default=None, description="文号")
    publish_date: str | None = Field(default=None, description="发布日期 (YYYY-MM-DD)")
    implementation_date: str | None = Field(default=None, description="实施日期 (YYYY-MM-DD)")
    issuing_authority: str | None = Field(default=None, description="发布机关")
    regulation_level: str | None = Field(default=None, description="法规层级")
    status: str | None = Field(default=None, description="时效状态")
    source_url: str = Field(..., description="来源 URL")
    source_type: str = Field(..., description="来源类型标识")
    raw_text: str | None = Field(default=None, description="原始文本（供 AI 摘要生成）")

    # ── V1.1 新增：AI 智能分析字段 ──
    content_type: str | None = Field(
        default=None, description="内容类型：regulation | news | speech | other"
    )
    impact_level: str | None = Field(
        default=None, description="影响等级：高 | 中 | 低"
    )
    business_domains: list[str] | None = Field(
        default=None, description="匹配的业务领域：安全生产/职业健康/环保/消防/危化品/特种设备"
    )
    relevance_score: float | None = Field(
        default=None, description="相关性评分 0.0-1.0"
    )
    action_recommendations: str | None = Field(
        default=None, description="应对建议（制度/设备/培训层面 + 时间节点）"
    )
    core_summary: str | None = Field(
        default=None, description="核心内容摘要（≤300字）"
    )
    related_old_title: str | None = Field(
        default=None, description="关联的旧版法规名称（修订/替代关系）"
    )
    comparison_summary: str | None = Field(
        default=None, description="新旧对比摘要"
    )

    # ── V1.2 新增：法规原件下载 ──
    attachment_url: str | None = Field(
        default=None, description="附件直接下载链接（PDF/DOCX）"
    )
    attachment_name: str | None = Field(
        default=None, description="附件原始文件名"
    )
    attachment_path: str | None = Field(
        default=None, description="附件本地存储路径"
    )
    attachment_file_token: str | None = Field(
        default=None, description="上传后 Feishu Drive file_token"
    )
    extra_attachments: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "额外附件（多附件法规，如公告的附件1/附件2）。"
            "每项: {url, name, path, file_token}，主附件为 attachment_* 字段。"
        ),
    )
    attachment_pending_reason: str | None = Field(
        default=None,
        description=(
            "原文待补原因：详情页无法提供真实原文（标准发布公告 / JS 壳信息页）时标记，"
            "会写入 Bitable 备注，避免把信息页/公告页渲染件误当法规原件。"
        ),
    )

    # ── V1.3 新增：更新状态 ──
    update_status: str | None = Field(
        default=None, description="更新状态：新增 | 已更新 | 已废止"
    )


class CrawlItemResult(BaseModel):
    """单条爬取结果项。"""

    title: str
    impact_level: str | None = None
    bitable_record_id: str | None = None
    bitable_shared_url: str | None = None
    status: str  # "created" | "duplicate" | "deleted" | "filtered" | "error"
    action: str | None = None  # "created" | "updated" — 区分新增 vs 修订替代
    core_summary: str | None = None  # 新增法规的 AI 核心摘要
    comparison_summary: str | None = None  # 修订法规的新旧对比摘要
    error: str | None = None


class CrawlResultSummary(BaseModel):
    """一次抓取的汇总结果。"""

    crawled_count: int = 0
    new_count: int = 0
    deleted_count: int = 0
    filtered_count: int = 0
    skipped_duplicate: int = 0
    attachment_failed_count: int = 0
    errors: list[str] = Field(default_factory=list)
    items: list[CrawlItemResult] = Field(default_factory=list)
