"""仓储 Agent 技能注册表（S1 ticket 08，spec Implementation Decisions 6）。

``SkillRegistry`` 扫描本目录 ``*.md`` 三段式技能文件（frontmatter 触发描述 +
``## 步骤`` + ``## 输出格式``），提供：
- ``catalog_markdown()``：技能目录注入片段（一行一技能：``- 名称：触发描述``），
  由 ``prompts.build_system_prompt`` 注入「## 五、可用技能」段；
- ``load_skill(name)``：返回完整 SOP 正文（未知名返回错误信息字符串）；
- 文件 mtime 缓存：内容未变命中缓存，文件修改后自动重读（开发热更新），
  目录每次访问重新 glob（新增/删除技能即时生效）。

工具壳 ``load_skill``（与查询/计划/记忆/办公工具共用 ``tools/query.py`` 的
注册表）：返回 ``{"name", "description", "content"}``（SOP 全文，LLM 按
步骤编排其他工具）或 ``{"error": ...}``；无 ``_ctx`` 形参，不需要会话上下文。

模块级单例 ``default_registry``：首次访问时扫描目录（模块导入即就绪）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 技能文件所在目录（与 registry.py 同目录）
SKILL_DIR = Path(__file__).parent


@dataclass(frozen=True)
class SkillMeta:
    """技能元信息（frontmatter 触发描述，目录注入用）。"""

    name: str
    description: str


def parse_skill_file(text: str) -> tuple[dict[str, str], str]:
    """解析三段式技能文件：→ (frontmatter 键值对, 正文)。

    frontmatter 为首行 ``---`` 至闭合 ``---`` 之间的逐行 ``key: value``；
    无 frontmatter / 未闭合时整体视为正文（防御式，目录扫描不炸）。
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text.strip()
    meta: dict[str, str] = {}
    for idx in range(1, len(lines)):
        line = lines[idx]
        if line.strip() in ("---", "..."):
            return meta, "\n".join(lines[idx + 1:]).strip()
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    return {}, text.strip()  # frontmatter 未闭合，按正文处理


class SkillRegistry:
    """技能目录扫描器 + 文件 mtime 缓存（开发热更新）。"""

    def __init__(self, skill_dir: Path | None = None) -> None:
        self._dir = Path(skill_dir) if skill_dir is not None else SKILL_DIR
        # path -> (mtime, frontmatter, 正文)；mtime 变化即重读
        self._cache: dict[Path, tuple[float, dict[str, str], str]] = {}

    def _read_file(self, path: Path) -> tuple[dict[str, str], str]:
        """读单个技能文件（mtime 未变命中缓存）；IO 失败按空文件处理。"""
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return {}, ""
        cached = self._cache.get(path)
        if cached is not None and cached[0] == mtime:
            return cached[1], cached[2]
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return {}, ""
        meta, body = parse_skill_file(text)
        self._cache[path] = (mtime, meta, body)
        return meta, body

    def list_skills(self) -> list[SkillMeta]:
        """扫描目录返回全部有效技能（frontmatter 有 name 的文件）。"""
        skills: list[SkillMeta] = []
        for path in sorted(self._dir.glob("*.md")):
            meta, _body = self._read_file(path)
            name = str(meta.get("name") or "").strip()
            if name:
                skills.append(
                    SkillMeta(name=name, description=str(meta.get("description") or "").strip())
                )
        return skills

    def get_meta(self, name: str) -> SkillMeta | None:
        """按名取技能元信息；不存在返回 None。"""
        for skill in self.list_skills():
            if skill.name == name:
                return skill
        return None

    def catalog_markdown(self) -> str:
        """技能目录注入片段：一行一技能「- 名称：触发描述」。

        空目录返回空串（调用方据此省略「可用技能」段）。
        """
        lines = [
            f"- {skill.name}：{skill.description or '（未填写触发描述）'}"
            for skill in self.list_skills()
        ]
        return "\n".join(lines)

    def load_skill(self, name: str) -> str:
        """返回技能完整 SOP 正文（frontmatter 之后的部分）。

        未知名返回错误信息字符串（含可用技能列表），不抛异常。
        """
        for path in sorted(self._dir.glob("*.md")):
            meta, body = self._read_file(path)
            if str(meta.get("name") or "").strip() == name:
                return body
        available = "、".join(skill.name for skill in self.list_skills()) or "（无）"
        return f"未找到技能 {name!r}，可用技能: {available}"


# 模块级单例（启动即就绪：SKILL_DIR 下首批 2 技能随包发布）
default_registry = SkillRegistry()


# ── 工具壳（注册表入口，见 query.py 尾部合并）──


async def load_skill(name: str) -> dict[str, Any]:
    """加载技能完整 SOP（LLM 按步骤编排查询/计划/办公工具）。"""
    meta = default_registry.get_meta(name)
    if meta is None:
        return {"error": default_registry.load_skill(name)}
    return {
        "name": meta.name,
        "description": meta.description,
        "content": default_registry.load_skill(name),
        "message": (
            "已加载技能 SOP：请严格按「## 步骤」顺序执行（编排查询/计划/办公"
            "工具），并按「## 输出格式」产出报告；对外发送动作必须走 send_card "
            "确认门。"
        ),
    }


SKILL_TOOL_FUNCS: dict[str, Callable[..., Any]] = {
    "load_skill": load_skill,
}

SKILL_TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": (
                "加载业务技能的完整 SOP（标准操作流程）。当任务与系统提示词"
                "「可用技能」目录中某个技能的触发描述匹配时，先调用本工具加载"
                " SOP，再严格按其步骤执行、按其输出格式产出报告。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "技能名称（须与目录中列出的一致，如 dead-stock-analysis）",
                    },
                },
                "required": ["name"],
            },
        },
    },
]
