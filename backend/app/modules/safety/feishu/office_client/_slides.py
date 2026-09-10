"""office_client 幻灯片（slides）资源方法及 XML 构造辅助。"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.modules.safety.feishu.office_client._base import OfficeResult

logger = logging.getLogger(__name__)


def _xml_escape(text: str) -> str:
    """转义 XML 特殊字符，避免标题/正文破坏 slide XML 结构。"""
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _coerce_slide_body(body: Any) -> list[str]:
    """把 body 字段归一化为非空行列表（str 多行 / list[str] / 其它标量）。"""
    if body is None:
        return []
    if isinstance(body, str):
        return [line.strip() for line in body.split("\n") if line.strip()]
    if isinstance(body, list):
        return [str(line).strip() for line in body if str(line).strip()]
    text = str(body).strip()
    return [text] if text else []


def _normalize_slide_content(content: Any) -> list[dict[str, Any]]:
    """把 create_slides 的 content 归一化为每页 {title, body} 结构。

    支持：
    - list[dict]：每页 {title, body?}，body 可为 str（多行）或 list[str]
    - str：markdown，# 标题开新页，其余行为正文；--- 分隔页
    空页会被过滤掉。
    """
    if content is None:
        return []

    if isinstance(content, str):
        pages: list[dict[str, Any]] = []
        current_title = ""
        current_lines: list[str] = []
        for raw in (content or "").split("\n"):
            line = raw.strip()
            if not line:
                continue

            heading = re.match(r"^#{1,3}\s+(.*)$", line)
            if heading:
                if current_title or current_lines:
                    pages.append({"title": current_title, "body": current_lines})
                current_title = heading.group(1).strip()
                current_lines = []
                continue

            if re.match(r"^(-{3,}|\*{3,}|_{3,})$", line):
                if current_title or current_lines:
                    pages.append({"title": current_title, "body": current_lines})
                current_title = ""
                current_lines = []
                continue

            current_lines.append(line)

        if current_title or current_lines:
            pages.append({"title": current_title, "body": current_lines})
        return pages

    if isinstance(content, list):
        pages = []
        for item in content:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            body = _coerce_slide_body(item.get("body"))
            if not title and not body:
                continue
            pages.append({"title": title, "body": body})
        return pages

    return []


def _build_slide_xml(title: str, body_lines: list[str]) -> str:
    """构造一页基础 slide XML（标题 + 正文/列表）。

    仅做“每页标题 + 正文”的基础写入；设计美化、图片、图表等由后续 ticket
    或前端模板完成。文本写入使用 slides_ai XML 协议。
    """
    parts: list[str] = [
        '<slide xmlns="https://www.larkoffice.com/sml/2.0">',
        "<data>",
    ]

    if title:
        parts.append(
            '<shape type="text" topLeftX="80" topLeftY="56" width="800" height="88">'
            '<content textType="title" fontSize="32" fontFamily="思源黑体" '
            'color="rgba(30, 60, 114, 1)" lineSpacing="multiple:1.2" '
            'wrap="true" autoFit="normal-auto-fit"><p>'
            + _xml_escape(title)
            + "</p></content></shape>"
        )

    bullets: list[str] = []
    paragraphs: list[str] = []
    for line in body_lines:
        if re.match(r"^[-*•]\s+", line):
            bullets.append(re.sub(r"^[-*•]\s+", "", line))
        else:
            paragraphs.append(line)

    if bullets or paragraphs:
        parts.append(
            '<shape type="text" topLeftX="80" topLeftY="180" width="800" height="300">'
            '<content textType="body" fontSize="18" fontFamily="思源黑体" '
            'color="rgba(43, 47, 54, 1)" lineSpacing="multiple:1.5" '
            'wrap="true" autoFit="normal-auto-fit">'
        )
        if bullets:
            parts.append("<ul>")
            for line in bullets:
                parts.append("<li><p>" + _xml_escape(line) + "</p></li>")
            parts.append("</ul>")
        for line in paragraphs:
            parts.append("<p>" + _xml_escape(line) + "</p>")
        parts.append("</content></shape>")

    parts.append("</data>")
    parts.append("</slide>")
    return "".join(parts)


class _SlidesOfficeMixin:
    """slides 创建与逐页写入。"""

    async def create_slides(
        self,
        title: str,
        *,
        folder_token: str | None = None,
        content: list[dict[str, Any]] | str | None = None,
        template: str | None = None,
    ) -> OfficeResult:
        """创建幻灯片（slides/v1/slides），可选逐页写入标题/正文内容。

        content 支持 list[dict]（每页 {title, body?}）或 markdown 字符串；
        为空时创建空白演示文稿并在 message 中说明。template 为可选模板 token，
        本期仅接受但不展开（模板导入需 drive import + slides 相关 scope）。
        """
        pages = _normalize_slide_content(content)
        try:
            body: dict[str, Any] = {"title": title}
            if folder_token:
                body["folder_token"] = folder_token

            if template:
                # 模板导入需补 scope：drive:drive / slides:presentation 等，
                # 本期不把 template 塞进创建 body，避免老创建接口参数不兼容。
                logger.info("create_slides template 参数本期未接入: %s", template)

            resp = await self._post(
                f"{self._base_url}/slides/v1/slides", json=body, timeout=60,
            )
            data = resp.json()

            if data.get("code") != 0:
                return OfficeResult.failure(
                    f"创建幻灯片失败：code={data.get('code')} "
                    f"msg={data.get('msg')}"
                )

            slides = (data.get("data") or {}).get("slides") or {}
            slides_token = (
                slides.get("token")
                or slides.get("slide_token")
                or slides.get("id")
                or ""
            )
            if not slides_token:
                return OfficeResult.failure("创建幻灯片成功但未返回 token")

            url = slides.get("url") or self._file_url(slides_token, "slides")
            result = OfficeResult.link(
                url, file_token=slides_token, message=f"已创建幻灯片《{title}》",
            )

            if not pages:
                result.message = f"已创建空白幻灯片《{title}》（未提供 content）"
                return result

            written = await self._write_slide_pages(
                slides_token, pages,
            )
            if written == 0:
                result.message = (
                    f"已创建幻灯片《{title}》，但内容页写入失败（0/{len(pages)}）；"
                    "请确认应用已开通 slides:presentation 写入 scope"
                )
            else:
                result.message = (
                    f"已创建幻灯片《{title}》并写入 {written} 页内容"
                )
            return result
        except Exception as exc:
            return self._failure("创建幻灯片", exc)

    async def _write_slide_pages(
        self,
        slides_token: str,
        pages: list[dict[str, Any]],
    ) -> int:
        """逐页调用 slides_ai XML 接口写入标题/正文，返回成功页数。

        页面写入失败仅告警并继续下一页；成功页数为 0 时由调用方决定提示方式。
        接口需 scope：slides:presentation:write_only / slides:presentation:update。
        """
        written = 0
        for page in pages:
            xml = _build_slide_xml(
                page.get("title") or "", page.get("body") or [],
            )
            try:
                resp = await self._post(
                    f"{self._base_url}/slides_ai/v1/xml_presentations/"
                    f"{slides_token}/slide",
                    params={"revision_id": -1},
                    json={"slide": {"content": xml}},
                    timeout=60,
                )
                data = resp.json()
            except Exception as exc:
                logger.warning("写入幻灯片页面异常: %s", exc)
                continue

            if data.get("code") == 0:
                written += 1
            else:
                logger.warning(
                    "写入幻灯片页面失败: code=%s msg=%s",
                    data.get("code"),
                    data.get("msg"),
                )
        return written
