"""Safety API schemas — facility_map（F2 厂区风险分区 pins）。"""

from __future__ import annotations

from pydantic import BaseModel


class PinRef(BaseModel):
    """分区明细引用（job/fire/central/key_risk/over_limit/hazard/fire_ext 八形，字段按 kind 取用）。"""

    kind: str
    ticket_type: str | None = None
    ticket_no: str | None = None
    work_site: str | None = None
    work_content: str | None = None
    alarm_time: str | None = None
    alarm_type: str | None = None
    location: str | None = None
    alarm_date: str | None = None
    alarm_description: str | None = None
    workshop: str | None = None
    report_no: str | None = None
    apply_status: str | None = None
    area: str | None = None
    operation_content: str | None = None
    start_time: str | None = None
    material_name: str | None = None
    department: str | None = None
    storage_location: str | None = None
    total_quantity_t: float | None = None
    max_limit: float | None = None
    unit: str | None = None
    # 隐患双口径（hazard_new/hazard_open）
    hazard_no: str | None = None
    hazard_desc: str | None = None
    hazard_level: str | None = None
    progress: str | None = None
    # 消防设施到期（fire_ext_due）
    ext_type: str | None = None
    ext_count: int | None = None
    due_date: str | None = None
    is_overdue: bool | None = None


class DistrictPin(BaseModel):
    dist_id: str
    jobs: dict[str, int]
    alarms: dict[str, int]
    key_risks: int = 0
    over_limits: int = 0
    hazard_news: int = 0
    hazard_opens: int = 0
    fire_ext_dues: int = 0
    refs: list[PinRef]
    truncated: bool = False


class UnmappedLocation(BaseModel):
    text: str
    count: int
    kinds: list[str]


class FacilityMapPinsOut(BaseModel):
    date: str
    pins: list[DistrictPin]
    unmapped: list[UnmappedLocation]
    errors: list[str] = []


__all__ = [
    "DistrictPin",
    "FacilityMapPinsOut",
    "PinRef",
    "UnmappedLocation",
]
