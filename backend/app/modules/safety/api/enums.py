"""Safety API — enums endpoints."""

from fastapi import APIRouter, Depends

from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import (
    ABNORMALITY_STATUS_OPTIONS,
    ACCIDENT_LEVEL_OPTIONS,
    ACCIDENT_STATUS_OPTIONS,
    ACCIDENT_TYPE_OPTIONS,
    ACTION_ITEM_STATUS_OPTIONS,
    APPROVAL_DECISION_OPTIONS,
    CHANGE_DURATION_OPTIONS,
    CHANGE_GRADE_OPTIONS,
    CHANGE_TYPE_OPTIONS,
    CHECK_TYPE_OPTIONS,
    COMPLETION_METHOD_OPTIONS,
    CONTRACTOR_STATUS_OPTIONS,
    CONTRACTOR_TRAINING_STATUS_OPTIONS,
    DETECTION_TYPE_OPTIONS,
    EHS_CHANGE_STATUS_OPTIONS,
    EXAM_CONCLUSION_OPTIONS,
    EXAM_STATUS_OPTIONS,
    EXAM_TYPE_OPTIONS,
    HAZARD_CATEGORY_OPTIONS,
    HAZARD_FACTOR_CATEGORY_OPTIONS,
    HAZARD_LEVEL_OPTIONS,
    HAZARD_TYPE_OPTIONS,
    INJURY_SEVERITY_OPTIONS,
    KNOWLEDGE_CATEGORY_OPTIONS,
    MONITOR_STATUS_OPTIONS,
    OEL_COMPLIANCE_STATUS_OPTIONS,
    OPERATION_LEVEL_OPTIONS,
    OPERATION_TYPE_OPTIONS,
    PERMIT_STATUS_OPTIONS,
    PERSONNEL_STATUS_OPTIONS,
    PSSR_RESULT_OPTIONS,
    QUALIFICATION_LEVEL_OPTIONS,
    QUALIFICATION_TYPE_OPTIONS,
    REPORT_STATUS_OPTIONS,
    REVIEW_OPINION_OPTIONS,
    REVISION_SCOPE_OPTIONS,
    REVISION_TYPE_OPTIONS,
    RISK_ASSESSMENT_METHOD_OPTIONS,
    RISK_LEVEL_OPTIONS,
    TRAINING_MODE_OPTIONS,
    TRAINING_TYPE_OPTIONS,
    WORK_RECORD_STATUS_OPTIONS,
)

enums_router = APIRouter()


@enums_router.get("/enums", response_model=ApiResponse, summary="获取枚举值列表")
async def get_enums(
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取安全模块的所有枚举值选项"""

    return ApiResponse(
        data={
            "check_types": CHECK_TYPE_OPTIONS,
            "hazard_types": HAZARD_TYPE_OPTIONS,
            "hazard_levels": HAZARD_LEVEL_OPTIONS,
            "hazard_categories": HAZARD_CATEGORY_OPTIONS,
            "accident_types": ACCIDENT_TYPE_OPTIONS,
            "accident_levels": ACCIDENT_LEVEL_OPTIONS,
            "accident_statuses": ACCIDENT_STATUS_OPTIONS,
            "injury_severities": INJURY_SEVERITY_OPTIONS,
            "training_types": TRAINING_TYPE_OPTIONS,
            "training_modes": TRAINING_MODE_OPTIONS,
            "revision_types": REVISION_TYPE_OPTIONS,
            "revision_scopes": REVISION_SCOPE_OPTIONS,
            "review_opinions": REVIEW_OPINION_OPTIONS,
            "operation_types": OPERATION_TYPE_OPTIONS,
            "operation_levels": OPERATION_LEVEL_OPTIONS,
            "personnel_statuses": PERSONNEL_STATUS_OPTIONS,
            "permit_statuses": PERMIT_STATUS_OPTIONS,
            "completion_methods": COMPLETION_METHOD_OPTIONS,
            "knowledge_categories": KNOWLEDGE_CATEGORY_OPTIONS,
            "report_statuses": REPORT_STATUS_OPTIONS,
            "contractor_statuses": CONTRACTOR_STATUS_OPTIONS,
            "qualification_types": QUALIFICATION_TYPE_OPTIONS,
            "qualification_levels": QUALIFICATION_LEVEL_OPTIONS,
            "contractor_training_statuses": CONTRACTOR_TRAINING_STATUS_OPTIONS,
            "work_record_statuses": WORK_RECORD_STATUS_OPTIONS,
            "ehs_change_types": CHANGE_TYPE_OPTIONS,
            "ehs_change_grades": CHANGE_GRADE_OPTIONS,
            "ehs_change_durations": CHANGE_DURATION_OPTIONS,
            "ehs_change_statuses": EHS_CHANGE_STATUS_OPTIONS,
            "risk_levels": RISK_LEVEL_OPTIONS,
            "risk_assessment_methods": RISK_ASSESSMENT_METHOD_OPTIONS,
            "approval_decisions": APPROVAL_DECISION_OPTIONS,
            "action_item_statuses": ACTION_ITEM_STATUS_OPTIONS,
            "pssr_results": PSSR_RESULT_OPTIONS,
            "oh_detection_types": DETECTION_TYPE_OPTIONS,
            "oh_hazard_factor_categories": HAZARD_FACTOR_CATEGORY_OPTIONS,
            "oh_oel_compliance_statuses": OEL_COMPLIANCE_STATUS_OPTIONS,
            "oh_monitor_statuses": MONITOR_STATUS_OPTIONS,
            "oh_exam_types": EXAM_TYPE_OPTIONS,
            "oh_exam_conclusions": EXAM_CONCLUSION_OPTIONS,
            "oh_exam_statuses": EXAM_STATUS_OPTIONS,
            "oh_abnormality_statuses": ABNORMALITY_STATUS_OPTIONS,
        }
    )


