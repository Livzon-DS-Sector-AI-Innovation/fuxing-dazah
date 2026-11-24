"""QA COA 请求模型：产品 / 客户标准 / 标准项目 / 出具报告与结果值。

响应统一走 service 层 dict 序列化（APR 同款），此处只定义入参。

所有字符串入参统一清洗（NFKC + 去不可见字符 + 去首尾空白）：
- 必填字段清洗后为空 → 422（纯空格/零宽字符过不了 min_length 的口子）；
- 可空字段清洗后为空 → None（空串归一）。
raw_extract 是 docx 导入原始留底，不做清洗。
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal
from unicodedata import normalize as _nfkc

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# 不可见字符：软连字符、零宽类（ZWSP/ZWNJ/ZWJ/LRM/RLM）、双向控制符、
# 行/段分隔符、词连接符等 Format 字符、BOM——NFKC 不分解这些，须显式移除
_INVISIBLE_RE = re.compile(r"[\u00ad\u200b-\u200f\u202a-\u202f\u2060-\u206f\ufeff]")


def _clean_text(value: str) -> str:
    """NFKC（全角→半角等兼容归一）+ 去不可见字符 + 去首尾空白。"""
    return _INVISIBLE_RE.sub("", _nfkc("NFKC", value)).strip()


def _clean_required(value: str | None) -> str | None:
    """必填文本：None 直通（Update 语义=不改），清洗后为空报 422。"""
    if value is None:
        return None
    text = _clean_text(value)
    if not text:
        raise ValueError("不能为空白")
    return text


def _clean_optional(value: str | None) -> str | None:
    """可空文本：清洗后为空归一为 None。"""
    if value is None:
        return None
    return _clean_text(value) or None


def _clean_batch_data_dict(value: dict[str, str] | None) -> dict[str, str] | None:
    """批次字段值字典：键清洗后非空、值清洗后为空丢键（空值=未填）。"""
    if value is None:
        return None
    cleaned: dict[str, str] = {}
    for key, raw in value.items():
        key_clean = _clean_text(key)
        if not key_clean:
            raise ValueError("批次字段键不能为空白")
        text = _clean_text(raw)
        if text:
            cleaned[key_clean] = text
    return cleaned


class CoaProductCreate(BaseModel):
    """新增 COA 产品。短码统一转大写（批号/COA 编号前缀口径）。"""

    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=100)
    name_en: str | None = Field(default=None, max_length=200)
    is_active: bool = True
    sort_order: int = 0
    remark: str | None = Field(default=None, max_length=500)

    @field_validator("code", "name")
    @classmethod
    def _clean_req(cls, value: str | None) -> str | None:
        return _clean_required(value)

    @field_validator("name_en", "remark")
    @classmethod
    def _clean_opt(cls, value: str | None) -> str | None:
        return _clean_optional(value)


class CoaProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, min_length=1, max_length=32)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    name_en: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None
    sort_order: int | None = None
    remark: str | None = Field(default=None, max_length=500)

    @field_validator("code", "name")
    @classmethod
    def _clean_req(cls, value: str | None) -> str | None:
        return _clean_required(value)

    @field_validator("name_en", "remark")
    @classmethod
    def _clean_opt(cls, value: str | None) -> str | None:
        return _clean_optional(value)


class CoaProductFieldIn(BaseModel):
    """产品批次信息字段入参（全量替换语义，行序=sort_order）。"""

    key: str = Field(min_length=1, max_length=64)
    label_cn: str = Field(min_length=1, max_length=100)
    label_en: str | None = Field(default=None, max_length=200)
    field_type: Literal["text", "date"] = "text"
    sort_order: int | None = Field(default=None, description="缺省按载荷顺序自增")

    @field_validator("key", "label_cn")
    @classmethod
    def _clean_req(cls, value: str | None) -> str | None:
        return _clean_required(value)

    @field_validator("label_en")
    @classmethod
    def _clean_opt(cls, value: str | None) -> str | None:
        return _clean_optional(value)


class CoaProductFieldsReplace(BaseModel):
    """产品批次信息字段配置全量替换。"""

    fields: list[CoaProductFieldIn] = Field(max_length=100)


class CoaStandardFieldsReplace(BaseModel):
    """标准级批次信息字段覆盖全量替换（写覆盖=与产品默认解耦）。"""

    fields: list[CoaProductFieldIn] = Field(max_length=100)


class CoaItemIn(BaseModel):
    """标准项目入参：id 为空=新建；替换场景带 id=保留更新（值引用不断）。

    项目必然启用（无停用态）；default_value 仅 text 型可用（登记预填默认值）。
    """

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
    default_value: str | None = Field(
        default=None, max_length=200, description="text 型登记时的预填默认值"
    )
    remark: str | None = Field(default=None, max_length=500)

    @field_validator("name_cn")
    @classmethod
    def _clean_req(cls, value: str | None) -> str | None:
        return _clean_required(value)

    # id/code 清洗后为空 → None（=新建 / 缺省自动生成）
    @field_validator("id", "code")
    @classmethod
    def _clean_opt(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @field_validator("group_name", "name_en", "unit", "spec_text", "default_value", "remark")
    @classmethod
    def _clean_opt_fields(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @model_validator(mode="after")
    def _number_has_no_default(self) -> CoaItemIn:
        if self.value_type == "number" and self.default_value:
            raise ValueError("数值型项目不支持默认值（默认值仅文本型可用）")
        return self


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
    batch_fields: list[CoaProductFieldIn] | None = Field(
        default=None,
        max_length=100,
        description="docx 导入的批次字段草稿；None=沿用产品默认，"
        "与产品默认一致不落覆盖，空数组=显式空自定义集",
    )
    raw_extract: dict[str, Any] | None = Field(
        default=None, description="docx 导入草稿的原始提取结果（source=import 留底）"
    )

    @field_validator("product_id", "code", "name")
    @classmethod
    def _clean_req(cls, value: str | None) -> str | None:
        return _clean_required(value)

    @field_validator("customer", "market", "version", "remark")
    @classmethod
    def _clean_opt(cls, value: str | None) -> str | None:
        return _clean_optional(value)


class CoaStandardUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    customer: str | None = Field(default=None, max_length=200)
    market: str | None = Field(default=None, max_length=16)
    version: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None
    remark: str | None = Field(default=None, max_length=500)

    @field_validator("code", "name")
    @classmethod
    def _clean_req(cls, value: str | None) -> str | None:
        return _clean_required(value)

    @field_validator("customer", "market", "version", "remark")
    @classmethod
    def _clean_opt(cls, value: str | None) -> str | None:
        return _clean_optional(value)


class CoaStandardItemsReplace(BaseModel):
    """标准项目全量替换：不在载荷中的既有项目按引用守卫删除/停用。"""

    items: list[CoaItemIn] = Field(min_length=0, max_length=500)


class CoaValueIn(BaseModel):
    """结果值：value_num/value_text 至少一项（原文永远保留在 value_text）。"""

    item_id: str
    value_num: float | None = None
    value_text: str | None = Field(default=None, max_length=300)
    remark: str | None = Field(default=None, max_length=500)

    @field_validator("item_id")
    @classmethod
    def _clean_req(cls, value: str | None) -> str | None:
        return _clean_required(value)

    @field_validator("value_text", "remark")
    @classmethod
    def _clean_opt(cls, value: str | None) -> str | None:
        return _clean_optional(value)


class CoaReportCreate(BaseModel):
    """出具登记（手工/导入统一落库端点）。

    raw_extract 有值 → source=import。导入不修改标准配置：未命中项目
    不落库（扩项目走「客户标准配置」维护），values 只引用既有项目。
    无报告编号（业务键=产品+模板+批号）；batch_data 为模板动态批次字段值
    （key=生效字段集自定义键；固定列别名键由后端镜像写固定列），
    date 型字段值须为 ISO 日期文本。
    """

    product_id: str
    standard_id: str
    batch_no: str = Field(min_length=1, max_length=64)
    # 流水号与批号同为内置必填批次字段（品名由产品带出）
    serial_no: str = Field(min_length=1, max_length=32)
    mfg_date: date | None = None
    exp_date: date | None = None
    packaging: str | None = Field(default=None, max_length=100)
    batch_size: str | None = Field(default=None, max_length=50)
    storage: str | None = Field(default=None, max_length=300)
    remark: str | None = Field(default=None, max_length=500)
    batch_data: dict[str, str] | None = None
    values: list[CoaValueIn] = Field(default_factory=list, max_length=500)
    raw_extract: dict[str, Any] | None = None

    @field_validator("product_id", "standard_id", "batch_no", "serial_no")
    @classmethod
    def _clean_req(cls, value: str | None) -> str | None:
        return _clean_required(value)

    @field_validator("packaging", "batch_size", "storage", "remark")
    @classmethod
    def _clean_opt(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @field_validator("batch_data")
    @classmethod
    def _clean_batch_data(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return _clean_batch_data_dict(value)


class CoaReportUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_no: str | None = Field(default=None, min_length=1, max_length=64)
    serial_no: str | None = Field(default=None, min_length=1, max_length=32)
    mfg_date: date | None = None
    exp_date: date | None = None
    packaging: str | None = Field(default=None, max_length=100)
    batch_size: str | None = Field(default=None, max_length=50)
    storage: str | None = Field(default=None, max_length=300)
    remark: str | None = Field(default=None, max_length=500)
    batch_data: dict[str, str] | None = Field(
        default=None,
        description="None=不动；提供（含空字典）=按生效字段集全量替换",
    )
    values: list[CoaValueIn] | None = Field(
        default=None, description="提供即全量替换（空列表=清空所有值）；None=不动值"
    )

    @field_validator("batch_no", "serial_no")
    @classmethod
    def _clean_req(cls, value: str | None) -> str | None:
        return _clean_required(value)

    @field_validator("packaging", "batch_size", "storage", "remark")
    @classmethod
    def _clean_opt(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @field_validator("batch_data")
    @classmethod
    def _clean_batch_data(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return _clean_batch_data_dict(value)
