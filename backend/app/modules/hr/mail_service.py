"""邮件发送服务 — 通过 SMTP 直发，无需外部 CLI 工具。"""

import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def _get_smtp_config() -> dict[str, str | int]:
    """读取 SMTP 配置：优先从数据库（系统设置），回退到环境变量。"""
    settings = get_settings()
    db_config: dict[str, str] = {}
    try:
        from sqlalchemy import select
        from app.core.database import async_session_factory
        from app.modules.hr.models import SystemSetting
        async with async_session_factory() as session:
            r = await session.execute(
                select(SystemSetting).where(SystemSetting.key.like("smtp_%"))
            )
            db_config = {s.key: s.value for s in r.scalars().all()}
    except Exception:
        pass

    def get_val(key: str, env_val: str | int) -> str:
        return db_config.get(f"smtp_{key}") or str(env_val)

    return {
        "host": db_config.get("smtp_host") or settings.SMTP_HOST,
        "port": int(db_config.get("smtp_port") or settings.SMTP_PORT),
        "user": db_config.get("smtp_user") or settings.SMTP_USER,
        "password": db_config.get("smtp_password") or settings.SMTP_PASSWORD,
        "from_addr": db_config.get("smtp_from") or settings.SMTP_FROM,
        "from_name": db_config.get("smtp_from_name") or settings.SMTP_FROM_NAME,
    }


async def send_email(
    *,
    to: str,
    subject: str,
    html_body: str,
    attachments: list[tuple[str, bytes]] | None = None,
    sender: str | None = None,
) -> bool:
    """通过 SMTP 发送邮件。成功返回 True，失败抛异常。"""
    cfg = await _get_smtp_config()
    host = str(cfg["host"])
    port = int(cfg["port"])
    user = str(cfg["user"])
    password = str(cfg["password"])
    from_addr = sender or str(cfg["from_addr"])
    from_name = str(cfg["from_name"])

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
