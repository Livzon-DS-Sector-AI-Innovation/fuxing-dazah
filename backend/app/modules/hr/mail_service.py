"""邮件发送服务 — 通过飞书 lark-cli 发送。无需 SMTP 配置。"""

import asyncio
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


async def _lark_send(to: str, subject: str, html_body: str, attachments: list[tuple[str, bytes]] | None = None, *, sender: str | None = None) -> bool:
    """调用 lark-cli mail +send 发邮件，支持附件。"""
    tmp_dir = Path(tempfile.mkdtemp(dir=Path(__file__).parent.parent.parent))
    body_file = tmp_dir / "body.html"
    body_file.write_text(html_body, encoding="utf-8")
    try:
        # lark-cli 要求 --body-file 和 --attach 必须是相对路径，所以用 cwd 切到临时目录
        cmd = ["lark-cli", "mail", "+send", "--as", "user",
               "--to", to, "--subject", subject,
               "--body-file", "body.html", "--confirm-send", "--format", "json"]
        if sender:
            cmd.extend(["--from", sender, "--mailbox", sender])

        # 附件：写入临时文件，使用文件名作为相对路径
        if attachments:
            attach_names = []
            for filename, content in attachments:
                fp = tmp_dir / filename
                fp.write_bytes(content)
                attach_names.append(filename)
            cmd.extend(["--attach", ",".join(attach_names)])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(tmp_dir),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            err_output = (stderr or b"").decode("utf-8", errors="ignore").strip()
            out_output = (stdout or b"").decode("utf-8", errors="ignore").strip()
            msg = err_output or out_output or "lark-cli 邮件发送失败"
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


async def send_email(
    *,
    to: str,
    subject: str,
    html_body: str,
    attachments: list[tuple[str, bytes]] | None = None,
    sender: str | None = None,
) -> bool:
    """发送邮件。走 lark-cli（无需 SMTP 配置）。成功返回 True，失败抛异常。

    attachments: 附件列表，每项为 (文件名, 文件内容bytes)。
    sender: 发件人邮箱，由调用方（业务模块）传入。
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "lark-cli", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode != 0:
            raise RuntimeError(f"lark-cli 不可用（退出码 {proc.returncode}），请检查安装")
    except FileNotFoundError:
        raise RuntimeError("lark-cli 未安装")
    return await _lark_send(to, subject, html_body, attachments, sender=sender)
