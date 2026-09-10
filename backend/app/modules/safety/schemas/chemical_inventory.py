"""危化品库存管理 Schema — Pydantic v2（单表固定行版）。

总表为固定行台账（原地更新），风险标记(正常/预警) + 风险说明(预警类型多选) 系统回填。
只做请求/响应模型 + Enum + OPTIONS，不 import ORM model。
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ChemicalDepartment(str, Enum):  # noqa: UP042
    """危化品库存部门。"""  # noqa: UP042

    WAREHOUSE = "warehouse"
    EXTRACTION_1 = "extraction_1"
    EXTRACTION_2 = "extraction_2"
    EXTRACTION_2B = "extraction_2b"
    FERMENTATION_1 = "fermentation_1"
    FERMENTATION_2 = "fermentation_2"
    STRAIN = "strain"
    QC = "qc"
    ENV = "env"
    PURIFICATION = "purification"
    SEMI_SYNTHESIS = "semi_synth"
    TECH_REFINEMENT = "tech_refine"
    OTHER = "other"


CHEMICAL_DEPARTMENT_OPTIONS = [
    {"value": ChemicalDepartment.WAREHOUSE, "label": "仓储部"},
    {"value": ChemicalDepartment.EXTRACTION_1, "label": "提炼一部"},
    {"value": ChemicalDepartment.EXTRACTION_2, "label": "提炼二期"},
    {"value": ChemicalDepartment.EXTRACTION_2B, "label": "提炼二部"},
    {"value": ChemicalDepartment.FERMENTATION_1, "label": "发酵一部"},
    {"value": ChemicalDepartment.FERMENTATION_2, "label": "发酵二部"},
    {"value": ChemicalDepartment.STRAIN, "label": "菌种中心"},
    {"value": ChemicalDepartment.QC, "label": "QC"},
    {"value": ChemicalDepartment.ENV, "label": "环保"},
    {"value": ChemicalDepartment.PURIFICATION, "label": "精制"},
    {"value": ChemicalDepartment.SEMI_SYNTHESIS, "label": "提炼半合成工程中心"},
    {"value": ChemicalDepartment.TECH_REFINEMENT, "label": "提炼技术精进中心"},
    {"value": ChemicalDepartment.OTHER, "label": "其他"},
]


# 部门枚举 → 中文名（权威清单，前端 CHEMICAL_DEPARTMENT_LABELS 与后端通知/日报共用）
CHEMICAL_DEPARTMENT_LABELS: dict[str, str] = {
    opt["value"].value: opt["label"] for opt in CHEMICAL_DEPARTMENT_OPTIONS
}


class ChemicalUnit(str, Enum):  # noqa: UP042
    """库存单位。"""  # noqa: UP042

    KG = "kg"
    G = "g"
    T = "T"
    L = "L"
    ML = "ml"
    BOTTLE = "bottle"


CHEMICAL_UNIT_OPTIONS = [
    {"value": ChemicalUnit.KG, "label": "kg"},
    {"value": ChemicalUnit.G, "label": "g"},
    {"value": ChemicalUnit.T, "label": "T"},
    {"value": ChemicalUnit.L, "label": "L"},
    {"value": ChemicalUnit.ML, "label": "ml"},
    {"value": ChemicalUnit.BOTTLE, "label": "瓶"},
]


class HazardClass(str, Enum):  # noqa: UP042
    """危险性类别。"""  # noqa: UP042

    FLAMMABLE = "flammable"
    EXPLOSIVE = "explosive"
    PRECURSOR_DRUG = "precursor_drug"
    PRECURSOR_EXPLOSIVE = "precursor_explosive"
    CORROSIVE = "corrosive"
    TOXIC = "toxic"
    OXIDIZER = "oxidizer"
    IRRITANT = "irritant"


HAZARD_CLASS_OPTIONS = [
    {"value": HazardClass.FLAMMABLE, "label": "易燃", "color": "red"},
    {"value": HazardClass.EXPLOSIVE, "label": "易爆", "color": "red"},
    {"value": HazardClass.PRECURSOR_DRUG, "label": "易制毒", "color": "orange"},
    {"value": HazardClass.PRECURSOR_EXPLOSIVE, "label": "易制爆", "color": "orange"},
    {"value": HazardClass.CORROSIVE, "label": "腐蚀", "color": "orange"},
    {"value": HazardClass.TOXIC, "label": "毒性", "color": "gold"},
    {"value": HazardClass.OXIDIZER, "label": "氧化剂", "color": "gold"},
    {"value": HazardClass.IRRITANT, "label": "刺激性", "color": "blue"},
]


class RiskFlag(str, Enum):  # noqa: UP042
    """风险标记（二元）。"""  # noqa: UP042

    NORMAL = "normal"
    WARN = "warn"


RISK_FLAG_OPTIONS = [
    {"value": RiskFlag.NORMAL, "label": "正常", "color": "default"},
    {"value": RiskFlag.WARN, "label": "预警", "color": "red"},
]


class RiskNote(str, Enum):  # noqa: UP042
    """风险说明取值（正常 + 预警类型）。"""  # noqa: UP042

    NORMAL = "normal"
    OVER_LIMIT = "over_limit"
    NEAR_LIMIT = "near_limit"
    HIGH_RATIO = "high_ratio"
    UNCLASSIFIED = "unclassified"
    UNIT_ANOMALY = "unit_anomaly"
    SPECIAL_STORAGE = "special_storage"


RISK_NOTE_OPTIONS = [
    {"value": RiskNote.NORMAL, "label": "正常", "color": "default"},
    {"value": RiskNote.OVER_LIMIT, "label": "超量", "color": "red"},
    {"value": RiskNote.NEAR_LIMIT, "label": "临限", "color": "orange"},
    {"value": RiskNote.HIGH_RATIO, "label": "高占比", "color": "gold"},
    {"value": RiskNote.UNCLASSIFIED, "label": "未分类", "color": "gold"},
    {"value": RiskNote.UNIT_ANOMALY, "label": "单位异常", "color": "gold"},
    {"value": RiskNote.SPECIAL_STORAGE, "label": "专库违规", "color": "orange"},
]


# ── 请求/响应 ──


class ChemicalInventoryRecordCreate(BaseModel):
    """手工补录/更新一条库存记录（固定行，同 部门+存放部位+物料名称 只一条）。"""

    model_config = ConfigDict(use_enum_values=True)

    department: ChemicalDepartment = Field(..., description="部门")
    storage_location: str | None = Field(None, description="存放部位")
    material_name: str = Field(..., min_length=1, max_length=128, description="物料名称")
    package_spec: str | None = Field(None, description="包装规格")
    quantity: float | None = Field(None, description="库存数量")
    unit: ChemicalUnit | None = Field(None, description="单位")
    total_quantity_t: float | None = Field(None, description="现场物料总量(T)")
    max_limit: float | None = Field(None, description="库存上限")
    max_limit_unit: ChemicalUnit | None = Field(None, description="上限单位")
    hazard_classes: list[HazardClass] | None = Field(None, description="危险性（多选）")
    category: str | None = Field(None, description="品类")
    remark: str | None = Field(None, description="备注")


class ChemicalInventoryRecordResponse(BaseModel):
    """库存记录响应。"""

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: uuid.UUID
    department: str
    storage_location: str | None = None
    material_name: str
    package_spec: str | None = None
    quantity: float | None = None
    unit: str | None = None
    total_quantity_t: float | None = None
    max_limit: float | None = None
    max_limit_unit: str | None = None
    hazard_classes: list[str] | None = None
    category: str | None = None
    last_updated_at: datetime | None = None
    remark: str | None = None
    risk_flag: str = "normal"
    risk_note: list[str] | None = None


__all__: list[str] = [
    "CHEMICAL_DEPARTMENT_LABELS",
    "CHEMICAL_DEPARTMENT_OPTIONS",
    "CHEMICAL_UNIT_OPTIONS",
    "ChemicalDepartment",
    "ChemicalInventoryRecordCreate",
    "ChemicalInventoryRecordResponse",
    "ChemicalUnit",
    "HAZARD_CLASS_OPTIONS",
    "HazardClass",
    "RISK_FLAG_OPTIONS",
    "RISK_NOTE_OPTIONS",
    "RiskFlag",
    "RiskNote",
]
