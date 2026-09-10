"""飞书云文档 Block 构建工具。

将结构化 JSON 内容转换为飞书 Docx API 的 block dict 格式。
提取自 scripts/tmp/create_ai_intro_doc.py，作为可复用模块。

Block 类型参考：
  TEXT=2, HEADING1=3, HEADING2=4, HEADING3=5,
  BULLET=11, ORDERED=12, CODE=13, DIVIDER=22
"""

from __future__ import annotations

import re

# ── Block 类型常量 ──

BLOCK_TEXT = 2
BLOCK_HEADING1 = 3
BLOCK_HEADING2 = 4
BLOCK_HEADING3 = 5
BLOCK_BULLET = 11
BLOCK_ORDERED = 12
BLOCK_CODE = 13
BLOCK_DIVIDER = 22


# ── 基础 Block 构建 ──


def _text_run(content: str, *, bold: bool = False, inline_code: bool = False) -> dict:
    """构建单个 text_run 元素。"""
    run: dict = {"content": content, "text_element_style": {}}
    if bold:
        run["text_element_style"]["bold"] = True
    if inline_code:
        run["text_element_style"]["inline_code"] = True
    return run


def _text_element(content: str, *, bold: bool = False, inline_code: bool = False) -> dict:
    """构建包含单个 text_run 的 text_element。"""
    return {"text_run": _text_run(content, bold=bold, inline_code=inline_code)}


def _strip_formatting(text: str) -> str:
    """移除行内 markdown 格式，得到纯文本。"""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
    return text


def build_text_block(text: str) -> dict:
    """普通段落 block（统一纯文本，不做加粗/代码内联，保证字体一致）。"""
    return {
        "block_type": BLOCK_TEXT,
        "text": {"style": {}, "elements": [_text_element(_strip_formatting(text))]},
    }


def build_heading(text: str, level: int = 1) -> dict:
    """标题 block（level: 1/2/3）。"""
    clean = _strip_formatting(text)
    clean = re.sub(r"^#+\s*", "", clean)
    type_map = {1: BLOCK_HEADING1, 2: BLOCK_HEADING2, 3: BLOCK_HEADING3}
    prop_map = {1: "heading1", 2: "heading2", 3: "heading3"}
    return {
        "block_type": type_map[level],
        prop_map[level]: {"style": {}, "elements": [_text_element(clean)]},
    }


def build_divider() -> dict:
    """分割线 block。"""
    return {"block_type": BLOCK_DIVIDER, "divider": {}}


def build_bullet(text: str) -> dict:
    """无序列表（统一纯文本）。"""
    clean = re.sub(r"^[-*•]\s+", "", text)
    return build_text_block("• " + _strip_formatting(clean))


def build_ordered(text: str) -> dict:
    """有序列表 → 文本 block（children API 不直接支持 ordered 类型）。"""
    clean = re.sub(r"^\d+[\.\、）)]\s+", "", text)
    return build_text_block(_strip_formatting(clean))


# ── 演练方案 JSON → Blocks ──


def drill_plan_to_blocks(content_json: dict) -> list[dict]:
    """将 AI 生成的演练方案 JSON 转换为飞书文档 block 列表。

    映射规则：
      title           → H1 heading
      summary         → 引用风格 text
      元信息           → 小号 text + divider
      sections[i].heading → H2 heading
      sections[i].content → 逐行解析：数字. → ordered, - → bullet, 其他 → text
      空白行           → 跳过
    """
    blocks: list[dict] = []

    title = content_json.get("title") or ""
    summary = content_json.get("summary") or ""
    sections: list[dict] = content_json.get("sections") or []

    # 标题
    if title.strip():
        blocks.append(build_heading(title, level=1))

    # 摘要（引用风格）
    if summary.strip():
        blocks.append(build_text_block(f"📋 {summary}"))

    # 分隔
    blocks.append(build_divider())

    # 各节内容
    for sec in sections:
        heading = sec.get("heading", "")
        content = sec.get("content", "")

        if heading.strip():
            blocks.append(build_heading(heading, level=2))

        if content.strip():
            for line in content.split("\n"):
                stripped = line.strip()
                if not stripped:
                    continue
                # 检测有序列表（数字. 开头）
                if re.match(r"^\d+[\.\、）)]\s*", stripped):
                    blocks.append(build_ordered(stripped))
                # 检测无序列表（- 或 • 开头）
                elif re.match(r"^[-•]\s+", stripped):
                    blocks.append(build_bullet(stripped))
                # 角色信息行（冒号分隔的短行）
                elif re.match(r"^[一-鿿\w]+[：:]\s*", stripped) and len(stripped) < 60:
                    blocks.append(build_text_block(stripped))
                # 【场景】标记
                elif stripped.startswith("【") and "】" in stripped[:8]:
                    blocks.append(build_text_block(stripped))
                else:
                    blocks.append(build_text_block(stripped))

    return blocks
