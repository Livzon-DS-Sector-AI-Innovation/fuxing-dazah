"""邮件服务测试：send_email + SMTP 配置编码"""

from email.header import Header

import pytest

from app.modules.hr.mail_service import _read_smtp_config, send_email


class TestSmtpConfig:
    @pytest.mark.asyncio
    async def test_read_empty_config_returns_dict(self, db_session):
        """无 SMTP 配置时返回空 dict"""
        from unittest.mock import AsyncMock

        cfg = await _read_smtp_config(db_session)
        assert isinstance(cfg, dict)

    @pytest.mark.asyncio
    async def test_send_email_empty_config_dict(self):
        """空配置 dict 时 send_email 抛 RuntimeError（host 为空）"""
        from unittest.mock import AsyncMock, patch

        with patch("app.modules.hr.mail_service._read_smtp_config", new_callable=AsyncMock) as mock_read:
            mock_read.return_value = {}
            with pytest.raises(RuntimeError, match="SMTP 未配置"):
                await send_email(
                    to="test@example.com",
                    subject="测试",
                    html_body="<p>测试</p>",
                    session=AsyncMock(),
                )


class TestEmailEncoding:
    def test_header_accepts_chinese_subject(self):
        """中文主题可正常传入 Header"""
        h = Header("入职 Offer — 工程师", "utf-8")
        # Header 接受中文，在 MIME 消息序列化时自动编码
        assert h is not None

    def test_header_accepts_chinese_name(self):
        """中文发件人名可正常传入 Header"""
        name = "丽珠集团福州福兴医药有限公司"
        h = Header(name, "utf-8")
        assert len(str(h)) > 0

    def test_mime_as_string_encodes_chinese(self):
        """MIME 邮件序列化时中文被正确编码"""
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.utils import formataddr

        msg = MIMEMultipart()
        msg["From"] = formataddr((str(Header("丽珠集团福州福兴医药有限公司", "utf-8")), "hr@livzon.cn"))
        msg["To"] = "test@example.com"
        msg["Subject"] = Header("入职 Offer — 操作工", "utf-8")
        msg.attach(MIMEText("<p>您好，请查收附件。</p>", "html", "utf-8"))

        raw = msg.as_string()
        # 中文 body 被 base64 编码，Subject 被 MIME 编码
        assert "=?utf-8?" in raw.lower() or "Content-Transfer-Encoding: base64" in raw
