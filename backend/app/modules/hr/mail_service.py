"""邮件发送服务 — 通过 SMTP 直发，无需外部 CLI 工具。"""

import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def send_email(
    *,
    to: str,
    subject: str,
    html_body: str,
    attachments: list[tuple[str, bytes]] | None = None,
    sender: str | None = None,
    session = None,
) -> bool:
    """通过 SMTP 发送邮件。成功返回 True，失败抛异常。"""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.modules.hr.models import SystemSetting

    settings = get_settings()
    db_config: dict[str, str] = {}

    # 从传入的 session 或新建 session 读取 SMTP 配置
    if isinstance(session, AsyncSession):
        r = await session.execute(
            select(SystemSetting).where(SystemSetting.key.like("smtp_%"))
        )
        db_config = {s.key: s.value for s in r.scalars().all()}

    host = db_config.get("smtp_host") or settings.SMTP_HOST
    port = int(db_config.get("smtp_port") or settings.SMTP_PORT)
    user = db_config.get("smtp_user") or settings.SMTP_USER
    password = db_config.get("smtp_password") or settings.SMTP_PASSWORD
    from_addr = sender or db_config.get("smtp_from") or settings.SMTP_FROM
    from_name = db_config.get("smtp_from_name") or settings.SMTP_FROM_NAME

    if not host or not from_addr:
        raise RuntimeError("SMTP 未配置，请先在系统设置中填写邮件服务器信息")

    msg = MIMEMultipart()
    msg["From"] = formataddr((from_name, from_addr))
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if attachments:
        for filename, content in attachments:
            part = MIMEApplication(content, name=filename)
            part.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(part)

    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            server = smtplib.SMTP(host, port, timeout=30)
            server.starttls()
        if user and password:
            server.login(user, password)
        server.sendmail(from_addr, [to], msg.as_string())
        server.quit()
        logger.info("邮件发送成功: to=%s attachments=%d", to, len(attachments or []))
        return True
    except smtplib.SMTPException as e:
        raise RuntimeError(f"邮件发送失败: {e}") from e
