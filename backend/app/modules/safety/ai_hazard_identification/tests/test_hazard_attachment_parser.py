"""Ticket 05 — 脚本1 附件解析链路测试（HazardAttachmentParser）。

覆盖：URL/裸 token 下载路径、URL 下载失败回退文件 token、fixture 文档落盘解析、
下载失败/解析失败/空附件 → None、max_chars 传递。
使用 fake 下载客户端 + fake 文档解析器，无网络/无真实文档依赖。
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.modules.safety.service.hazard_attachment_parser import (
    HazardAttachmentParser,
)
from app.modules.safety.service.hazard_identification_bitable import (
    HazardIdentificationBitableService,
)

FIXTURE_TEXT = "岗位操作规程：发酵罐灭菌操作步骤……"


class _FakeClient:
    """记录调用并返回预设字节的 fake 下载客户端。"""

    def __init__(self, url_bytes=None, token_bytes=None, extra_bytes=None, drive_bytes=None, field_id="fldAttach01", docx_raw=None):
        self.url_bytes = url_bytes
        self.token_bytes = token_bytes
        self.extra_bytes = extra_bytes
        self.drive_bytes = drive_bytes
        self.field_id = field_id
        self.docx_raw = docx_raw
        self.url_calls: list[str] = []
        self.token_calls: list[str] = []
        self.extra_calls: list[tuple[str, str, str]] = []
        self.drive_calls: list[str] = []
        self.field_name_calls: list[str] = []
        self.docx_calls: list[str] = []

    async def download_attachment_from_url(self, url: str) -> bytes | None:
        self.url_calls.append(url)
        return self.url_bytes

    async def download_attachment(self, token: str, extra: str | None = None) -> bytes | None:
        self.token_calls.append(token)
        return self.token_bytes

    async def download_drive_file(self, token: str) -> bytes | None:
        self.drive_calls.append(token)
        return self.drive_bytes

    async def download_bitable_attachment(self, file_token, record_id, field_id) -> bytes | None:
        self.extra_calls.append((file_token, record_id, field_id))
        return self.extra_bytes

    async def get_field_id_by_name(self, field_name: str) -> str | None:
        self.field_name_calls.append(field_name)
        return self.field_id

    async def download_docx_raw(self, document_id: str) -> str | None:
        self.docx_calls.append(document_id)
        return self.docx_raw


class _ReadingDocParser:
    """fake 文档解析器：读取落盘文件，验证临时文件写路径。"""

    calls: list[tuple[str, int]] = []

    @classmethod
    def extract_text(cls, path: str, max_chars: int = 100000) -> str:
        cls.calls.append((path, max_chars))
        return Path(path).read_text(encoding="utf-8")


class _RaisingDocParser:
    @staticmethod
    def extract_text(path: str, max_chars: int = 100000) -> str:
        raise RuntimeError("文档解析失败")


@pytest.mark.asyncio
class TestHazardAttachmentParser:
    async def test_url_download_and_parse(self, tmp_path):
        fixture = tmp_path / "sop.txt"
        fixture.write_text(FIXTURE_TEXT, encoding="utf-8")
        client = _FakeClient(url_bytes=fixture.read_bytes())
        parser = HazardAttachmentParser(client, document_parser=_ReadingDocParser)

        text = await parser("https://xxx.feishu.cn/file/Token12345")

        assert text == FIXTURE_TEXT
        assert client.url_calls == ["https://xxx.feishu.cn/file/Token12345"]
        assert client.token_calls == []

    async def test_url_fallback_to_file_token(self):
        client = _FakeClient(url_bytes=None, token_bytes=FIXTURE_TEXT.encode())
        parser = HazardAttachmentParser(client, document_parser=_ReadingDocParser)

        text = await parser("https://xxx.feishu.cn/wiki/TokenA1B2C3D4")

        assert text == FIXTURE_TEXT
        assert client.token_calls == ["TokenA1B2C3D4"]

    async def test_url_with_query_token_extracted(self):
        client = _FakeClient(url_bytes=None, token_bytes=FIXTURE_TEXT.encode())
        parser = HazardAttachmentParser(client, document_parser=_ReadingDocParser)

        await parser("https://open.feishu.cn/drive/v1/medias/download?token=MediaXyZ1")

        assert client.token_calls == ["MediaXyZ1"]

    # ── 飞书云文档（/docx/ 链接）→ raw_content API ──

    async def test_docx_link_uses_raw_content(self):
        """`/docx/` 链接（岗位资料附件可粘贴云文档）→ 优先 raw_content API 返回纯文本。

        不再走 URL/Drive/media 字节下载，且跳过字节解析（docx 云文档非可下载文件）。
        """
        client = _FakeClient(
            url_bytes=None, token_bytes=None, drive_bytes=None,
            docx_raw="阿福合成缩合反应\n产前确认……",
        )
        parser = HazardAttachmentParser(client, document_parser=_ReadingDocParser)

        text = await parser(
            "https://j0eukrlohu.feishu.cn/docx/DoCxTokA1B2C3D4?from=from_copylink"
        )

        assert text == "阿福合成缩合反应\n产前确认……"
        assert client.docx_calls == ["DoCxTokA1B2C3D4"]
        assert client.url_calls == []
        assert client.token_calls == []
        assert client.drive_calls == []

    async def test_docx_link_in_bitable_context_uses_raw_content(self):
        """dict 上下文 + url 为 `/docx/` 链接 → 仍走 raw_content，不做 extra 下载。"""
        client = _FakeClient(
            extra_bytes=None, url_bytes=None, docx_raw="云文档纯文本",
        )
        parser = HazardAttachmentParser(client, document_parser=_ReadingDocParser)

        text = await parser({
            "url": "https://j0eukrlohu.feishu.cn/docx/DoCxTokA1B2C3D4?from=from_copylink",
            "record_id": "recXYZ",
            "field_name": "岗位资料附件（人工）",
        })

        assert text == "云文档纯文本"
        assert client.docx_calls == ["DoCxTokA1B2C3D4"]
        assert client.extra_calls == []

    async def test_docx_raw_failure_falls_back_to_url_download(self):
        """raw_content 返回 None（不可访问）→ 回退原 URL 下载路径。"""
        client = _FakeClient(
            url_bytes=FIXTURE_TEXT.encode(), token_bytes=None, docx_raw=None,
        )
        parser = HazardAttachmentParser(client, document_parser=_ReadingDocParser)

        text = await parser(
            "https://j0eukrlohu.feishu.cn/docx/DoCxTokA1B2C3D4?from=from_copylink"
        )

        assert text == FIXTURE_TEXT
        assert client.docx_calls == ["DoCxTokA1B2C3D4"]
        assert client.url_calls == [
            "https://j0eukrlohu.feishu.cn/docx/DoCxTokA1B2C3D4?from=from_copylink",
        ]

    async def test_non_docx_link_does_not_call_docx_api(self):
        """非 `/docx/` 链接（media/file/wiki）→ 不触发 raw_content。"""
        client = _FakeClient(url_bytes=FIXTURE_TEXT.encode(), docx_raw="不应被调用")
        parser = HazardAttachmentParser(client, document_parser=_ReadingDocParser)

        await parser("https://j0eukrlohu.feishu.cn/file/DrvTokA1B2C3D4")

        assert client.docx_calls == []

    # ── Bitable 附件上下文（extra 位权限定下载）──

    async def test_bitable_context_download_with_extra(self):
        """dict 上下文 → 解析 token + 按字段名解析 field_id → extra 下载。"""
        fixture = b"docx bytes"
        client = _FakeClient(extra_bytes=fixture)
        parser = HazardAttachmentParser(client, document_parser=_ReadingDocParser)

        text = await parser({
            "url": "https://open.feishu.cn/open-apis/drive/v1/medias/TokAbC123/download?token=TokAbC123",
            "record_id": "recXYZ",
            "field_name": "岗位资料附件（人工）",
        })

        assert text == fixture.decode()
        assert client.extra_calls == [("TokAbC123", "recXYZ", "fldAttach01")]
        assert client.field_name_calls == ["岗位资料附件（人工）"]
        assert client.url_calls == []

    async def test_bitable_context_field_id_cached(self):
        """field_id 惰性解析只调用一次（缓存）。"""
        client = _FakeClient(extra_bytes=b"bytes")
        parser = HazardAttachmentParser(client, document_parser=_ReadingDocParser)
        ctx = {
            "url": "https://open.feishu.cn/medias/TokAbC123/download?token=TokAbC123",
            "record_id": "recXYZ",
            "field_name": "岗位资料附件（人工）",
        }

        await parser(ctx)
        await parser(ctx)

        assert client.field_name_calls == ["岗位资料附件（人工）"]

    async def test_bitable_context_inline_field_id(self):
        """ctx 直接携带 field_id 时不走字段名解析。"""
        client = _FakeClient(extra_bytes=b"bytes")
        parser = HazardAttachmentParser(client, document_parser=_ReadingDocParser)

        await parser({
            "url": "https://open.feishu.cn/medias/TokAbC123/download?token=TokAbC123",
            "record_id": "recXYZ",
            "field_id": "fldDirect",
            "field_name": "岗位资料附件（人工）",
        })

        assert client.extra_calls == [("TokAbC123", "recXYZ", "fldDirect")]
        assert client.field_name_calls == []

    async def test_bitable_context_missing_field_id_falls_back_to_url(self):
        """字段名解析失败 → 回退 URL 直下。"""
        client = _FakeClient(url_bytes=FIXTURE_TEXT.encode(), field_id=None)
        parser = HazardAttachmentParser(client, document_parser=_ReadingDocParser)

        text = await parser({
            "url": "https://open.feishu.cn/medias/TokAbC123/download?token=TokAbC123",
            "record_id": "recXYZ",
            "field_name": "岗位资料附件（人工）",
        })

        assert text == FIXTURE_TEXT
        assert client.extra_calls == []
        assert client.url_calls == [
            "https://open.feishu.cn/medias/TokAbC123/download?token=TokAbC123",
        ]

    async def test_bitable_context_missing_record_id_falls_back_to_url(self):
        """缺 record_id（无法构建 extra）→ 回退 URL/裸 token 下载。"""
        client = _FakeClient(url_bytes=None, token_bytes=FIXTURE_TEXT.encode())
        parser = HazardAttachmentParser(client, document_parser=_ReadingDocParser)

        text = await parser({
            "url": "https://open.feishu.cn/medias/TokAbC123/download?token=TokAbC123",
            "field_name": "岗位资料附件（人工）",
        })

        assert text == FIXTURE_TEXT
        assert client.token_calls == ["TokAbC123"]
        assert client.extra_calls == []

    async def test_bitable_context_extra_download_fails_falls_back(self):
        """extra 下载失败 → 回退 URL 直下。"""
        client = _FakeClient(url_bytes=FIXTURE_TEXT.encode(), extra_bytes=None)
        parser = HazardAttachmentParser(client, document_parser=_ReadingDocParser)

        text = await parser({
            "url": "https://open.feishu.cn/medias/TokAbC123/download?token=TokAbC123",
            "record_id": "recXYZ",
            "field_name": "岗位资料附件（人工）",
        })

        assert text == FIXTURE_TEXT
        assert client.extra_calls == [("TokAbC123", "recXYZ", "fldAttach01")]
        assert client.url_calls == [
            "https://open.feishu.cn/medias/TokAbC123/download?token=TokAbC123",
        ]

    async def test_bitable_context_via_service_advance_record_with_record_id(self):
        """advance_record(fields, record_id=...) → 附件解析走 dict 上下文（extra）。"""
        fixture_bytes = b"docx bytes"
        client = _FakeClient(extra_bytes=fixture_bytes)
        parser = HazardAttachmentParser(client, document_parser=_ReadingDocParser)

        async def fake_run_script(script, effective):
            assert script == 1
            assert effective["attachment_text"] == fixture_bytes.decode()
            return SimpleNamespace(
                specific_activity="乙醇投料", equipment_facilities="乙醇罐",
                raw_auxiliary_materials="乙醇",
            )

        svc = HazardIdentificationBitableService(
            run_script=fake_run_script, attachment_parser=parser,
        )
        fields = {
            "AI流程节点进度": "待危险源信息AI提取",
            "岗位（人工）": "车间主操",
            "生产步骤（人工）": "乙醇配制投料",
            "岗位资料附件（人工）": {
                "link": "https://open.feishu.cn/open-apis/drive/v1/medias/TokAbC123/download?token=TokAbC123",
                "text": "岗位安全操作规程.docx",
            },
        }
        out = await svc.advance_record(fields, record_id="recXYZ")

        assert out["具体作业活动（AI）"] == "乙醇投料"
        assert client.extra_calls == [("TokAbC123", "recXYZ", "fldAttach01")]
        assert "AI流程节点进度" not in out  # RUN 不推进节点

    async def test_bare_token_download(self):
        client = _FakeClient(token_bytes=FIXTURE_TEXT.encode())
        parser = HazardAttachmentParser(client, document_parser=_ReadingDocParser)

        text = await parser("MediaXyZ1")

        assert text == FIXTURE_TEXT
        assert client.token_calls == ["MediaXyZ1"]
        assert client.url_calls == []

    # ── Drive 普通文件（file/ 链接）下载回退 ──

    async def test_drive_file_fallback_when_media_fails(self):
        """URL 是 file/ 链接（Drive 普通文件）→ media 下载失败时用 download_drive_file。"""
        client = _FakeClient(url_bytes=None, token_bytes=None, drive_bytes=FIXTURE_TEXT.encode())
        parser = HazardAttachmentParser(client, document_parser=_ReadingDocParser)

        text = await parser("https://j0eukrlohu.feishu.cn/file/DrvTokA1B2C3D4")

        assert text == FIXTURE_TEXT
        assert client.drive_calls == ["DrvTokA1B2C3D4"]
        # drive 成功 → 不再走 media download_attachment
        assert client.token_calls == []

    async def test_bare_token_prefers_drive_file(self):
        """裸 token：先尝试 Drive 普通文件（岗位资料附件 `file/` 存量），成功则不降级 media。"""
        client = _FakeClient(token_bytes=None, drive_bytes=FIXTURE_TEXT.encode())
        parser = HazardAttachmentParser(client, document_parser=_ReadingDocParser)

        text = await parser("DrvTokA1B2C3D4")

        assert text == FIXTURE_TEXT
        assert client.drive_calls == ["DrvTokA1B2C3D4"]
        assert client.token_calls == []

    async def test_drive_file_none_then_falls_back_to_media(self):
        """Drive 下载失败（返回 None）→ 降级到 Bitable media download_attachment。"""
        client = _FakeClient(token_bytes=FIXTURE_TEXT.encode(), drive_bytes=None)
        parser = HazardAttachmentParser(client, document_parser=_ReadingDocParser)

        text = await parser("DrvTokA1B2C3D4")

        assert text == FIXTURE_TEXT
        assert client.drive_calls == ["DrvTokA1B2C3D4"]
        assert client.token_calls == ["DrvTokA1B2C3D4"]

    async def test_drive_file_in_bitable_context_fallback(self):
        """dict 上下文 extra 下载失败 → 回退 URL → file/ 链接 Drive 直下。"""
        client = _FakeClient(
            url_bytes=None, token_bytes=None, extra_bytes=None,
            drive_bytes=FIXTURE_TEXT.encode(),
        )
        parser = HazardAttachmentParser(client, document_parser=_ReadingDocParser)

        text = await parser({
            "url": "https://j0eukrlohu.feishu.cn/file/DrvTokA1B2C3D4",
            "record_id": "recXYZ",
            "field_name": "岗位资料附件（人工）",
        })

        assert text == FIXTURE_TEXT
        assert client.extra_calls == [("DrvTokA1B2C3D4", "recXYZ", "fldAttach01")]
        assert client.drive_calls == ["DrvTokA1B2C3D4"]

    async def test_download_failure_returns_none(self):
        client = _FakeClient(url_bytes=None, token_bytes=None)
        parser = HazardAttachmentParser(client, document_parser=_ReadingDocParser)

        assert await parser("https://xxx.feishu.cn/wiki/TokenA1B2C3D4") is None
        assert await parser("BareToken12345") is None

    async def test_empty_source_returns_none(self):
        parser = HazardAttachmentParser(_FakeClient(), document_parser=_ReadingDocParser)
        assert await parser("") is None

    async def test_parse_failure_returns_none(self):
        client = _FakeClient(url_bytes=FIXTURE_TEXT.encode())
        parser = HazardAttachmentParser(client, document_parser=_RaisingDocParser)

        assert await parser("https://xxx.feishu.cn/file/Token12345") is None

    async def test_max_chars_passed_to_parser(self):
        fixture_bytes = FIXTURE_TEXT.encode()
        client = _FakeClient(url_bytes=fixture_bytes)
        parser = HazardAttachmentParser(
            client, document_parser=_ReadingDocParser, max_chars=12345,
        )

        await parser("https://xxx.feishu.cn/file/Token12345")

        assert _ReadingDocParser.calls[-1][1] == 12345

    async def test_default_document_parser_used_when_not_injected(self):
        # 不注入 document_parser → 惰性加载真实 SafetyDocumentParser（仅验证不抛异常）
        client = _FakeClient(url_bytes=b"dummy bytes not a real doc")
        parser = HazardAttachmentParser(client)
        # 真实解析器遇到非文档字节会抛 RuntimeError → 返回 None（不致命）
        assert await parser("https://xxx.feishu.cn/file/Token12345") is None

    async def test_integration_with_service_advance_record(self, tmp_path):
        """生产解析器接入 advance_record 脚本1 输入路径。"""
        fixture = tmp_path / "sop.txt"
        fixture.write_text(FIXTURE_TEXT, encoding="utf-8")
        client = _FakeClient(url_bytes=fixture.read_bytes())
        parser = HazardAttachmentParser(client, document_parser=_ReadingDocParser)

        async def fake_run_script(script, effective):
            assert script == 1
            assert effective["attachment_text"] == FIXTURE_TEXT
            return SimpleNamespace(
                specific_activity="人工投料", equipment_facilities="发酵罐",
                raw_auxiliary_materials="培养基",
            )

        svc = HazardIdentificationBitableService(
            run_script=fake_run_script, attachment_parser=parser,
        )
        fields = {
            "AI流程节点进度": "待危险源信息AI提取",
            "岗位（人工）": "发酵车间主操",
            "生产步骤（人工）": "发酵罐灭菌操作",
            "岗位资料附件（人工）": "https://xxx.feishu.cn/wiki/TokenA1B2C3D4",
        }
        out = await svc.advance_record(fields)
        assert out["具体作业活动（AI）"] == "人工投料"
        # RUN 不推进节点（审核驱动）：节点待脚本1审核通过后由对账推进
        assert "AI流程节点进度" not in out
