"""Safety API — S6 教育培训与行为管控（二期培训生产链）。

链1 年度培训需求（DESIGN 二期 §4.5）：
- POST /training-behavior/demand/generate：五源取数 → AI 草案（同步，
  AI 超时 120s 与服务配置一致；草案只落 PG，采纳后才写台账）
- GET  /training-behavior/demand/drafts：草案清单（安环科评审入口）
- POST /training-behavior/demand/drafts/{id}/adopt：采纳 → 写 Bitable 培训表
  计划行（状态=未开始）+ 回填 record_id
- POST /training-behavior/demand/drafts/{id}/reject：驳回

链2 课件/试卷生成（§5.6）：
- POST /training-behavior/material/generate：培训行 → 讲义要点卡/试卷 docx →
  挂「课件与试卷」附件列（幂等标记防重复生成，产物全落表可审不推送）
- GET  /training-behavior/material/{record_id}：该行已生成产物清单

链3 签到/成绩解析（§6.1）：
- POST /training-behavior/record/parse：取该行「签到表」附件首图 → vision
  解析 → confidence 分级回填（high 回填数字列；medium/low 仅备注；无法识
  别仅备注；人工改表=覆盖终值）
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.safety.ai_training_demand import TrainingDemandError
from app.modules.safety.ai_training_material import TrainingMaterialError
from app.modules.safety.ai_training_record_parsing import (
    TrainingRecordParsingError,
)
from app.modules.safety.service.training_behavior import (
    demand,
    material,
    record_parsing,
)
from app.shared.schemas import ApiResponse

logger = logging.getLogger(__name__)

training_behavior_router = APIRouter()


class DemandGenerateRequest(BaseModel):
    year: int = Field(..., ge=2020, le=2100, description="计划年度（五源统计年=year-1）")


@training_behavior_router.post(
    "/training-behavior/demand/generate",
    response_model=ApiResponse,
    summary="生成年度培训需求草案（五源取数→AI→PG 草案表）",
)
async def generate_demand(
    body: DemandGenerateRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    try:
        data = await demand.generate_demand_drafts(db, year=body.year)
    except TrainingDemandError as exc:
        raise HTTPException(status_code=502, detail=f"AI 生成失败: {exc}") from exc
    message = (
        f"生成完成：{data['count']} 条草案（替换旧草案 {data['replaced']} 条）"
    )
    if data["sources"]["disconnected"]:
        message += f"；{data['sources']['disconnected']} 个数据源未接入已降级"
    return ApiResponse(data=data, message=message)


@training_behavior_router.get(
    "/training-behavior/demand/drafts",
    response_model=ApiResponse,
    summary="培训需求草案清单（安环科评审）",
)
async def list_demand_drafts(
    year: int | None = Query(None, description="计划年度"),
    status: str | None = Query(
        None, description="状态筛选：draft/adopted/rejected"
    ),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    try:
        rows = await demand.list_drafts(db, year=year, status=status)
    except demand.DemandStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data={"items": rows, "total": len(rows)})


@training_behavior_router.post(
    "/training-behavior/demand/drafts/{draft_id}/adopt",
    response_model=ApiResponse,
    summary="采纳草案（写 Bitable 培训表计划行，状态=未开始）",
)
async def adopt_demand_draft(
    draft_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    try:
        data = await demand.adopt_draft(db, draft_id)
    except demand.DemandStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(
        data=data,
        message=f"已采纳并写入培训台账（行 {data['adopted_record_id']}）",
    )


@training_behavior_router.post(
    "/training-behavior/demand/drafts/{draft_id}/reject",
    response_model=ApiResponse,
    summary="驳回草案",
)
async def reject_demand_draft(
    draft_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    try:
        data = await demand.reject_draft(db, draft_id)
    except demand.DemandStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=data, message="已驳回")


class MaterialGenerateRequest(BaseModel):
    record_id: str = Field(..., min_length=1, description="培训行 record_id")
    material_type: str = Field(
        "lecture",
        description="生成类型：lecture=讲义 / exam=试卷 / both=两者",
    )
    config: dict | None = Field(
        None,
        description="试卷题型配置：choice_count/true_false_count/multi_choice_count"
                    "/fill_blank_count（fill_count 亦认；默认 5/5/0/0）",
    )


@training_behavior_router.post(
    "/training-behavior/material/generate",
    response_model=ApiResponse,
    summary="生成培训课件（讲义要点卡/试卷 docx，挂「课件与试卷」附件列）",
)
async def generate_material(
    body: MaterialGenerateRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    try:
        data = await material.generate_material(
            db,
            record_id=body.record_id,
            material_type=body.material_type,
            config=body.config,
        )
    except material.MaterialStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TrainingMaterialError as exc:
        raise HTTPException(status_code=502, detail=f"AI 生成失败: {exc}") from exc
    names = "、".join(m["file_name"] for m in data["materials"])
    return ApiResponse(data=data, message=f"已生成并挂附件：{names}")


@training_behavior_router.get(
    "/training-behavior/material/{record_id}",
    response_model=ApiResponse,
    summary="该培训行已生成产物清单（附件+时间+类型）",
)
async def get_materials(record_id: str) -> ApiResponse:
    try:
        data = await material.list_materials(record_id=record_id)
    except material.MaterialStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ApiResponse(data=data)


class RecordParseRequest(BaseModel):
    record_id: str = Field(..., min_length=1, description="培训行 record_id")


@training_behavior_router.post(
    "/training-behavior/record/parse",
    response_model=ApiResponse,
    summary="解析签到表/成绩单照片并按 confidence 分级回填",
)
async def parse_training_record(
    body: RecordParseRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse:
    try:
        data = await record_parsing.parse_training_record(
            record_id=body.record_id, db=db
        )
    except record_parsing.RecordParseStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TrainingRecordParsingError as exc:
        raise HTTPException(status_code=502, detail=f"vision 解析失败: {exc}") from exc
    parse = data["parse"]
    persisted = data.get("attendees_persisted")
    suffix = f"，参训人明细 {persisted} 行落库" if persisted else ""
    message = (
        f"解析完成：{parse['doc_type']}（confidence={parse['confidence']}），"
        f"回填列：{data['writeback_keys'] or '仅备注'}{suffix}"
    )
    return ApiResponse(data=data, message=message)
