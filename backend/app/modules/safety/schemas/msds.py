"""MSDS 智能提取入库 — Pydantic 请求/响应 Schema。

采集入口：供应商资料表（Bitable）→ msds_collection_records
标准化台账：MSDS 表（Bitable）→ msds_documents（1 采集 → N 台账）
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

# ── 枚举 ──

PARSE_STATUS_OPTIONS = [
    {"value": "pending", "label": "待解析"},
    {"value": "parsed", "label": "已解析"},
    {"value": "failed", "label": "解析失败"},
]

REVIEW_STATUS_OPTIONS = [
    {"value": "pending", "label": "待复核"},
    {"value": "approved", "label": "已复核"},
    {"value": "rejected", "label": "已驳回"},
]

ARCHIVE_STATUS_OPTIONS = [
    {"value": "pending", "label": "未归档"},
    {"value": "archived", "label": "已归档"},
]


# ── AI 提取 28 字段（单个化学品）──


class MsdsExtractionOutput(BaseModel):
    """AI 从供应商 MSDS 附件提取的 28 字段（12 类）。

    数值字段保留原始单位字符串（"12℃（CC）"），不做数值化。
    允许空值建档：文档确无值时字段为 None。
    """

    # 基础标识（4）
    name: str | None = None
    cas_no: str | None = None
    molecular_formula: str | None = None
    un_no: str | None = None

    # 危险性概述（2）
    hazard_statement: str | None = None
    label_elements: str | None = None

    # 理化特性（10）
    appearance: str | None = None
    solubility: str | None = None
    melting_point: str | None = None
    boiling_point: str | None = None
    flash_point: str | None = None
    relative_density: str | None = None
    explosion_upper_limit: str | None = None
    explosion_lower_limit: str | None = None
    autoignition_temperature: str | None = None
    decomposition_temperature: str | None = None

    # 职业接触限值（3）
    pc_twa: str | None = None
    pc_stel: str | None = None
    mac: str | None = None

    # 健康与环境危害（2）
    health_hazard: str | None = None
    environmental_hazard: str | None = None

    # 应急响应（4）
    first_aid: str | None = None
    fire_fighting: str | None = None
    leakage_response: str | None = None
    waste_disposal: str | None = None

    # 防护与控制（3）
    exposure_controls: str | None = None
    handling_storage: str | None = None
    stability_reactivity: str | None = None


class MsdsExtractionEntries(BaseModel):
    """AI 提取返回结构 — entries 数组（一个化学品一条，支持多化学品拆分）。"""

    entries: list[MsdsExtractionOutput] = Field(default_factory=list)


# ── 采集记录响应 ──


class MsdsCollectionResponse(BaseModel):
    """供应商资料采集记录响应。"""

    id: uuid.UUID
    feishu_record_id: str | None = None
    source_date: date | None = None
    attachment: list | None = None
    person_data: list | None = None
    parse_status: str = "pending"
    parse_error: str | None = None
    parse_result: list | None = None
    msds_table_record_ids: list | None = None
    synced_at: datetime | None = None
    is_deleted: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── 台账响应 ──


class MsdsDocumentResponse(BaseModel):
    """MSDS 标准化台账响应（镜像 MSDS 表 29 字段）。"""

    id: uuid.UUID
    feishu_record_id: str | None = None
    collection_record_id: uuid.UUID | None = None
    source_date: date | None = None

    # 基础标识
    name: str | None = None
    cas_no: str | None = None
    molecular_formula: str | None = None
    un_no: str | None = None
    hazard_class: str | None = None

    # 危险性概述
    hazard_statement: str | None = None
    label_elements: str | None = None

    # 理化特性
    appearance: str | None = None
    solubility: str | None = None
    melting_point: str | None = None
    boiling_point: str | None = None
    flash_point: str | None = None
    relative_density: str | None = None
    explosion_upper_limit: str | None = None
    explosion_lower_limit: str | None = None
    autoignition_temperature: str | None = None
    decomposition_temperature: str | None = None

    # 职业接触限值
    pc_twa: str | None = None
    pc_stel: str | None = None
    mac: str | None = None

    # 危害
    health_hazard: str | None = None
    environmental_hazard: str | None = None

    # 应急
    first_aid: str | None = None
    fire_fighting: str | None = None
    leakage_response: str | None = None
    waste_disposal: str | None = None

    # 防护
    exposure_controls: str | None = None
    handling_storage: str | None = None
    stability_reactivity: str | None = None

    # 附件与状态
    msds_attachment: list | None = None
    review_status: str = "pending"
    archive_status: str = "pending"
    is_deleted: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class MsdsStatsResponse(BaseModel):
    """MSDS 统计仪表盘。"""

    total_collections: int = 0
    parsed_collections: int = 0
    failed_collections: int = 0
    total_documents: int = 0
    archived_documents: int = 0
    by_parse_status: dict[str, int] = Field(default_factory=dict)
    by_review_status: dict[str, int] = Field(default_factory=dict)
