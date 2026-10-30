"""职业健康人员汇总台账 schemas — Enum 化（Pydantic v2）。

对齐 backend-design.md §1.1 OhPerson 列定义。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.modules.safety.schemas.oh_health_exams import OhAiConclusion, OhExamType


class OhWorkStatus(StrEnum):
    """在岗状态（原「最后体检状态」更名，D6）"""

    ON_POST = "on_post"
    OFF_POST = "off_post"
    PRE_EMPLOYMENT = "pre_employment"
    TRANSFER = "transfer"


OH_WORK_STATUS_OPTIONS = [
    {"value": OhWorkStatus.ON_POST, "label": "在岗"},
    {"value": OhWorkStatus.OFF_POST, "label": "离岗"},
    {"value": OhWorkStatus.PRE_EMPLOYMENT, "label": "岗前"},
    {"value": OhWorkStatus.TRANSFER, "label": "转岗"},
]


class OhPersonBase(BaseModel):
    """人员汇总台账基础字段"""

    model_config = ConfigDict(use_enum_values=True)

    feishu_record_id: str | None = Field(None, max_length=64, description="Bitable 记录 ID")
    source: str = Field("manual", max_length=16, description="数据来源: bitable/manual")
    name: str = Field(..., max_length=100, description="员工姓名")
    id_card_no: str | None = Field(None, max_length=32, description="身份证号（关联键）")
    employee_no: str | None = Field(None, max_length=64, description="工号")
    user_id: uuid.UUID | None = Field(None, description="关联 identity.users.id")
    open_id: str | None = Field(None, max_length=64, description="飞书 open_id")
    department: str | None = Field(None, max_length=100, description="部门")
    position: str | None = Field(None, max_length=100, description="岗位")
    gender: str | None = Field(None, max_length=16, description="性别")
    age: int | None = Field(None, description="年龄")
    marital_status: str | None = Field(None, max_length=16, description="婚姻状况")
    phone: str | None = Field(None, max_length=32, description="电话")
    total_work_years: float | None = Field(None, description="总工龄（年.月折算）")
    hazard_exposure_years: float | None = Field(None, description="接害工龄（年.月折算）")
    hazard_factors: list[str] | None = Field(None, description="接触危害因素 [标准名]")
    last_exam_at: datetime | None = Field(None, description="最后体检时间（平台回填）")
    last_exam_type: OhExamType | None = Field(None, description="最后体检类别")
    last_exam_conclusion: OhAiConclusion | None = Field(None, description="最后体检结论（ai_conclusion 归一）")
    last_exam_summary: str | None = Field(None, description="最后体检摘要")
    exam_record_ids: list[str] | None = Field(None, description="体检记录 ID 数组")
    safety_officer: str | None = Field(None, max_length=100, description="部门安全员")
    work_status: OhWorkStatus | None = Field(None, description="在岗状态")
    notes: str | None = Field(None, description="备注")


class OhPersonCreate(OhPersonBase):
    """创建人员台账"""

    pass


class OhPersonUpdate(BaseModel):
    """更新人员台账（所有字段可选）"""

    model_config = ConfigDict(use_enum_values=True)

    feishu_record_id: str | None = Field(None, max_length=64)
    name: str | None = Field(None, max_length=100)
    id_card_no: str | None = Field(None, max_length=32)
    employee_no: str | None = Field(None, max_length=64)
    user_id: uuid.UUID | None = None
    open_id: str | None = Field(None, max_length=64)
    department: str | None = Field(None, max_length=100)
    position: str | None = Field(None, max_length=100)
    gender: str | None = Field(None, max_length=16)
    age: int | None = None
    marital_status: str | None = Field(None, max_length=16)
    phone: str | None = Field(None, max_length=32)
    total_work_years: float | None = None
    hazard_exposure_years: float | None = None
    hazard_factors: list[str] | None = None
    last_exam_at: datetime | None = None
    last_exam_type: OhExamType | None = None
    last_exam_conclusion: OhAiConclusion | None = None
    last_exam_summary: str | None = None
    exam_record_ids: list[str] | None = None
    safety_officer: str | None = Field(None, max_length=100)
    work_status: OhWorkStatus | None = None
    notes: str | None = None


class OhPersonResponse(OhPersonBase):
    """人员台账响应"""

    # 直读模式 id 为飞书记录 ID（recXXX），created_at/updated_at 恒 None
    id: uuid.UUID | str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # Bitable 总表身份证列存在脏值（如逗号拼接的重复号，实测 39 字符），
    # 响应层放宽避免整页 500（人员面板统计卡拉 200 条曾被此打断）；
    # 写入路径（Create/Update→DB String(32)）仍走 Base 的 32 上限。
    id_card_no: str | None = Field(None, max_length=128)

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class OhPersonDetail(OhPersonResponse):
    """人员详情（含体检历史 + 异常随访展开）"""

    exams: list[Any] = Field(default_factory=list, description="体检记录链（OhHealthExamResponse）")
    followups: list[Any] = Field(default_factory=list, description="异常随访（OhFollowupResponse）")


class OhPersonStats(BaseModel):
    """人员台账统计"""

    total: int = Field(0, description="总人数")
    hazard_exposed: int = Field(0, description="接触危害人数")
    by_department: dict[str, int] = Field(default_factory=dict, description="按部门分布")
    by_position: dict[str, int] = Field(default_factory=dict, description="按岗位分布")
    by_work_status: dict[str, int] = Field(default_factory=dict, description="按在岗状态分布")
    by_last_exam_conclusion: dict[str, int] = Field(default_factory=dict, description="按最后体检结论分布")


# ═══════════════ 个人完整档案（六源聚合）═══════════════


class OhTrainingAttendeeOut(BaseModel):
    """参训人明细（签到表/成绩单 AI 转录，一人一场一行）"""

    model_config = ConfigDict(from_attributes=True)

    training_record_id: str = Field(..., description="培训行 Bitable record_id")
    training_name: str | None = Field(None, description="培训名称快照")
    category: str | None = Field(None, description="培训类别快照")
    form: str | None = Field(None, description="培训形式快照")
    held_at: datetime | None = Field(None, description="实施日期快照")
    hours: float | None = Field(None, description="培训学时快照")
    assessment: str | None = Field(None, description="考核方式快照")
    training_department: str | None = Field(None, description="组织部门快照")
    person_name: str = Field(..., description="参训人姓名（OCR 转录）")
    score: float | None = Field(None, description="考核成绩（成绩单明细按名匹配）")
    unrecognized: bool = Field(False, description="姓名辨认不清（展示灰显）")
    confidence: str | None = Field(None, description="解析置信度: high/medium/low")
    source: str = Field("ai_parse", description="来源: ai_parse | manual")


class OhProfileViolationOut(BaseModel):
    """违章档案行（Bitable 直读投影 + 逐行匹配口径）"""

    record_id: str = Field("", description="Bitable record_id")
    occurred_at: str | None = Field(None, description="违章日期（ISO）")
    person_name: str | None = Field(None, description="违章人员姓名")
    department: list[str] = Field(default_factory=list, description="所属单位")
    category: str | None = Field(None, description="违章类别")
    level: str | None = Field(None, description="违章等级")
    description: str | None = Field(None, description="违章描述")
    handling: str | None = Field(None, description="处理方式")
    status: str | None = Field(None, description="状态")
    retraining_note: str | None = Field(None, description="定向培训")
    match_basis: str = Field(..., description="匹配口径: open_id | name")


class OhProfileApplicationOut(BaseModel):
    """转岗/离岗申请摘要（档案页投影）"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_no: str | None = None
    apply_status: str | None = None
    transfer_type: str | None = None
    exam_type: str | None = None
    employee_name: str | None = None
    department: str | None = None
    position: str | None = None
    new_department: str | None = None
    new_position: str | None = None
    submitted_at: datetime | None = None
    transfer_date: datetime | None = None
    leave_date: datetime | None = None
    diff_summary: str | None = None
    needs_exam: bool | None = None
    created_exam_id: uuid.UUID | None = None


