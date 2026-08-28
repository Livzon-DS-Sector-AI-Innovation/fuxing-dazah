"""Excel 台账导入结果 schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LedgerImportError(BaseModel):
    """单条导入错误详情。"""
    sheet: str = Field(..., description="Sheet 名称")
    row: int | None = Field(default=None, description="Excel 行号（1-based）")
    type: str = Field(default="error", description="error / warning")
    message: str = Field(..., description="错误描述")
    missing_fields: list[str] = Field(default_factory=list, description="缺少的字段名列表")





class LedgerImportSheetDetail(BaseModel):
    """单个 sheet 的导入结果。"""
    sheet_name: str = Field(..., description="Sheet 名称")
    department: str | None = Field(default=None, description="从 sheet 中提取的部门名")
    rows: int = Field(default=0, description="本 sheet 导入的数据行数")





class LedgerImportResult(BaseModel):
    """台账导入结果汇总。"""
    deleted_count: int = Field(default=0, description="软删除的旧记录数（文件未出现）")
    imported_count: int = Field(default=0, description="新插入的记录数")
    updated_count: int = Field(default=0, description="更新的已有记录数")
    sheet_count: int = Field(default=0, description="处理的 sheet 数")
    sheet_details: list[LedgerImportSheetDetail] = Field(default_factory=list)
    warnings: list[LedgerImportError] = Field(default_factory=list, description="字段缺失提醒")


# ═══════════════════════════════════════════
# 日期聚合统计
# ═══════════════════════════════════════════
