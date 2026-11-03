"""QA 模块 HTTP API 入口：聚合各域子路由，路径与旧版单文件保持一致。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.modules.qa.api._deps import qa_read
from app.modules.qa.api.ai_analysis import router as ai_analysis_router
from app.modules.qa.api.deviations import router as deviations_router
from app.modules.qa.api.documents import router as documents_router
from app.modules.qa.api.files import router as files_router
from app.modules.qa.api.masters import router as masters_router
from app.modules.qa.api.references import router as references_router
from app.modules.qa.api.search import router as search_router
from app.platform.identity.models import User
from app.shared.module_registry import MODULES_BY_CODE

router = APIRouter()
_module = MODULES_BY_CODE["qa"]


@router.get("/", summary="QA 模块信息")
async def read_module(user: User = Depends(qa_read)) -> dict[str, str]:
    """返回模块元信息；需持有 QA 读取权限。"""
    return _module.as_dict()


# 主数据与引用选择器
router.include_router(masters_router)
router.include_router(references_router)
# 文件类型、台账、版本与关系
router.include_router(documents_router)
# AI 分析与提案
router.include_router(ai_analysis_router)
# 文件提取/产物/内容
router.include_router(files_router)
# 偏差管理（偏差 + CAPA）
router.include_router(deviations_router)
# 检索与审计
router.include_router(search_router)