class OhPlatformIdentityPerson(BaseModel):
    """3.x 平台身份卡字段组（user/detail 投影；身份证等敏感键一律不含）"""

    platform_id: str = Field(..., description="平台人员 id")
    post_name: str | None = Field(None, description="岗位（平台主档）")
    dept_name: str | None = Field(None, description="部门（平台主档）")
    dept_whole_name: str | None = Field(None, description="部门全路径")
    direct_leader: str | None = Field(None, description="直属上级")
    job_no: str | None = Field(None, description="工号（平台主档）")
    telephone: str | None = Field(None, description="电话")
    email: str | None = Field(None, description="邮箱")
    status: str | None = Field(None, description="在职状态: 在职/离职")
    entry_date: str | None = Field(None, description="入职日期（平台大面积空，容空）")


class OhPlatformIdentity(BaseModel):
    """平台身份卡信封（第 6 源；org_directory 三态口径 + unmatched）"""

    status: str = Field(..., description="live | degraded | empty | unmatched")
    fetched_at: str | None = Field(None, description="数据时点（ISO）")
    match_basis: str | None = Field(None, description="匹配口径: job_no | name_dept")
    person: OhPlatformIdentityPerson | None = Field(
        None, description="平台身份字段组（unmatched/empty 时为 None）"
    )
    message: str | None = Field(None, description="降级/未匹配提示")


class OhPersonProfile(BaseModel):
    """个人完整档案：人员 + 体检 + 随访 + 转岗申请 + 培训参训 + 违章 + 平台身份"""

    person: OhPersonResponse
    exams: list[Any] = Field(default_factory=list, description="体检记录链（OhHealthExamResponse）")
    followups: list[Any] = Field(default_factory=list, description="异常随访（OhFollowupResponse）")
    applications: list[OhProfileApplicationOut] = Field(
        default_factory=list, description="转岗/离岗申请"
    )
    trainings: list[OhTrainingAttendeeOut] = Field(
        default_factory=list, description="培训参训明细（签到表AI转录，姓名匹配）"
    )
    violations: list[OhProfileViolationOut] | None = Field(
        None, description="违章档案行（None=源未接入/失败降级）"
    )
    platform: OhPlatformIdentity | None = Field(
        None, description="3.x 平台身份卡（第 6 源；None=采集异常降级，见 errors）"
    )
    match_notes: dict[str, str | None] = Field(
        default_factory=dict, description="匹配口径标注: trainings/violations"
    )
    errors: list[str] = Field(default_factory=list, description="降级源标注")
