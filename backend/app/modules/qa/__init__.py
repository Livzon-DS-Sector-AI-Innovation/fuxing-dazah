"""QA 模块。

本模块与 ``quality``（质量检验）和 ``hr.qa_assessments``（培训考核）
保持独立，仅提供已批准质量文件及其主数据关系的持久化模型。
"""

# 与其他业务模块保持一致，允许全局路由装配或测试通过模块包导入 router。
# api.py 中的业务实现仍只通过本模块内部公开契约访问。
from app.modules.qa.api import router
from app.modules.qa.models import (
    Document,
    DocumentFile,
    DocumentMasterLink,
    DocumentTextSegment,
    DocumentType,
    DocumentVersion,
    ExtractionStatus,
    MasterObject,
    MasterObjectAlias,
    MasterObjectSource,
    MasterObjectType,
    RecordStatus,
    RelationType,
    TextSegment,
    VersionStatus,
)

__all__ = [
    "Document",
    "DocumentFile",
    "DocumentMasterLink",
    "DocumentTextSegment",
    "DocumentType",
    "DocumentVersion",
    "ExtractionStatus",
    "MasterObject",
    "MasterObjectAlias",
    "MasterObjectSource",
    "MasterObjectType",
    "RecordStatus",
    "RelationType",
    "TextSegment",
    "VersionStatus",
    "router",
]
