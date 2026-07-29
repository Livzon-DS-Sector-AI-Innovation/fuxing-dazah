"""邮件发送服务 — 通过 SMTP 直发，配置完全收敛在 HR 模块内。"""

import logging
import smtplib
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

logger = logging.getLogger(__name__)


async def _read_smtp_config(session) -> dict[str, str]:
    """从数据库 system_settings 表读取 SMTP 配置。"""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.modules.hr.models import SystemSetting

    db_config: dict[str, str] = {}
    if isinstance(session, AsyncSession):
        r = await session.execute(
            select(SystemSetting).where(SystemSetting.key.like("smtp_%"))
        )
        db_config = {s.key: s.value for s in r.scalars().all()}
    return db_config


async def send_email(
    *,
    to: str,
    subject: str,
    html_body: str,
    attachments: list[tuple[str, bytes]] | None = None,
    sender: str | None = None,
    session = None,
) -> bool:
    """通过 SMTP 发送邮件。配置从 HR 系统设置页面保存，完全收敛在 HR 模块内。"""
    cfg = await _read_smtp_config(session)

    host = cfg.get("smtp_host", "")
    port = int(cfg.get("smtp_port", "587"))
    user = cfg.get("smtp_user", "")
    password = cfg.get("smtp_password", "")
    from_addr = sender or cfg.get("smtp_from", "")
    from_name = cfg.get("smtp_from_name", "丽珠集团福州福兴医药有限公司")

    if not host or not from_addr:
        raise RuntimeError("SMTP 未配置，请先在系统设置中填写邮件服务器信息")

    msg = MIMEMultipart()
    msg["From"] = formataddr((str(Header(from_name, "utf-8")), from_addr))
    msg["To"] = to
    msg["Subject"] = Header(subject, "utf-8")
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if attachments:
        for filename, content in attachments:
            part = MIMEApplication(content, name=("utf-8", "", filename))
            part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", filename))
            msg.attach(part)

    import asyncio
    loop = asyncio.get_running_loop()

    def _send():
        server = None
        try:
            if port == 465:
                server = smtplib.SMTP_SSL(host, port, timeout=30)
            else:
                server = smtplib.SMTP(host, port, timeout=30)
                server.starttls()
            if user and password:
                server.login(user, password)
            server.sendmail(from_addr, [to], msg.as_string())
        finally:
            if server:
                try:
                    server.quit()
                except Exception:
                    pass  # 关闭连接失败不掩盖原始异常

    try:
        await loop.run_in_executor(None, _send)
        logger.info("邮件发送成功: to=%s attachments=%d", to, len(attachments or []))
        return True
    except Exception as e:
        raise RuntimeError(f"邮件发送失败: {e}") from e
