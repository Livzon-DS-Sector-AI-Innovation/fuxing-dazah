"""Safety ORM models（目录化拆分，外部 import 路径不变）。"""

from app.modules.safety.models.ai_config import (  # noqa: F401
    AiConfigAudit,
    AiModelProfile,
    AiScenarioConfig,
    AiScenarioConfigAudit,
)
from app.modules.safety.models.app_config import (  # noqa: F401
    AppConfigAudit,
    AppConfigEntry,
)
from app.modules.safety.models.bitable_config import (  # noqa: F401
    BitableConfigAudit,
    BitableConnection,
    BitableFieldMapping,
)
from app.modules.safety.models.chemical_inventory import (  # noqa: F401
    ChemicalDepartmentType,
    ChemicalInventoryRecord,
    ChemicalInventorySnapshot,
    ChemicalUnitType,
    HazardClassType,
    RiskFlagType,
)
from app.modules.safety.models.contractors import (  # noqa: F401
    Contractor,
    ContractorAdmission,
    ContractorWorkRecord,
    DrillCollectionRecord,
    DrillHazardLink,
    EmergencyDrillDocument,
    EmergencyDrillRecord,
    URSReport,
    URSReviewDocument,
    URSStandardItem,
)
from app.modules.safety.models.ehs_changes import (  # noqa: F401
    EhsChange,
)
from app.modules.safety.models.facilities import (  # noqa: F401
    TASK_STATUS_CANCELLED,
    TASK_STATUS_CLOSED,
    TASK_STATUS_ISSUED,
    TRIGGER_EVENT,
    TRIGGER_MANUAL,
    TRIGGER_POLL,
    FacilityCheckTask,
    FacilityNoticeBatch,
    FacilityTaskEvent,
)
from app.modules.safety.models.enums import (  # noqa: F401
    AbnormalityStatus,
    ActionItemStatus,
    AdmissionConclusion,
    AdmissionReviewStatus,
    AdmissionSubmitStatus,
    AdmissionTrainingStatus,
    ApprovalDecision,
    CertificateStatus,
    ChangeDuration,
    ChangeGrade,
    ChangeType,
    CompletionMethod,
    ContractorStatus,
    ContractorTrainingStatus,
    DetectionType,
    EhsChangeStatus,
    ExamConclusion,
    ExamStatus,
    ExamType,
    HazardCategory,
    HazardFactorCategory,
    HazardLevel,
    HazardType,
    InjurySeverity,
    KnowledgeCategory,
    MonitorStatus,
    OELComplianceStatus,
    OperationLevel,
    OperationType,
    PermitStatus,
    PersonnelStatus,
    PSSRResult,
    QualificationLevel,
    QualificationType,
    RegulationStatus,
    RelatedPartyType,
    ReportStatus,
    ReviewOpinion,
    RevisionScope,
    RevisionType,
    RiskAssessmentMethod,
    RiskLevel,
    TrainingLevel,
    TrainingMode,
    TrainingType,
    WorkRecordStatus,
)
from app.modules.safety.models.hazard_identifications import (  # noqa: F401
    HazardIdentification,
)
from app.modules.safety.models.hazard_reports import (  # noqa: F401
    HazardReport,
)
from app.modules.safety.models.knowledge import (  # noqa: F401
    RagplusDocMap,
    RegulationChunk,
    SafetyKnowledgeArticle,
)
from app.modules.safety.models.msds import (  # noqa: F401
    CentralAlarmRecord,
    FireAlarmRecord,
    MsdsCollectionRecord,
    MsdsDocument,
    MsdsTrainingTask,
    PersonCertificate,
    SchedulerJobRun,
)
from app.modules.safety.models.occupational_health import (  # noqa: F401
    OhExamApplication,
    OhFollowup,
    OhHazardFactor,
    OhHealthExam,
    OhPerson,
    OhPosition,
)
from app.modules.safety.models.regulation_ingest import (  # noqa: F401
    RegulationIngestRun,
)
from app.modules.safety.models.regulations import (  # noqa: F401
    OperationRegulation,
    RegulationRevision,
)
from app.modules.safety.models.scheduler import (  # noqa: F401
    SchedulerConfigAudit,
    SchedulerTaskConfig,
)
from app.modules.safety.models.scheduler_run_log import (  # noqa: F401
    SchedulerTaskRunLog,
)
from app.modules.safety.models.special_operations import (  # noqa: F401
    KeyRiskOperationReport,
    SpecialOperationPermit,
    SpecialOperationPersonnel,
    SpecialOperationReport,
)
from app.modules.safety.models.standard_check import (  # noqa: F401
    StandardCheckSnapshot,
)
from app.modules.safety.models.telemetry import (  # noqa: F401
    ALARM_LEVEL_ALARM,
    ALARM_LEVEL_WARNING,
    ALARM_STATUS_ACKED,
    ALARM_STATUS_FIRING,
    ALARM_STATUS_RESOLVED,
    PARSE_METHOD_AI,
    PARSE_METHOD_MANUAL,
    PARSE_METHOD_TEMPLATE,
    PARSE_STATUS_OK,
    PARSE_STATUS_PENDING_REVIEW,
    TelemetryAlarmRecord,
    TelemetrySnapshot,
)
from app.modules.safety.models.location_district_map import (  # noqa: F401
    LocationDistrictMap,
)
from app.modules.safety.models.location_district_suggestion import (  # noqa: F401
    LocationDistrictSuggestion,
)
from app.modules.safety.models.org_post_families import (  # noqa: F401
    OrgPostFamily,
)
from app.modules.safety.models.trainings import (  # noqa: F401
    SafetyTraining,
    TrainingRecord,
)
from app.modules.safety.models.training_attendees import (  # noqa: F401
    TrainingAttendee,
)
from app.modules.safety.models.work_ticket_review import (  # noqa: F401
    WorkTicketRectifyCheck,
    WorkTicketReview,
    WorkTicketReviewViolation,
)

