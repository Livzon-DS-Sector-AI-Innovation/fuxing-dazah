"""MinerU 结果包解析：正文成员的选取契约。"""

from __future__ import annotations

import io
from zipfile import ZipFile

from app.modules.qa import mineru


def _zip(members: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_unzip_prefers_full_markdown_over_earlier_members() -> None:
    """ZIP 成员顺序不保证 full.md 在前。

    先到先得会把分页 md 之类的旁支当正文，之后每一段、每个 chunk、每次
    AI 抽取都跑在错的文本上。
    """

    artifacts, markdown, structured = mineru._unzip_artifacts(
        _zip({"zz_page1.md": "# PAGE ONE\n", "full.md": "# FULL DOC\n"})
    )

    assert markdown == "# FULL DOC\n"
    assert structured is None
    assert {item.source_name for item in artifacts} == {"zz_page1.md", "full.md"}


def test_unzip_falls_back_to_first_markdown_without_full_md() -> None:
    """结果包里没有 full.md 时，仍按第一个 markdown 成员兜底。"""

    _, markdown, _ = mineru._unzip_artifacts(_zip({"only.md": "# ONLY\n"}))

    assert markdown == "# ONLY\n"


def test_artifact_type_separates_images_from_generic_assets() -> None:
    """图片要单独成类，否则界面按后端原样显示英文 "asset"。"""

    assert mineru._artifact_type("abc.jpg") == "image"
    assert mineru._artifact_type("dir/ABC.PNG") == "image"
    assert mineru._artifact_type("full.md") == "markdown"
    assert mineru._artifact_type("page7.md") == "markdown"
    assert mineru._artifact_type("a_content_list.json") == "structure"
    assert mineru._artifact_type("origin.docx") == "asset"


def test_poll_interval_backs_off_after_the_fast_window() -> None:
    """前若干次按秒级跟进，之后退到慢档——预算按时间算，退避只决定打多少次。"""

    assert mineru.poll_interval(1) == mineru.MINERU_POLL_INTERVAL_SECONDS
    assert mineru.poll_interval(mineru.MINERU_FAST_POLL_COUNT) == (
        mineru.MINERU_POLL_INTERVAL_SECONDS
    )
    assert mineru.poll_interval(mineru.MINERU_FAST_POLL_COUNT + 1) == (
        mineru.MINERU_SLOW_POLL_INTERVAL_SECONDS
    )
