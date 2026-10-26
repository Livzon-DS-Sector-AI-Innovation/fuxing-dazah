"""Safety API schemas — facility_map（F2 厂区风险分区 pins）。"""

from __future__ import annotations

from pydantic import BaseModel


class PinRef(BaseModel):
    """分区明细引用（job/fire/central 三形，字段按 kind 取用）。"""

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


class DistrictPin(BaseModel):
    dist_id: str
    jobs: dict[str, int]
    alarms: dict[str, int]
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
