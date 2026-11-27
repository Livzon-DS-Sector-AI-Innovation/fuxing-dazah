"""液相加密计算表解密兜底逻辑测试。

服务端兜底密码（QUALITY_LC_EXCEL_PASSWORD）的核心约束：
未加密文件绝不消耗密码、兜底未配置时原样放行、显式密码错时明确报 422。
真实加密文件的解密链路由生产使用路径覆盖（msoffcrypto 不可逆构造加密样本）。
"""

import pytest
from fastapi import HTTPException

from app.core.config import get_settings
from app.modules.quality.api._lc import _decrypt_if_needed
from app.modules.quality.lc_template_parser import is_office_encrypted

# ── is_office_encrypted：非加密容器判定 ──


def test_encrypted_detect_zip_xlsx_is_not_encrypted() -> None:
    # zip 容器（xlsx）一定未加密
    assert is_office_encrypted(b"PK\x03\x04" + b"\x00" * 64) is False


def test_encrypted_detect_empty_and_junk() -> None:
    assert is_office_encrypted(b"") is False
    assert is_office_encrypted(b"\xd0\xcf\x11\xe0") is False  # 只有魔数、非合法 OLE
    assert is_office_encrypted(b"not an office file at all") is False


# ── _decrypt_if_needed：兜底密码行为 ──


def test_decrypt_passthrough_when_no_password_and_no_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "QUALITY_LC_EXCEL_PASSWORD", "")
    data = b"PK\x03\x04plain-xlsx-bytes"
    assert _decrypt_if_needed(data, None) is data


def test_decrypt_fallback_not_consumed_by_unencrypted_file(monkeypatch: pytest.MonkeyPatch) -> None:
    # 关键约束：兜底密码已配置，但未加密文件原样返回（不尝试解密）
    monkeypatch.setattr(get_settings(), "QUALITY_LC_EXCEL_PASSWORD", "server-side-secret")
    data = b"PK\x03\x04plain-xlsx-bytes"
    assert _decrypt_if_needed(data, None) is data


def test_decrypt_explicit_password_failure_raises_422() -> None:
    # 显式填了密码但文件无法解密（如未加密/密码错）→ 422 友好提示
    with pytest.raises(HTTPException) as exc_info:
        _decrypt_if_needed(b"PK\x03\x04plain-xlsx-bytes", "wrong-pass")
    assert exc_info.value.status_code == 422
    assert "解密失败" in exc_info.value.detail
