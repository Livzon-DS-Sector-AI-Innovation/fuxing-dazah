"""Info Query schemas — conversational RAG chat request/response."""

from __future__ import annotations

from pydantic import BaseModel, Field


class InfoQueryMessage(BaseModel):
    """A single message in the conversation history."""

    role: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., description="Message text")


class InfoQueryRequest(BaseModel):
    """Request body for the knowledge chat endpoint."""

    query: str = Field(..., min_length=1, max_length=2000, description="User's question")
    history: list[InfoQueryMessage] = Field(
        default_factory=list,
        max_length=20,
        description="Previous messages for conversational context",
    )


class InfoQuerySource(BaseModel):
    """A retrieved regulation chunk cited in the answer."""

    doc_title: str = Field(..., description="Document title")
    article_ref: str = Field("", description="Article or chapter reference")
    chunk_text: str = Field(..., description="Relevant excerpt from the regulation")
    doc_category: str = Field("", description="Document category")
    feishu_url: str = Field("", description="飞书多维表格原文链接，为空时前端不显示链接")


class InfoQueryResponse(BaseModel):
    """Response body for the knowledge chat endpoint."""

    answer: str = Field(..., description="AI-generated answer based on regulation chunks")
    sources: list[InfoQuerySource] = Field(
        default_factory=list,
        description="Source regulation chunks used to generate the answer",
    )