__all__ = [
    'AbnormalityStatus',
    'ActionItemStatus',
    'AdmissionConclusion',
    'AdmissionReviewStatus',
    'AdmissionSubmitStatus',
    'AdmissionTrainingStatus',
    'AiConfigAudit',
    'AiModelProfile',
    'AiScenarioConfig',
    'AiScenarioConfigAudit',
    'AppConfigAudit',
    'AppConfigEntry',
    'ApprovalDecision',
    'BitableConfigAudit',
    'BitableConnection',
    'BitableFieldMapping',
    'CentralAlarmRecord',
    'CertificateStatus',
    'ChangeDuration',
    'ChangeGrade',
    'ChangeType',
    'ChemicalDepartmentType',
    'ChemicalInventoryRecord',
    'ChemicalInventorySnapshot',
    'ChemicalUnitType',
    'CompletionMethod',
    'Contractor',
    'ContractorAdmission',
    'ContractorStatus',
    'ContractorTrainingStatus',
    'ContractorWorkRecord',
    'DetectionType',
    'DrillCollectionRecord',
    'DrillHazardLink',
    'EhsChange',
    'EhsChangeStatus',
    'EmergencyDrillDocument',
    'EmergencyDrillRecord',
    'ExamConclusion',
    'ExamStatus',
    'ExamType',
    'FireAlarmRecord',
    'HazardCategory',
    'HazardClassType',
    'HazardFactorCategory',
    'HazardIdentification',
    'HazardLevel',
    'HazardReport',
    'HazardType',
    'InjurySeverity',
    'KeyRiskOperationReport',
    'KnowledgeCategory',
    'LocationDistrictMap',
    'LocationDistrictSuggestion',
    'MonitorStatus',
    'MsdsCollectionRecord',
    'MsdsDocument',
    'MsdsTrainingTask',
    'OELComplianceStatus',
    'OhExamApplication',
    'OhFollowup',
    'OrgPostFamily',
    'OhHazardFactor',
    'OhHealthExam',
    'OhPerson',
    'OhPosition',
    'OperationLevel',
    'OperationRegulation',
    'OperationType',
    'PSSRResult',
    'PermitStatus',
    'PersonCertificate',
    'PersonnelStatus',
    'QualificationLevel',
    'QualificationType',
    'RagplusDocMap',
    'RegulationChunk',
    'RegulationIngestRun',
    'RegulationRevision',
    'RegulationStatus',
    'RelatedPartyType',
    'ReportStatus',
    'ReviewOpinion',
    'RevisionScope',
    'RevisionType',
    'RiskAssessmentMethod',
    'RiskFlagType',
    'RiskLevel',
    'SafetyKnowledgeArticle',
    'SafetyTraining',
    'SchedulerConfigAudit',
    'SchedulerJobRun',
    'SchedulerTaskConfig',
    'SchedulerTaskRunLog',
    'SpecialOperationPermit',
    'SpecialOperationPersonnel',
    'SpecialOperationReport',
    'StandardCheckSnapshot',
    'TrainingAttendee',
    'TrainingLevel',
    'TrainingMode',
    'TrainingRecord',
    'TrainingType',
    'URSReport',
    'URSReviewDocument',
    'URSStandardItem',
    'WorkRecordStatus',
    'WorkTicketRectifyCheck',
    'WorkTicketReview',
    'WorkTicketReviewViolation',
]

from app.modules.safety.models.safety_ops import (  # noqa: F401
    Accident,
    DailyRiskReport,
    OhHazardMonitor,
    SafetyCheck,
)

__all__ += [
    'Accident',
    'DailyRiskReport',
    'OhHazardMonitor',
    'SafetyCheck',
]

from app.modules.safety.models.training_demand_draft import (  # noqa: F401, E402
    TrainingDemandDraft,
)

__all__ += [
    'TrainingDemandDraft',
]
