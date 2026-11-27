"""离职管理请求/响应 Schema（pydantic v2 风格，与 hr/schemas.py 保持一致）。

台账增强（筛选/导出/保存视图）的契约在同目录 ledger_schemas.py。
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class OffboardingCaseCreate(BaseModel):
    employee_id: UUID = Field(..., description="员工档案ID")
    offboarding_date: date = Field(..., description="离职日期")
    offboarding_type: str = Field("辞职", description="离职类型: 辞职/辞退/合同到期/退休/其他")
    reason: str | None = Field(None, max_length=512, description="离职原因")
    application_submitted: bool = Field(True, description="是否递交离职申请")
    health_check_required: bool | None = Field(
        None, description="是否需离岗体检（缺省取员工 is_key_position）",
    )
    remark: str | None = Field(None, max_length=512, description="备注")
    departure_record_id: UUID | None = Field(
        None, description="从离职台账行发起时传：离职日期与类型取该台账行（以飞书离职表为准）",
    )


class OffboardingCaseUpdate(BaseModel):
    offboarding_date: date | None = None
    offboarding_type: str | None = None
    reason: str | None = Field(None, max_length=512)
    application_submitted: bool | None = None
    health_check_required: bool | None = None
    remark: str | None = Field(None, max_length=512)


class ClearanceItemIn(BaseModel):
    category: str = Field(..., description="admin/finance/hr/work")
    item_name: str = Field(..., max_length=64)
    status: str = Field("pending", description="pending/confirmed/deducted")
    deduction_amount: Decimal | None = Field(None, ge=0, description="扣款金额（元）")
    supplement_amount: Decimal | None = Field(None, ge=0, description="补发金额（元）")
    remark: str | None = Field(None, max_length=255)
    confirmed_by: str | None = Field(None, max_length=64)


class ClearanceBulkReplace(BaseModel):
    items: list[ClearanceItemIn] = Field(..., max_length=200, description="全量替换该办结单的清退明细")


class ManualStageDone(BaseModel):
    stage: str = Field(..., pattern="^(approving|clearing)$", description="approving（离职审批）/ clearing（清退会签）")
    note: str | None = Field(None, max_length=255, description="办理说明（站内登记原因）")


class IssueCertificateRequest(BaseModel):
    cert_template: str = Field("electronic", pattern="^(electronic|paper)$", description="electronic 电子单张 / paper 纸质两联")
    mail_recipient: str | None = Field(None, max_length=128, description="送达邮箱（开具后自动发送）")


class SendDeliveryRequest(BaseModel):
    mail_recipient: str | None = Field(None, max_length=128, description="送达邮箱（重发）")
    sms_phone: str | None = Field(None, max_length=32, description="短信接收号码（登记已人工发送）")


class HandoverIn(BaseModel):
    handover_to: str | None = Field(None, max_length=64, description="交接人（传空字符串清空）")
    dept_clerk: str | None = Field(None, max_length=64, description="部门办事员（传空字符串清空）")


class PaperSignRequest(BaseModel):
    signed_by: str = Field(..., min_length=1, max_length=64, description="签收人（员工本人姓名）")


class SignatureSignRequest(BaseModel):
    """员工到人事办公室当面手写签名：在 HR 登录的公司电脑上签，签名图随档案留存。"""

    signature: str = Field(..., max_length=500_000, description="手写签名 PNG/JPEG dataURL（base64）")
    signed_name: str | None = Field(None, max_length=64, description="签署人确认姓名（留空取员工姓名）")


class CloseCaseRequest(BaseModel):
    account_deactivated: bool = Field(True, description="飞书账号已注销勾选")
