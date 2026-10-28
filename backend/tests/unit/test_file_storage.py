"""app/core/file_storage 通用上传校验与存储基座的单元测试。

这些函数由 qa 偏差附件与 feedback 截图共用；报错文案被 QA 现有测试与前端提示依赖，
抽取到 core 后必须与原 qa 实现保持一致。
"""

from __future__ import annotations

import io
from zipfile import ZipFile

import pytest

from app.core import file_storage
from app.core.exceptions import AppException

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
GIF = b"GIF89a" + b"\x00" * 16
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 16
PDF = b"%PDF-1.7\n%..."
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 8

IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
FIVE_MB = 5 * 1024 * 1024


def _zip_with(*members: str) -> bytes:
    buf = io.BytesIO()
    with ZipFile(buf, "w") as archive:
        for name in members:
            archive.writestr(name, b"x")
    return buf.getvalue()


class TestMagicMatches:
    @pytest.mark.parametrize(
        ("extension", "data"),
        [
            (".png", PNG),
            (".jpg", JPEG),
            (".jpeg", JPEG),
            (".gif", GIF),
            (".webp", WEBP),
            (".pdf", PDF),
            (".doc", OLE),
            (".xls", OLE),
            (".docx", _zip_with("[Content_Types].xml", "word/document.xml")),
            (".xlsx", _zip_with("[Content_Types].xml", "xl/workbook.xml")),
        ],
    )
    def test_accepts_matching_signature(self, extension: str, data: bytes) -> None:
        """每种允许类型的真实魔数都应判真。"""
        assert file_storage.magic_matches(extension, data) is True

    @pytest.mark.parametrize(
        ("extension", "data"),
        [
            (".png", JPEG),
            (".webp", b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 8),
            (".gif", b"GIF00a" + b"\x00" * 8),
            (".pdf", PNG),
            (".docx", _zip_with("[Content_Types].xml", "xl/workbook.xml")),
            (".xlsx", b"PK\x03\x04not-a-zip"),
            (".exe", b"MZ" + b"\x00" * 8),
        ],
    )
    def test_rejects_mismatch(self, extension: str, data: bytes) -> None:
        """内容与扩展名不符、损坏的 zip、未知扩展名一律判假。"""
        assert file_storage.magic_matches(extension, data) is False


class TestValidateUpload:
    def _validate(self, filename: str, data: bytes, **kw: object) -> tuple[str, str, str]:
        params: dict[str, object] = {
            "allowed": IMAGE_TYPES,
            "max_size": FIVE_MB,
            "kind_label": "PNG、JPG、WEBP、GIF",
        }
        params.update(kw)
        return file_storage.validate_upload(filename, data, **params)  # type: ignore[arg-type]

    def test_returns_safe_name_bare_extension_and_mime(self) -> None:
        """返回 (安全文件名, 不带点的扩展名, 按扩展名映射的 MIME)，与 qa 原契约一致。"""
        name, ext, mime = self._validate("../路径/我的 截图.PNG", PNG)
        assert name == "我的 截图.PNG"
        assert ext == "png"
        assert mime == "image/png"

    def test_rejects_disallowed_extension_with_kind_label(self) -> None:
        with pytest.raises(AppException) as exc:
            self._validate("说明.txt", b"hello")
        assert exc.value.status_code == 422
        assert exc.value.message == "仅支持 PNG、JPG、WEBP、GIF 附件"

    def test_rejects_empty(self) -> None:
        with pytest.raises(AppException) as exc:
            self._validate("空.png", b"")
        assert exc.value.message == "附件不能为空"

    @pytest.mark.parametrize(
        ("max_size", "label"),
        [(FIVE_MB, "5MB"), (20 * 1024 * 1024, "20MB")],
    )
    def test_size_message_derived_from_limit(self, max_size: int, label: str) -> None:
        """大小文案由上限推出：feedback 5MB、qa 20MB 都能复用同一实现。"""
        with pytest.raises(AppException) as exc:
            self._validate("大.png", PNG + b"\x00" * max_size, max_size=max_size)
        assert exc.value.message == f"附件大小不能超过 {label}"

    def test_rejects_magic_mismatch(self) -> None:
        with pytest.raises(AppException) as exc:
            self._validate("假的.png", JPEG)
        assert exc.value.message == "附件内容与扩展名不匹配或文件已损坏"

    def test_default_name_used_when_filename_missing(self) -> None:
        """无文件名时用调用方给的默认名，且仍按扩展名规则拒绝（默认名无扩展名）。"""
        with pytest.raises(AppException) as exc:
            self._validate("", PNG, default_name="screenshot")
        assert exc.value.message == "仅支持 PNG、JPG、WEBP、GIF 附件"


class TestKeysAndHeaders:
    @pytest.mark.parametrize("key", ["", "/abs/path.png", "\\win\\path.png", "a/../b.png"])
    def test_unsafe_keys_rejected(self, key: str) -> None:
        assert file_storage.is_safe_key(key) is False

    def test_safe_key_accepted(self) -> None:
        assert file_storage.is_safe_key("feedback/abc/def.png") is True

    def test_store_object_refuses_unsafe_key(self) -> None:
        with pytest.raises(ValueError):
            file_storage.store_object("feedback", "../escape.png", PNG, "image/png")

    def test_content_disposition_has_ascii_and_utf8_names(self) -> None:
        header = file_storage.content_disposition("inline", "截图 1.png")
        assert header.startswith("inline; filename=")
        assert "filename*=UTF-8''" in header

    @pytest.mark.parametrize(
        ("mime", "expected"),
        [
            ("image/png", "image/png"),
            ("IMAGE/JPEG; charset=binary", "image/jpeg"),
            ("application/pdf", "application/pdf"),
            ("text/html", None),
            ("image/svg+xml", None),
            (None, None),
        ],
    )
    def test_inline_media_type_whitelist(self, mime: str | None, expected: str | None) -> None:
        """HTML/SVG 一律不内联（API 域下的存储型 XSS），图片与 PDF 放行。"""
        assert file_storage.inline_media_type(mime) == expected
