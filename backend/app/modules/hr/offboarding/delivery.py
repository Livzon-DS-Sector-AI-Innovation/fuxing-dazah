"""离职证明送达通道：邮件（现有 send_email）+ 短信（人工发送 + 登记）。

需求口径：离职办结后员工飞书账号随即注销，邮件 + 短信通知是主要送达入口；
发送时间、接收号码/邮箱与送达结果需留存。
2026-11-27 拍板：短信通道不接服务商，先做闭环——短信文案按模板生成交 HR 一键复制，
用手机或飞书发出后在本系统登记接收号码与发送时间（service.register_sms_sent）。
`send_certificate_sms` / `_send_via_provider` 保留为后续接入服务商的适配点，接入后只需把
service 层的登记动作换成调用它。
同日拍板：系统只部署在公司内网，员工在手机 / 外网打不开任何指向本系统的链接，
所以邮件与短信里都不带签署链接，只做通知；员工签字改为到人事办公室当面办理。
"""

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.mail_service import send_email
from app.modules.hr.models import EmailLog

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
) -> DeliveryResult:
    """离职证明邮件：PDF 附件；结果写 EmailLog 留痕。"""
    filename = f"解除劳动关系证明_{employee_name}.pdf"
    html = (
        f"<html><body style=\"font-family:sans-serif;padding:20px;\">"
        f"<h2>解除劳动关系证明</h2>"
        f"<p>{employee_name}，您好！</p>"
        f"<p>附件是您的解除劳动关系证明，请查收。</p>"
        f"</body></html>"
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
    contact: str,
) -> DeliveryResult:
    """离职证明短信通知（只告知已开具，不带链接）。通道未接入时返回 not_configured（不视为失败）。"""
    content = (
        f"【丽珠集团福兴医药】{employee_name}您好，您的解除劳动关系证明已开具，"
        f"请到人力资源部签收。如有疑问请联系{contact}。"
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
