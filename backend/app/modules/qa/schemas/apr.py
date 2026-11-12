"""QA 年度产品审核（PQR）请求模型。

响应用惯例由 service 构造 dict 返回（同偏差管理），这里只声明请求体。
"""

from __future__ import annotations

import uuid
from typing import Any, Literal
from unicodedata import normalize as _nfkc

from pydantic import BaseModel, Field, field_validator, model_validator

from app.modules.qa.models import (
    AprDataKind,
    AprItemCategory,
    AprNdPolicy,
    AprValueType,
)


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _normalize_quick_values(values: list[str] | None) -> list[str] | None:
    """快捷值统一做 NFKC（全角 ＜０.５ → <0.5），去空白、去重，最多 4 个。"""
    if values is None:
        return None
    result: list[str] = []
    for raw in values:
        text = _nfkc("NFKC", raw).strip()
        if not text:
            continue
        if len(text) > 50:
            raise ValueError("快捷值不能超过 50 个字符")
        if text not in result:
            result.append(text)
    if len(result) > 4:
        raise ValueError("快捷值最多 4 个")
    return result


# ───────────────────────── 产品 ─────────────────────────


class AprProductCreate(BaseModel):
    """新增 PQR 产品。

    短码统一转大写（批号前缀与导出识别口径），短码与名称均要求唯一。
    """

    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=100)
    name_en: str | None = Field(default=None, max_length=100)
    is_active: bool = True
    sort_order: int = 0
    remark: str | None = Field(default=None, max_length=500)

    @field_validator("code")
    @classmethod
    def _upper_code(cls, value: str) -> str:
        text = value.strip().upper()
        if not text:
            raise ValueError("不能为空")
        return text

    @field_validator("name")
    @classmethod
    def _trim_name(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("不能为空")
        return text

    @field_validator("name_en", "remark")
    @classmethod
    def _trim_optional(cls, value: str | None) -> str | None:
        return _strip_optional(value)


class AprProductUpdate(BaseModel):
    """编辑 PQR 产品；未传字段不改。"""

    code: str | None = Field(default=None, min_length=1, max_length=32)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    name_en: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None
    sort_order: int | None = None
    remark: str | None = Field(default=None, max_length=500)

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_null(cls, data: Any) -> Any:
        """短码/名称是必填列，「不改」用不传表示，显式传 null 直接 422。"""
        if isinstance(data, dict):
            for field in ("code", "name"):
                if field in data and data[field] is None:
                    raise ValueError(f"{field} 不能为 null")
        return data

    @field_validator("code")
    @classmethod
    def _upper_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip().upper()
        if not text:
            raise ValueError("不能为空")
        return text

    @field_validator("name")
    @classmethod
    def _trim_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("不能为空")
        return text

    @field_validator("name_en", "remark")
    @classmethod
    def _trim_optional(cls, value: str | None) -> str | None:
        return _strip_optional(value)


# ───────────────────────── 段 ─────────────────────────


class AprSectionCreate(BaseModel):
    """新增模板段（对应 sheet 或横向块）。"""

    product_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    data_kind: AprDataKind = AprDataKind.PRODUCTION
    market: str | None = Field(default=None, max_length=16)
    stage: str | None = Field(default=None, max_length=32)
    multi_row: bool = False
    sort_order: int = 0
    remark: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def _trim_name(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("段名不能为空")
        return text

    @field_validator("market", "stage", "remark")
    @classmethod
    def _trim_optional(cls, value: str | None) -> str | None:
        return _strip_optional(value)


class AprSectionUpdate(BaseModel):
    """编辑模板段；未传字段不改。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    data_kind: AprDataKind | None = None
    market: str | None = Field(default=None, max_length=16)
    stage: str | None = Field(default=None, max_length=32)
    multi_row: bool | None = None
    sort_order: int | None = None
    remark: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def _trim_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("段名不能为空")
        return text

    @field_validator("market", "stage", "remark")
    @classmethod
    def _trim_optional(cls, value: str | None) -> str | None:
        return _strip_optional(value)


# ───────────────────────── 列定义 ─────────────────────────


class AprItemBase(BaseModel):
    """列定义公共字段。code 未传自动生成；sort_order 未传自动追加到段尾。"""

    code: str | None = Field(default=None, max_length=64)
    group_name: str | None = Field(default=None, max_length=100)
    category: AprItemCategory = AprItemCategory.TEST
    name_cn: str = Field(min_length=1, max_length=200)
    name_en: str | None = Field(default=None, max_length=200)
    value_type: AprValueType = AprValueType.NUMBER
    unit: str | None = Field(default=None, max_length=32)
    spec_text: str | None = Field(default=None, max_length=200)
    spec_min: float | None = None
    spec_max: float | None = None
    oot_min: float | None = None
    oot_max: float | None = None
    nd_policy: AprNdPolicy = AprNdPolicy.ZERO
    quick_values: list[str] = Field(default_factory=lambda: ["未检出", "<1"])
    stat_precision: int | None = Field(default=None, ge=0, le=6)
    trend_enabled: bool = True
    required: bool = False
    sort_order: int | None = None
    remark: str | None = Field(default=None, max_length=500)

    @field_validator("name_cn")
    @classmethod
    def _trim_name(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("名称不能为空")
        return text

    @field_validator("code", "group_name", "name_en", "unit", "spec_text", "remark")
    @classmethod
    def _trim_optional(cls, value: str | None) -> str | None:
        return _strip_optional(value)

    @field_validator("quick_values")
    @classmethod
    def _check_quick_values(cls, value: list[str]) -> list[str]:
        return _normalize_quick_values(value) or []

    @model_validator(mode="after")
    def _check_limit_pairs(self) -> AprItemBase:
        # 下限不得大于上限（DB CheckConstraint 同口径，提前到 422；
        # PATCH 单边修改的合并校验在 service.update_item 兜底）。
        if self.spec_min is not None and self.spec_max is not None:
            if self.spec_min > self.spec_max:
                raise ValueError("spec_min 不能大于 spec_max")
        if self.oot_min is not None and self.oot_max is not None:
            if self.oot_min > self.oot_max:
                raise ValueError("oot_min 不能大于 oot_max")
        return self


class AprItemCreate(AprItemBase):
    """新增列定义。"""

    section_id: uuid.UUID


class AprItemDraft(AprItemBase):
    """批量建列的单项；所属段由路径参数给定。"""


class AprItemsBulkCreate(BaseModel):
    """批量建列（从 Excel 粘贴）。按数组顺序依次落到段尾。"""

    items: list[AprItemDraft] = Field(min_length=1, max_length=300)


class AprSectionCopyIn(BaseModel):
    """复制模板段到目标产品：单请求原子完成（建段+建列，替代前端两步写）。

    只复制启用的列定义（停用列跳过），计数在响应里透明报告。
    """

    product_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def _trim_name(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("段名不能为空")
        return text


class AprItemsOrderIn(BaseModel):
    """整段列重排：必须按目标顺序携带该段全部未删除列的 id（含停用列），
    后端单事务重赋 sort_order，替代逐列 PATCH。"""

    item_ids: list[uuid.UUID] = Field(min_length=1, max_length=300)


class AprItemUpdate(BaseModel):
    """编辑列定义；未传字段不改。code 建议不再修改（导出列匹配依赖）。"""

    code: str | None = Field(default=None, max_length=64)
    group_name: str | None = Field(default=None, max_length=100)
    category: AprItemCategory | None = None
    name_cn: str | None = Field(default=None, min_length=1, max_length=200)
    name_en: str | None = Field(default=None, max_length=200)
    value_type: AprValueType | None = None
    unit: str | None = Field(default=None, max_length=32)
    spec_text: str | None = Field(default=None, max_length=200)
    spec_min: float | None = None
    spec_max: float | None = None
    oot_min: float | None = None
    oot_max: float | None = None
    nd_policy: AprNdPolicy | None = None
    quick_values: list[str] | None = None
    stat_precision: int | None = Field(default=None, ge=0, le=6)
    trend_enabled: bool | None = None
    required: bool | None = None
    is_active: bool | None = None
    sort_order: int | None = None
    remark: str | None = Field(default=None, max_length=500)

    @field_validator("name_cn")
    @classmethod
    def _trim_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("名称不能为空")
        return text

    @field_validator("code", "group_name", "name_en", "unit", "spec_text", "remark")
    @classmethod
    def _trim_optional(cls, value: str | None) -> str | None:
        return _strip_optional(value)

    @field_validator("quick_values")
    @classmethod
    def _check_quick_values(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_quick_values(value)

    @model_validator(mode="after")
    def _check_limit_pairs(self) -> AprItemUpdate:
        # PATCH 未传的一侧是 None、无法与现值比较：这里只拦「同一请求里
        # 自相矛盾」的对；单边修改由 service.update_item 合并现值兜底。
        if self.spec_min is not None and self.spec_max is not None:
            if self.spec_min > self.spec_max:
                raise ValueError("spec_min 不能大于 spec_max")
        if self.oot_min is not None and self.oot_max is not None:
            if self.oot_min > self.oot_max:
                raise ValueError("oot_min 不能大于 oot_max")
        return self


# ───────────────────────── 批次与值 ─────────────────────────


class AprBatchCreate(BaseModel):
    """批次登记（段内唯一：同段同年同批号）。"""

    section_id: uuid.UUID
    year: int = Field(ge=2000, le=2100)
    batch_no: str = Field(min_length=1, max_length=64)
    seq: int | None = Field(default=None, ge=1)
    parent_batch_id: uuid.UUID | None = None
    remark: str | None = Field(default=None, max_length=500)

    @field_validator("batch_no")
    @classmethod
    def _trim_batch_no(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("批号不能为空")
        return text

    @field_validator("remark")
    @classmethod
    def _trim_optional(cls, value: str | None) -> str | None:
        return _strip_optional(value)


class AprBatchUpdate(BaseModel):
    """编辑批次；未传字段不改。"""

    year: int | None = Field(default=None, ge=2000, le=2100)
    batch_no: str | None = Field(default=None, min_length=1, max_length=64)
    seq: int | None = Field(default=None, ge=1)
    parent_batch_id: uuid.UUID | None = None
    remark: str | None = Field(default=None, max_length=500)

    @field_validator("batch_no")
    @classmethod
    def _trim_batch_no(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("批号不能为空")
        return text

    @field_validator("remark")
    @classmethod
    def _trim_optional(cls, value: str | None) -> str | None:
        return _strip_optional(value)


class AprValueIn(BaseModel):
    """单个值：item 归属批次所在段；number 项填 value_num，未检出等文字结果
    可只填 value_text（统计口径由列定义 nd_policy 决定）；text 项填 value_text。"""

    item_id: uuid.UUID
    row_seq: int = Field(default=1, ge=1, le=999)
    row_label: str | None = Field(default=None, max_length=32)
    value_num: float | None = None
    value_text: str | None = Field(default=None, max_length=300)
    remark: str | None = Field(default=None, max_length=500)

    @field_validator("row_label", "value_text", "remark")
    @classmethod
    def _trim_optional(cls, value: str | None) -> str | None:
        return _strip_optional(value)


class AprBatchValuesIn(BaseModel):
    """整批一屏批量保存：全量替换该批次现有值（硬删+插入）。"""

    values: list[AprValueIn] = Field(min_length=0, max_length=2000)


AprImportMode = Literal["merge", "replace"]


class AprImportCellError(BaseModel):
    """Excel 导入错误定位：row=工作簿行号，0 表示文件级（打不开/无表头等）。"""

    row: int = Field(ge=0)
    column: str | None = None
    message: str


class AprImportResult(BaseModel):
    """Excel 导入结果：全部校验通过才写入（ok=false 时零落库）。"""

    ok: bool
    mode: AprImportMode
    batches: int = Field(default=0, ge=0)
    cells: int = Field(default=0, ge=0)
    registered: int = Field(
        default=0, ge=0, description="文件中未登记、本次自动创建的批次数"
    )
    errors: list[AprImportCellError] = Field(default_factory=list, max_length=100)
    total_errors: int = Field(default=0, ge=0)


TrendPointStatus = Literal["normal", "oot", "oos"]
