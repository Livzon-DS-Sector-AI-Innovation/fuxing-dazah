"""字段口径静态扫描（P0-B B2 验收钉子 / R1-9）。

目的：证明「以 AI 值为权威口径」的读路径 = 0。行为测试（S1-S6）已逐条验证
human≠AI 时取人工值；本文件再做一层**静态防回归**：一旦某个下游模块退回
`v.hazard_level or v.hazard_level_manual` / `_match_level(v.hazard_level` 这类
AI 权威写法，测试立即失败。

扫描范围限定在 B2 指名的读口径模块（白名单），避免误伤 mirror/旧通道/写回路径。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_SAFETY_APP = Path(__file__).resolve().parents[3] / "app" / "modules" / "safety"

# (相对 safety/app 的路径, 禁止出现的表达式, 说明)
_FORBIDDEN_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (
        "service/hazard_direct/page_query.py",
        r"_match_level\(\s*v\.hazard_level\b",
        "页面筛选必须用 effective_level，不得用 AI 列 hazard_level",
    ),
    (
        "service/hazard_direct/page_query.py",
        r"\(v\.hazard_type or \"\"\)\s*==",
        "页面筛选必须用 effective_type，不得用 AI 列 hazard_type",
    ),
    (
        "service/hazard_direct/page_query.py",
        r"\(v\.hazard_category or \"\"\)\s*==",
        "页面筛选必须用 effective_category，不得用 AI 列 hazard_category",
    ),
    (
        "service/hazard_direct/hazard_scoring.py",
        r"hazard_level=view\.hazard_level\b",
        "⑤评分输入必须用 effective_level，不得用 AI 列 hazard_level",
    ),
    (
        "service/hazard_direct/hazard_scoring.py",
        r"hazard_type=view\.hazard_type\b",
        "⑤评分输入必须用 effective_type，不得用 AI 列 hazard_type",
    ),
    (
        "service/hazard_direct/hazard_scoring.py",
        r"hazard_category=view\.hazard_category\b",
        "⑤评分输入必须用 effective_category，不得用 AI 列 hazard_category",
    ),
    (
        "business_agent/tools/hazard_action_tools.py",
        r"v\.hazard_level\s+or\s+v\.hazard_level_manual",
        "导出等级列必须用 effective_level，不得 AI 优先",
    ),
    (
        "service/facility_map/service.py",
        r"v\.hazard_level\s+or\s+v\.hazard_level_manual",
        "风险分区图等级必须用 effective_level，不得 AI 优先",
    ),
    (
        "service/hazard_direct/bulletin.py",
        r"_level_label\(\s*view\.hazard_level_manual\s+or\s+view\.hazard_level",
        "④通报等级必须用 effective_level（统一读口径，禁止手工 or 回退）",
    ),
)

# (相对路径, 必须出现的读口径标记, 说明)
_REQUIRED_MARKERS: tuple[tuple[str, str, str], ...] = (
    ("service/hazard_direct/page_query.py", "effective_level", "页面筛选走 effective"),
    ("service/hazard_direct/hazard_scoring.py", "effective_level", "⑤评分走 effective"),
    ("service/hazard_direct/bulletin.py", "effective_level", "④通报走 effective"),
    (
        "business_agent/tools/hazard_action_tools.py",
        "effective_level",
        "导出走 effective",
    ),
    ("business_agent/tools/read_tools.py", "effective_level", "Agent 查询走 effective"),
    ("service/facility_map/service.py", "effective_level", "facility_map 走 effective"),
)


def _source(rel: str) -> str:
    path = _SAFETY_APP / rel
    assert path.is_file(), f"扫描目标不存在: {path}"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize(("rel", "pattern", "reason"), _FORBIDDEN_PATTERNS)
def test_no_ai_authority_read_path(rel: str, pattern: str, reason: str) -> None:
    source = _source(rel)
    assert re.search(pattern, source) is None, f"{rel}: {reason}"


@pytest.mark.parametrize(("rel", "marker", "reason"), _REQUIRED_MARKERS)
def test_downstream_uses_effective_marker(rel: str, marker: str, reason: str) -> None:
    source = _source(rel)
    assert marker in source, f"{rel}: {reason}（未找到 {marker}）"


def test_hazard_view_effective_fields_are_single_source() -> None:
    """数据层只允许 field_authority.resolve_effective 产出 effective_*。"""
    repo_source = _source("service/hazard_direct/bitable_repo.py")
    assert "fa.resolve_effective(" in repo_source
    # 禁止在 view/下游手工重算：effective_* 赋值只能来自 resolve 的返回值
    assert repo_source.count("effective_level=") == 1
    assert repo_source.count("effective_type=") == 1
    assert repo_source.count("effective_category=") == 1


_BACKEND_APP = Path(__file__).resolve().parents[3] / "app"


def test_main_lifespan_shutdown_closes_ai_singletons() -> None:
    """F7 接线钉子：进程 shutdown 必须关闭 AI 单例（close_all_ai_services）。"""
    source = (_BACKEND_APP / "main.py").read_text(encoding="utf-8")
    assert "close_all_ai_services" in source
    assert "await close_all_ai_services()" in source
    # 仅在 shutdown 段（yield 之后）调用，不能在启动段误关
    yield_pos = source.index("    yield\n")
    assert source.index("await close_all_ai_services()") > yield_pos


def test_no_legacy_event_channel_full_row_push_without_guard() -> None:
    """B5 钉子：EVENT_SYNC=true 时 push_hazard_to_bitable 必须拒绝整行回写。"""
    source = (
        Path(__file__).resolve().parents[3]
        / "app/modules/safety/feishu/bitable_handler.py"
    ).read_text(encoding="utf-8")
    assert "拒绝整行回写以防覆盖人工列" in source
    assert "if event_sync_enabled():" in source
