"""相关方准入（contractor admission）请求与响应 Schemas.

只描述 API 契约，不 import ORM model（CLAUDE.md 铁律）。
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, computed_field


class AttachmentItem(BaseModel):
    """附件项（与平台 JSON 数组元素结构一致）"""

    name: str | None = None
    path: str | None = None
    file_token: str | None = None
    original_name: str | None = None


class ContractorAdmissionBase(BaseModel):
    """相关方准入基础字段（与 Bitable 字段映射一致）"""

    company_name: str | None = Field(None, max_length=255, description="作业单位名称")
    related_party_type: str | None = Field(
        None, max_length=32, description="相关方类型: 承包商/合作类相关方/劳务派遣/其他相关方"
    )
    contact_person: str | None = Field(None, max_length=100, description="承包商负责人")
    contact_phone: str | None = Field(None, max_length=32, description="承包商负责人联系电话")
    liaison_user_id: str | None = Field(None, max_length=64, description="对接人员飞书 open_id/user_id")
    liaison_user_name: str | None = Field(None, max_length=100, description="对接人员姓名")
    entry_date: date | None = Field(None, description="入厂日期")
    start_date: date | None = Field(None, description="开始日期")
    end_date: date | None = Field(None, description="结束日期")
    material_expiry_date: date | None = Field(None, description="材料失效日期")
    actual_submit_date: date | None = Field(None, description="实际提交日期")
    actual_complete_date: date | None = Field(None, description="实际完成日期")
    submit_status: str | None = Field(
        None, max_length=32, description="提交状态: 已完成/进行中/未开始"
    )
    training_status: str | None = Field(
        None, max_length=32, description="培训状态: 已完结/已培训待补材/未培训"
    )
    notes: str | None = Field(None, description="备注")
    safety_agreement_files: list[AttachmentItem] | None = Field(
        None, description="安全管理协议附件（按相关方类型取对应 Bitable 字段）"
    )
    business_license_files: list[AttachmentItem] | None = Field(
        None, description="企业营业执照附件"
    )
    insurance_files: list[AttachmentItem] | None = Field(
        None, description="现场作业保险凭证附件"
    )
    assessment_rules_files: list[AttachmentItem] | None = Field(
        None, description="承包商考核细则附件"
    )
    employee_cert_files: list[AttachmentItem] | None = Field(
        None, description="员工证明盖章文件附件"
    )
    on_site_leader_stamp_files: list[AttachmentItem] | None = Field(
        None, description="现场负责人盖章文件附件"
    )


class ContractorAdmissionCreate(ContractorAdmissionBase):
    """创建相关方准入"""

    admission_no: str | None = Field(
        None, max_length=64, description="准入编号（人工/平台生成，Bitable 无该列，可空）"
    )


class ContractorAdmissionUpdate(ContractorAdmissionBase):
    """更新相关方准入（基类字段全部可选，等价于全字段可选）"""

    pass


class AdmissionReviewDimensionResult(BaseModel):
    """单维度审核结果（agreement/license/insurance 内嵌结构）"""

    conclusion: str | None = Field(None, description="审核通过/需补充完善/审核不通过")
    report: str | None = Field(None, description="维度审核报告（不符合项+补材指引）")
    defects: list[str] = Field(default_factory=list, description="不符合项明细")


class AdmissionReviewResultResponse(BaseModel):
    """AI 审核结果（ai_review_result JSONB 投影）"""

    agreement: AdmissionReviewDimensionResult | None = Field(
        None, description="安全管理协议维度审核结果"
    )
    license: AdmissionReviewDimensionResult | None = Field(
        None, description="企业营业执照维度审核结果"
    )
    insurance: AdmissionReviewDimensionResult | None = Field(
        None, description="现场作业保险凭证维度审核结果"
    )
    overall_conclusion: str | None = Field(
        None, description="总体结论: 审核通过/需补充完善/审核不通过"
    )
    overall_report: str | None = Field(None, description="综合审核报告/退回话术")
    defect_categories: list[str] = Field(
        default_factory=list,
        description="不符合原因分类多选: A基础信息类/B有效期类/C签章类/D骑缝章类",
    )
    regulations: list[dict] = Field(
        default_factory=list, description="参考法规 [{doc_title, article_ref}]"
    )


class ContractorAdmissionResponse(ContractorAdmissionBase):
    """相关方准入详情响应"""

    id: uuid.UUID
    admission_no: str | None = None
    source: str = Field("bitable", description="数据来源: bitable(飞书同步)/manual(手动)")
    feishu_record_id: str | None = None
    feishu_table_id: str | None = None
    feishu_url: str | None = Field(None, description="Bitable 记录跳转链接")
    ai_review_status: str = Field(
        "none", description="AI审核状态: none/processing/completed/failed"
    )
    ai_review_result: AdmissionReviewResultResponse | None = Field(
        None, description="AI 三维度审核结果"
    )
    ai_error_message: str | None = Field(None, description="AI审核失败信息")
    ai_reviewed_at: datetime | None = Field(None, description="最近一次 AI 审核完成时间")
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ContractorAdmissionListItem(BaseModel):
    """列表项（轻量，不含大 JSON；overall_conclusion 从 ai_review_result 平铺）"""

    id: uuid.UUID
    admission_no: str | None = None
    company_name: str | None = None
    related_party_type: str | None = None
    liaison_user_name: str | None = None
    entry_date: date | None = None
    submit_status: str | None = None
    training_status: str | None = None
    ai_review_status: str = "none"
    # 内部投影承载字段：从 ORM 的 ai_review_result(dict) 校验为结构化模型；
    # 序列化时排除，仅供 computed field 平铺 overall_conclusion
    ai_review_result: AdmissionReviewResultResponse | None = Field(
        default=None, exclude=True, description="（内部使用）AI 审核结果投影"
    )
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ai_overall_conclusion(self) -> str | None:
        """从 ai_review_result.overall_conclusion 平铺（审核通过/需补充完善/审核不通过）"""
        if self.ai_review_result is None:
            return None
        return self.ai_review_result.overall_conclusion

    class Config:
        from_attributes = True


class ContractorAdmissionStats(BaseModel):
    """相关方准入 KPI 统计"""

    total: int = Field(0, description="总记录数（未删除）")
    by_ai_review_status: dict[str, int] = Field(
        default_factory=dict, description="按 AI 审核状态分组: none/processing/completed/failed"
    )
    by_related_party_type: dict[str, int] = Field(
        default_factory=dict, description="按相关方类型分组"
    )
    by_submit_status: dict[str, int] = Field(
        default_factory=dict, description="按提交状态分组: 已完成/进行中/未开始"
    )
