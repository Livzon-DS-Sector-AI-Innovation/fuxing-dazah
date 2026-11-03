"""qa 包导入面回归。

qa 模块按域拆成子包后，``api``/``scheduler`` 仍以 ``service.X`` 这种包属性方式
调用；任何子模块新增公开函数却忘记在包 ``__init__`` re-export，运行时才会
以 AttributeError 暴露（测试未覆盖的端点尤其如此）。这里用静态扫描兜底。
"""

from __future__ import annotations

import re
from pathlib import Path

import app.modules.qa.models as qa_models
import app.modules.qa.repository as qa_repository
import app.modules.qa.schemas as qa_schemas
import app.modules.qa.service as qa_service
from app.modules.qa.service import ai_analysis, deviation

QA_ROOT = Path(__file__).resolve().parents[3] / "app" / "modules" / "qa"

_DEF_RE = re.compile(r"^(?:class |def |async def )(\w+)")
_CONST_RE = re.compile(r"^([A-Z][A-Za-z0-9_]*) = ")


def _public_defs(path: Path) -> list[str]:
    names: list[str] = []
    for line in path.read_text().splitlines():
        match = _DEF_RE.match(line) or _CONST_RE.match(line)
        if match and not match.group(1).startswith("_"):
            names.append(match.group(1))
    return names


def test_api_and_scheduler_service_references_resolve() -> None:
    """api 子模块与 scheduler 里出现的 service.X / ai_analysis.X 都应是真实属性。"""
    sources = list((QA_ROOT / "api").glob("*.py")) + [QA_ROOT / "scheduler.py"]
    missing: list[str] = []
    for source in sources:
        text = source.read_text()
        # deviations.py 以 `from app.modules.qa.service import deviation as service` 引用子模块
        target = deviation if source.name == "deviations.py" else qa_service
        for name in sorted(set(re.findall(r"\bservice\.(\w+)", text))):
            if not hasattr(target, name):
                missing.append(f"{source.name}: service.{name}")
        for name in sorted(set(re.findall(r"\bai_analysis\.(\w+)", text))):
            if not hasattr(ai_analysis, name):
                missing.append(f"{source.name}: ai_analysis.{name}")
    assert not missing, f"包导入面缺失: {missing}"


def test_subpackages_reexport_all_public_definitions() -> None:
    """models/schemas/repository/service 的 __init__ 必须覆盖子模块全部公开定义。"""
    packages = {
        "models": qa_models,
        "schemas": qa_schemas,
        "repository": qa_repository,
        "service": qa_service,
    }
    missing: list[str] = []
    for pkg_name, module in packages.items():
        for sub in sorted((QA_ROOT / pkg_name).glob("*.py")):
            if sub.name.startswith("_"):
                continue
            if pkg_name == "service" and sub.name in ("ai_analysis.py", "deviation_ai.py"):
                # AI 分析/偏差 AI 辅助以整模块暴露（service.X），不逐名 re-export
                assert hasattr(module, sub.stem)
                continue
            for name in _public_defs(sub):
                if not hasattr(module, name):
                    missing.append(f"{pkg_name}/{sub.name}: {name}")
    assert not missing, f"__init__ 漏导出: {missing}"
