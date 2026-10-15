"""法规收录契约 v1 模型（双仓冻结，不得单端增改——升版须双仓同步）。

契约① ragplus→dazah 候选推送；② dazah→ragplus 生命周期回执；
③ dazah→ragplus 爬虫状态查询。字段口径唯一事实源：
docs/DESIGN-法规采集迁移ragplus-x与监控中心接入-功能改进计划-20261015.md §2.3。
"""

from __future__ import annotations

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
