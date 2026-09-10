"""法规抓取系统 Pydantic 模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ═══════════════════════════════════════════════════════════════
# 请求模型
# ═══════════════════════════════════════════════════════════════


class ChangeDetectionWebhookRequest(BaseModel):
    """changedetection.io 变更通知 Webhook 载荷。"""

    watch_url: str = Field(..., description="被监控的 URL")
    watch_title: str = Field(default="", description="Watch 标签")
    current_snapshot: str = Field(default="", description="当前页面快照（HTML/文本）")
    diff: str = Field(default="", description="统一文本 diff")
    previous_md5: str = Field(default="", description="变更前内容 MD5")
    current_md5: str = Field(default="", description="变更后内容 MD5")
    viewed: str = Field(default="0", description="是否已查看")
    source_tag: str | None = Field(
        default=None, description="法规来源标签（通过 Jinja2 模板注入，如 'npc'、'gov_cn'）"
    )


class ManualCrawlRequest(BaseModel):
    """手动触发抓取请求。"""

    source_url: str | None = Field(default=None, description="指定抓取 URL（空=全部来源）")
    source_type: str | None = Field(
        default=None, description="来源类型筛选：npc / gov_cn / mem / nhc / nmpa / samr"
    )


# ═══════════════════════════════════════════════════════════════
# 爬取结果模型
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
    extra_attachments: list[dict] = Field(
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
