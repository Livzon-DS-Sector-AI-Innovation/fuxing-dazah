"""底座 import 卫生：底座自身不得引入 ORM / AI / scheduler / 任何业务域包。

口径说明：本仓库的 app.modules.safety.service 是一个 eager 重包，
导入其任何子包都会触发父包的聚合导入，这是既有仓库属性（hazard_direct /
special_op_direct 同样如此），不由底座引入、也不在本次收敛范围内。
本测试保证的是**底座自身源码**的 import 图是干净的：
只允许标准库、自身、以及显式列出的少数基础设施模块。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent

# 允许的绝对导入前缀（新增一项都必须是有意识的决定）
ALLOWED_PREFIXES = (
    "app.modules.safety.service.bitable_direct",  # 自身
    "app.modules.safety.bitable_config",          # 连接配置中心（reader 使用）
    "app.modules.safety.feishu.bitable_client",   # Bitable 客户端（reader / writer 使用）
)

# 明令禁止（出现即失败）
BANNED_PREFIXES = (
    "app.modules.safety.models",
    "app.modules.safety.scheduler",
    "app.modules.safety.business_agent",
    "app.modules.safety.service.hazard_direct",
    "app.modules.safety.service.special_op_direct",
    "app.modules.safety.service.fire_alarm",
    "app.modules.safety.service.central_alarm",
    "app.modules.safety.service.chemical_inventory",
    "app.core",
    "app.shared",
    "app.platform",
    "sqlalchemy",
    "redis",
    "httpx",
    "lark_oapi",
)


def _base_modules() -> list[Path]:
    return sorted(
        p
        for p in BASE_DIR.rglob("*.py")
        if "tests" not in p.parts and "__pycache__" not in p.parts
    )


def _absolute_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            found.append(node.module or "")
    return found


def _is_stdlib(module: str) -> bool:
    root = module.split(".")[0]
    return root in sys.stdlib_module_names or root == "__future__"


def test_base_package_files_exist() -> None:
    names = {p.name for p in _base_modules()}
    assert "gates.py" in names
    assert "errors.py" in names


@pytest.mark.parametrize("path", _base_modules(), ids=lambda p: p.name)
def test_module_imports_are_allowed(path: Path) -> None:
    for module in _absolute_imports(path):
        if not module:
            continue
        assert not module.startswith(BANNED_PREFIXES), (
            f"{path.name} 引入了被禁依赖: {module}"
        )
        if _is_stdlib(module):
            continue
        assert module.startswith(ALLOWED_PREFIXES), (
            f"{path.name} 引入了未列入白名单的依赖: {module}；"
            "如确需引入，请显式扩展本测试的白名单并说明理由"
        )


def test_gates_module_only_uses_stdlib() -> None:
    gates = next(p for p in _base_modules() if p.name == "gates.py")
    for module in _absolute_imports(gates):
        assert _is_stdlib(module), f"gates.py 不应引入非标准库依赖: {module}"


class TestLazyPackageExports:
    def test_exported_names_resolve(self) -> None:
        from app.modules.safety.service import bitable_direct

        for name in bitable_direct.__all__:
            assert getattr(bitable_direct, name) is not None

    def test_unknown_attribute_raises(self) -> None:
        from app.modules.safety.service import bitable_direct

        with pytest.raises(AttributeError):
            _ = bitable_direct.definitely_not_a_real_export

    def test_dir_lists_exports(self) -> None:
        from app.modules.safety.service import bitable_direct

        assert set(bitable_direct.__dir__()) == set(bitable_direct.__all__)

    def test_lazy_export_is_same_object_as_gates_function(self) -> None:
        from app.modules.safety.service import bitable_direct
        from app.modules.safety.service.bitable_direct import gates

        assert bitable_direct.legacy_event_sync_active is gates.legacy_event_sync_active
