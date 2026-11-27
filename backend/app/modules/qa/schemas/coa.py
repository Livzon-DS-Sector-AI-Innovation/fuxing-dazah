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


# 日期格式只放行「年月日」类指令：strftime 对未知指令在多数平台上不报错
# （%Q 原样输出），靠它校验拦不住非法格式
_DATE_DIRECTIVE_RE = re.compile(r"%(.)", re.S)
_ALLOWED_DATE_DIRECTIVES = frozenset({"Y", "y", "m", "d", "b", "B", "e"})


def check_date_pattern(pattern: str) -> str:
    pattern = pattern.strip()
    if not pattern or len(pattern) > 40:
        raise ValueError("日期格式不能为空且不超过 40 个字符")
    bad = [m.group(0) for m in _DATE_DIRECTIVE_RE.finditer(pattern) if m.group(1) not in _ALLOWED_DATE_DIRECTIVES]
    if bad:
        raise ValueError(f"日期格式只支持年月日（%Y %m %d），不支持 {' '.join(bad)}")
    return pattern


class CoaTemplateFmtIn(BaseModel):
    """数据位的格式规则：数值（小数位 + 单位后缀）/ 日期（strftime）/ 文字。

    suffix/pattern 只做去首尾空白、不做 NFKC——全角兼容归一会把 µg/mg 的 µ
    改写成希腊字母 μ，单位必须保持模板里的原字符。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["number", "date", "text"]
    decimals: int | None = Field(default=None, ge=0, le=6)
    suffix: str | None = Field(default=None, max_length=32)
    pattern: str | None = Field(default=None, max_length=40)
    bilingual: bool | None = None
    joiner: Literal["", " ", "\n"] | None = None

    @field_validator("suffix", "pattern")
    @classmethod
    def _plain(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def _date_pattern_must_be_valid(self) -> CoaTemplateFmtIn:
        if self.kind == "date":
            if not self.pattern:
                raise ValueError("日期格式不能为空")
            check_date_pattern(self.pattern)
        return self


class CoaTemplateSlotIn(BaseModel):
    """一个数据位的绑定：地址 + 回填时被替换的原文 + 格式规则。"""

    model_config = ConfigDict(extra="forbid")

    sid: str = Field(min_length=1, max_length=64)
    sample: str | None = Field(
        default=None,
        max_length=300,
        description="值夹在固定文字中间时必须给出：要被替换的那段原文；"
        "整格是值/空格时不传，服务端按格子推导",
    )
    fmt: CoaTemplateFmtIn

    @field_validator("sid")
    @classmethod
    def _clean_req(cls, value: str | None) -> str | None:
        return _clean_required(value)

    @field_validator("sample")
    @classmethod
    def _plain_optional(cls, value: str | None) -> str | None:
        # None=由服务端推导；空串=该位置当前为空。两者语义不同，不能归一
        return value if value is None else value.strip()


class CoaTemplateFieldIn(BaseModel):
    """一个字段的绑定：至少一个数据位；required=回填时该字段必须有值。"""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=80)
    required: bool = True
    slots: list[CoaTemplateSlotIn] = Field(min_length=1, max_length=20)

    @field_validator("field")
    @classmethod
    def _clean_req(cls, value: str | None) -> str | None:
        return _clean_required(value)


class CoaTemplateBindingIn(BaseModel):
    """人工确认后的模板标注（服务端会对模板重新校验一遍）。

    static_slots：结果列里确认「保持模板原文」的格子——填过值的模板上，
    结果列里没绑定又非空的格子必须逐个确认，否则不许保存。
    """

    model_config = ConfigDict(extra="forbid")

    fields: list[CoaTemplateFieldIn] = Field(max_length=600)
    static_slots: list[str] = Field(default_factory=list, max_length=200)
    verdicts: dict[str, str] = Field(
        default_factory=dict, description="判定词中→英对照（样例里学到的，可增改）"
    )

    @field_validator("static_slots")
    @classmethod
    def _clean_sids(cls, value: list[str]) -> list[str]:
        return [sid.strip() for sid in value if sid.strip()]

    @field_validator("verdicts")
    @classmethod
    def _clean_verdicts(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for cn, en in value.items():
            cn, en = cn.strip(), en.strip()
            if cn and en and len(cn) <= 100 and len(en) <= 200:
                cleaned[cn] = en
        return cleaned


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
