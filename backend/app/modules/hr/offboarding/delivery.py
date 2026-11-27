"""离职证明送达通道抽象：邮件（现有 send_email）+ 短信（通道预留）。

需求口径：离职办结后员工飞书账号随即注销，邮件 + 短信（附签署链接）是
主要送达与签署入口；发送时间、接收号码/邮箱与送达结果需留存。
2026-11-25 拍板：短信暂不接，本模块留统一适配点——后续接入服务商时实现
`_send_via_provider` 并在 hr_offboarding.* 增加凭证配置键即可，调用方
（service.resend_delivery）无需改动。通道未接入期间签署链接交回 HR 人工转发。
"""

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.mail_service import send_email
from app.modules.hr.models import EmailLog
from app.modules.hr.offboarding import settings as offboarding_settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DeliveryResult:
    ok: bool
    status: str  # sent / failed / not_configured
    error: str | None = None


async def send_certificate_mail(
    db: AsyncSession,
    *,
    to: str,
    employee_name: str,
    pdf_bytes: bytes,
    sign_url: str,
) -> DeliveryResult:
    """离职证明邮件：PDF 附件 + 签署链接正文；结果写 EmailLog 留痕。"""
    filename = f"解除劳动关系证明_{employee_name}.pdf"
    sign_html = (
        f'<p>您也可以点击 <a href="{sign_url}">签署链接</a> 查看证明并完成线上签字确认。</p>'
        if sign_url else ""
    )
    html = (
        f"<html><body style=\"font-family:sans-serif;padding:20px;\">"
        f"<h2>解除劳动关系证明</h2>"
        f"<p>{employee_name}，您好！</p>"
        f"<p>附件是您的解除劳动关系证明，请查收。</p>"
        f"{sign_html}</body></html>"
    )
    try:
        await send_email(
            to=to, subject="解除劳动关系证明", html_body=html,
            attachments=[(filename, pdf_bytes)], session=db,
        )
    except Exception as exc:  # SMTP 异常不中断流程，状态落库由调用方回写
        logger.warning("离职证明邮件发送失败: to=%s → %s", to, exc)
        db.add(EmailLog(email_type="departure_cert", employee_name=employee_name,
                        recipient=to, subject="解除劳动关系证明", status="failed",
                        error_message=str(exc)[:500]))
        await db.flush()
        return DeliveryResult(False, "failed", str(exc))
    db.add(EmailLog(email_type="departure_cert", employee_name=employee_name,
                    recipient=to, subject="解除劳动关系证明", status="sent"))
    await db.flush()
    return DeliveryResult(True, "sent")


async def send_certificate_sms(
    db: AsyncSession,
    *,
    to: str,
    employee_name: str,
    sign_url: str,
    contact: str,
) -> DeliveryResult:
    """离职证明短信（附签署链接）。通道未接入时返回 not_configured（不视为失败）。"""
    content = (
        f"【丽珠集团福兴医药】{employee_name}您好，您的解除劳动关系证明已开具，"
        f"请点击 {sign_url} 查看并完成签字确认。如有疑问请联系{contact}。"
    )
    ok, error, status = await _send_via_provider(to=to, content=content)
    logger.info("离职证明短信: to=%s status=%s", to, status)
    return DeliveryResult(ok, status, error)


async def _send_via_provider(*, to: str, content: str) -> tuple[bool, str | None, str]:
    """短信服务商适配点（P1 占位）：未接入返回 not_configured。

    接入方式：实现服务商 API 调用（凭证建议放 hr_offboarding.sms_* KV），
    返回 (True, None, "sent")；失败返回 (False, 错误, "failed")。
    """
    return False, "短信通道未接入（服务商确定后实现 _send_via_provider）", "not_configured"


async def build_sign_url(db: AsyncSession, token: str) -> str:
    """签字 H5 链接：基地址配置 hr_offboarding.sign_page_base_url；未配置返回空串。

    基地址须是静态段页面（…/api/departure-cert-sign），token 走查询参数。
    """
    kv = await offboarding_settings.load_offboarding_settings(db)
    base = offboarding_settings.sign_base_url(kv)
    return f"{base}?token={token}" if base else ""
