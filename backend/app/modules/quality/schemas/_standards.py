"""Quality 模块请求/响应 Schema。"""


from pydantic import BaseModel, Field

# ─── 产品标准配置 ───


class StandardDocumentCreate(BaseModel):
    """创建质量标准文档。"""

    file_no: str = Field(max_length=100)
    product_name: str = Field(max_length=200)
    product_code: str | None = Field(default=None, max_length=64)
    product_internal_code: str | None = Field(default=None, max_length=64)
    specification: str | None = Field(default=None, max_length=200)
    valid_years: str | None = Field(default=None, max_length=32)
    effective_date: str | None = Field(default=None, max_length=32)
    version: str | None = Field(default=None, max_length=32)
    template_path: str | None = Field(default=None, max_length=500, description="绑定的 COA 报告模板路径")


class StandardDocumentUpdate(BaseModel):
    """更新质量标准文档。"""

    file_no: str | None = Field(default=None, max_length=100)
    product_name: str | None = Field(default=None, max_length=200)
    product_code: str | None = Field(default=None, max_length=64)
    product_internal_code: str | None = Field(default=None, max_length=64)
    specification: str | None = Field(default=None, max_length=200)
    valid_years: str | None = Field(default=None, max_length=32)
    effective_date: str | None = Field(default=None, max_length=32)
    version: str | None = Field(default=None, max_length=32)
    template_path: str | None = Field(default=None, max_length=500, description="绑定的 COA 报告模板路径")


class StandardItemCreate(BaseModel):
    """创建标准项目行（SOP 号为匹配键；含纯文字标准，文字标准 operator/limit 为空、人工判定）。"""

    seq: int | None = None
    category: str | None = Field(default=None, max_length=100)
    item_name: str = Field(max_length=200)
    sop_no: str = Field(max_length=64)
    standard_text: str = Field(max_length=300)
    operator: str | None = Field(default=None, max_length=10)
    limit_min: float | None = None
    limit_max: float | None = None
    method_source: str | None = Field(default=None, max_length=64)
    remark: str | None = Field(default=None, max_length=200)


class StandardItemUpdate(BaseModel):
    """更新标准项目行。"""

    seq: int | None = None
    category: str | None = Field(default=None, max_length=100)
    item_name: str | None = Field(default=None, max_length=200)
    sop_no: str | None = Field(default=None, max_length=64)
    standard_text: str | None = Field(default=None, max_length=300)
    operator: str | None = Field(default=None, max_length=10)
    limit_min: float | None = None
    limit_max: float | None = None
    method_source: str | None = Field(default=None, max_length=64)
    remark: str | None = Field(default=None, max_length=200)


# ─── 标准文档导入（预览确认流程）───


class StandardImportDocument(BaseModel):
    """导入草稿的文档头（可修改后确认）。"""

    file_no: str = Field(max_length=100)
    product_name: str = Field(max_length=200)
    product_code: str | None = Field(default=None, max_length=64)
    product_internal_code: str | None = Field(default=None, max_length=64)
    specification: str | None = Field(default=None, max_length=200)
    valid_years: str | None = Field(default=None, max_length=32)
    effective_date: str | None = Field(default=None, max_length=32)
    version: str | None = Field(default=None, max_length=32)


class StandardImportItem(BaseModel):
    """导入草稿的项目行（可修改后确认）。"""

    seq: int | None = None
    category: str | None = Field(default=None, max_length=100)
    item_name: str = Field(max_length=200)
    sop_no: str | None = Field(default=None, max_length=64)
    standard_text: str | None = Field(default=None, max_length=300)
    operator: str | None = Field(default=None, max_length=10)
    limit_min: float | None = None
    limit_max: float | None = None
    method_source: str | None = Field(default=None, max_length=64)
    remark: str | None = Field(default=None, max_length=200)


class StandardImportConfirm(BaseModel):
    """确认导入：携带人工校正后的文档头与项目行。"""

    document: StandardImportDocument
    items: list[StandardImportItem] = Field(min_length=0, max_length=500)
