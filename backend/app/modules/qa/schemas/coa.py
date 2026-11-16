"""QA COA 请求模型：产品 / 客户标准 / 标准项目 / 出具报告与结果值。

响应统一走 service 层 dict 序列化（APR 同款），此处只定义入参。
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CoaProductCreate(BaseModel):
    """新增 COA 产品。短码统一转大写（批号/COA 编号前缀口径）。"""

    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=100)
    name_en: str | None = Field(default=None, max_length=200)
    is_active: bool = True
    sort_order: int = 0
    remark: str | None = Field(default=None, max_length=500)


class CoaProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, min_length=1, max_length=32)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    name_en: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None
    sort_order: int | None = None
    remark: str | None = Field(default=None, max_length=500)


class CoaItemIn(BaseModel):
    """标准项目入参：id 为空=新建；替换场景带 id=保留更新（值引用不断）。"""

    id: str | None = None
    code: str | None = Field(
        default=None, max_length=64, description="缺省由中英文名归一化生成"
    )
    group_name: str | None = Field(default=None, max_length=100)
    name_cn: str = Field(min_length=1, max_length=200)
    name_en: str | None = Field(default=None, max_length=200)
    value_type: Literal["number", "text"] = "text"
    unit: str | None = Field(default=None, max_length=32)
    spec_text: str | None = Field(default=None, max_length=200)
    spec_min: float | None = None
    spec_max: float | None = None
    sort_order: int | None = Field(default=None, description="缺省按载荷顺序自增")
    is_active: bool = True
    remark: str | None = Field(default=None, max_length=500)


class CoaStandardCreate(BaseModel):
    """新建客户标准（含首批项目）。source 恒 manual——docx 导入落库也走本端点，
    raw_extract 有值时后端标记 import。"""

    product_id: str
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    customer: str | None = Field(default=None, max_length=200)
    market: str | None = Field(default=None, max_length=16)
    version: str | None = Field(default=None, max_length=50)
    is_active: bool = True
    remark: str | None = Field(default=None, max_length=500)
    items: list[CoaItemIn] = Field(default_factory=list, max_length=500)
    raw_extract: dict[str, Any] | None = Field(
        default=None, description="docx 导入草稿的原始提取结果（source=import 留底）"
    )


class CoaStandardUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    customer: str | None = Field(default=None, max_length=200)
    market: str | None = Field(default=None, max_length=16)
    version: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None
    remark: str | None = Field(default=None, max_length=500)


class CoaStandardItemsReplace(BaseModel):
    """标准项目全量替换：不在载荷中的既有项目按引用守卫删除/停用。"""

    items: list[CoaItemIn] = Field(min_length=0, max_length=500)


class CoaValueIn(BaseModel):
    """结果值：value_num/value_text 至少一项（原文永远保留在 value_text）。"""

    item_id: str
    value_num: float | None = None
    value_text: str | None = Field(default=None, max_length=300)
    remark: str | None = Field(default=None, max_length=500)


class CoaNewItemIn(CoaItemIn):
    """导入确认时并入标准的新项目（携带首份结果值）。

    后端先建项目再建报告，值由后端按新建后的 item id 归并——
    前端无法预知 UUID，故值不进 values 载荷。
    """

    value_num: float | None = None
    value_text: str | None = Field(default=None, max_length=300)


class CoaReportCreate(BaseModel):
    """出具登记（手工/导入统一落库端点）。

    导入确认时可带 new_items（预览中勾选「并入标准」的未命中项目），
    后端事务内先建项目再建报告；raw_extract 有值 → source=import。
    """

    product_id: str
    standard_id: str
    report_no: str = Field(min_length=1, max_length=64)
    batch_no: str = Field(min_length=1, max_length=64)
    serial_no: str | None = Field(default=None, max_length=32)
    mfg_date: date | None = None
    exp_date: date | None = None
    issued_date: date | None = None
    packaging: str | None = Field(default=None, max_length=100)
    batch_size: str | None = Field(default=None, max_length=50)
    storage: str | None = Field(default=None, max_length=300)
    conclusion: str | None = Field(default=None, max_length=500)
    remark: str | None = Field(default=None, max_length=500)
    values: list[CoaValueIn] = Field(default_factory=list, max_length=500)
    new_items: list[CoaNewItemIn] = Field(default_factory=list, max_length=100)
    raw_extract: dict[str, Any] | None = None


class CoaReportUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_no: str | None = Field(default=None, min_length=1, max_length=64)
    batch_no: str | None = Field(default=None, min_length=1, max_length=64)
    serial_no: str | None = Field(default=None, max_length=32)
    mfg_date: date | None = None
    exp_date: date | None = None
    issued_date: date | None = None
    packaging: str | None = Field(default=None, max_length=100)
    batch_size: str | None = Field(default=None, max_length=50)
    storage: str | None = Field(default=None, max_length=300)
    conclusion: str | None = Field(default=None, max_length=500)
    remark: str | None = Field(default=None, max_length=500)
    values: list[CoaValueIn] | None = Field(
        default=None, description="非空列表=全量替换；None=不动值"
    )
