"""Safety request and response schemas."""

from enum import StrEnum


class ContractorStatus(StrEnum):
    """承包商状态枚举"""

    ACTIVE = "active"
    INACTIVE = "inactive"
    BLACKLISTED = "blacklisted"


CONTRACTOR_STATUS_OPTIONS = [
    {"value": ContractorStatus.ACTIVE, "label": "活跃", "color": "green"},
    {"value": ContractorStatus.INACTIVE, "label": "停用", "color": "default"},
    {"value": ContractorStatus.BLACKLISTED, "label": "黑名单", "color": "red"},
]


class QualificationTypeEnum(StrEnum):
    """承包资质类型枚举"""

    CONSTRUCTION = "construction"
    INSTALLATION = "installation"
    MAINTENANCE = "maintenance"
    CLEANING = "cleaning"
    SECURITY = "security"
    OTHER = "other"


QUALIFICATION_TYPE_OPTIONS = [
    {"value": QualificationTypeEnum.CONSTRUCTION, "label": "建筑施工"},
    {"value": QualificationTypeEnum.INSTALLATION, "label": "设备安装"},
    {"value": QualificationTypeEnum.MAINTENANCE, "label": "检维修"},
    {"value": QualificationTypeEnum.CLEANING, "label": "保洁"},
    {"value": QualificationTypeEnum.SECURITY, "label": "安保"},
    {"value": QualificationTypeEnum.OTHER, "label": "其他"},
]


class QualificationLevelEnum(StrEnum):
    """资质等级枚举"""

    GRADE_A = "grade_a"
    GRADE_B = "grade_b"
    GRADE_C = "grade_c"


QUALIFICATION_LEVEL_OPTIONS = [
    {"value": QualificationLevelEnum.GRADE_A, "label": "甲级/一级"},
    {"value": QualificationLevelEnum.GRADE_B, "label": "乙级/二级"},
    {"value": QualificationLevelEnum.GRADE_C, "label": "丙级/三级"},
]


class ContractorTrainingStatusEnum(StrEnum):
    """承包商培训状态枚举"""

    UNTRAINED = "untrained"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    EXPIRED = "expired"


CONTRACTOR_TRAINING_STATUS_OPTIONS = [
    {"value": ContractorTrainingStatusEnum.UNTRAINED, "label": "未培训", "color": "default"},
    {"value": ContractorTrainingStatusEnum.IN_PROGRESS, "label": "培训中", "color": "processing"},
    {"value": ContractorTrainingStatusEnum.PASSED, "label": "已通过", "color": "green"},
    {"value": ContractorTrainingStatusEnum.EXPIRED, "label": "已过期", "color": "red"},
]


class WorkRecordStatusEnum(StrEnum):
    """施工记录状态枚举"""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    EVALUATED = "evaluated"


WORK_RECORD_STATUS_OPTIONS = [
    {"value": WorkRecordStatusEnum.IN_PROGRESS, "label": "施工中", "color": "processing"},
    {"value": WorkRecordStatusEnum.COMPLETED, "label": "已完成", "color": "green"},
    {"value": WorkRecordStatusEnum.EVALUATED, "label": "已评价", "color": "blue"},
]


# ── 承包商主表 ──
