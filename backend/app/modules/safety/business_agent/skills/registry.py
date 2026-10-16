"""安全业务 Agent 技能注册表（2-B SOP 技能化）。

照搬仓储 ``app/modules/warehouse/agent/skills/registry.py`` 模式：
``SkillRegistry`` 扫描本目录 ``*.md`` 三段式技能文件（frontmatter
name/description 触发描述 + ``## 步骤`` + ``## 输出格式``），提供：

- ``catalog_markdown()``：技能目录注入片段（一行一技能），由
  ``core/prompt.py::SkillCatalogSection`` 注入「可用技能」节；
- ``load_skill(name)``：返回完整 SOP 正文（未知名返回错误信息字符串）；
- 文件 mtime 缓存：内容未变命中缓存，文件修改后自动重读（热更新），
  目录每次访问重新 glob（新增/删除技能即时生效，无需重启）。

红线（本地化）：技能只编排既有工具、不引入新权限；涉及写操作必须走
既有确认流（requires_approval 挂起确认）；事实性数据必须来自工具结果。

模块级单例 ``default_registry``：首次访问时扫描目录。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic_ai import RunContext

from app.modules.safety.business_agent.schemas import SafetyDeps

# 技能文件所在目录（与 registry.py 同目录，随包发布）
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
    """技能目录扫描器 + 文件 mtime 缓存（热更新）。"""

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

        空目录返回空串（调用方据此省略「可用技能」节）。
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


# 模块级单例（技能 .md 文件随包发布，首批 4 个见 2-B 迁移）
default_registry = SkillRegistry()


# ── 工具壳（注册表入口，见 tools/registry.py 名册）──


async def load_skill(ctx: RunContext[SafetyDeps], name: str) -> dict[str, Any]:  # noqa: ARG001
    """加载技能完整 SOP（LLM 按步骤编排既有工具）。"""
    meta = default_registry.get_meta(name)
    if meta is None:
        return {"error": default_registry.load_skill(name)}
    return {
        "name": meta.name,
        "description": meta.description,
        "content": default_registry.load_skill(name),
        "message": (
            "已加载技能 SOP：请严格按「## 步骤」顺序执行（编排既有工具），"
            "并按「## 输出格式」产出；涉及写操作时按确认流程先复述、"
            "经用户确认后执行；所有事实性数据必须来自工具结果，禁止编造。"
        ),
    }


SKILL_TOOL_FUNCS: dict[str, Callable[..., Any]] = {
    "load_skill": load_skill,
}
