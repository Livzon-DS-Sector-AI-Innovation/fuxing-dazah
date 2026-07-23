"""邮件发送服务 — 通过飞书 lark-cli 发送。无需 SMTP 配置。"""

import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def _lark_send(to: str, subject: str, html_body: str, attachments: list[tuple[str, bytes]] | None = None) -> bool:
    """调用 lark-cli mail +send 发邮件，支持附件。"""
    tmp_dir = Path(tempfile.mkdtemp(dir=Path(__file__).parent.parent.parent))
    body_file = tmp_dir / "body.html"
    body_file.write_text(html_body, encoding="utf-8")
    try:
        # lark-cli 要求 --body-file 和 --attach 必须是相对路径，所以用 cwd 切到临时目录
        cmd = ["lark-cli", "mail", "+send", "--as", "user",
               "--to", to, "--subject", subject,
               "--body-file", "body.html", "--confirm-send", "--format", "json"]
        try:
            from app.modules.hr.service import get_system_setting
            sender = get_system_setting("mail_sender")
            if sender and isinstance(sender, str):
                cmd.extend(["--from", sender, "--mailbox", sender])
        except Exception:
            pass

        # 附件：写入临时文件，使用文件名作为相对路径
        if attachments:
            attach_names = []
            for filename, content in attachments:
                fp = tmp_dir / filename
                fp.write_bytes(content)
                attach_names.append(filename)
            cmd.extend(["--attach", ",".join(attach_names)])

        result = subprocess.run(cmd,
            capture_output=True, text=True, timeout=30, cwd=str(tmp_dir),
        )
        if result.returncode != 0:
            msg = result.stderr.strip() or result.stdout.strip() or "lark-cli 邮件发送失败"
            raise Exception(msg)
        logger.info("邮件发送成功: to=%s attachments=%d", to, len(attachments or []))
        return True
    finally:
        # 清理临时文件
        for f in tmp_dir.glob("*"):
            try:
                f.unlink()
            except OSError:
                pass
        try:
            tmp_dir.rmdir()
        except OSError:
            pass


def send_email(
    *,
    to: str,
    subject: str,
    html_body: str,
    attachments: list[tuple[str, bytes]] | None = None,
) -> bool:
    """发送邮件。走 lark-cli（无需 SMTP 配置）。成功返回 True，失败抛异常。

    attachments: 附件列表，每项为 (文件名, 文件内容bytes)。
    """
    try:
        subprocess.run(["lark-cli", "--version"], capture_output=True, timeout=5, check=False)
    except FileNotFoundError:
        raise RuntimeError("lark-cli 未安装")
    return _lark_send(to, subject, html_body, attachments)
