"""QA 权限码约定：固定三段 qa:<resource>:<action>，不使用 * 资源段。"""

import re
from pathlib import Path

from app.modules.qa.permissions import PERMISSIONS


def test_qa_permission_codes_follow_three_segment_convention() -> None:
    codes = [p.code for p in PERMISSIONS]
    assert len(codes) == len(set(codes)), "QA 权限码重复"
    for p in PERMISSIONS:
        assert "*" not in p.code, f"QA 权限码不使用通配资源: {p.code}"
        module, resource, action = p.code.split(":")
        assert module == "qa"
        assert p.resource == resource, f"resource 字段与码不一致: {p.code}"
        assert p.action == action, f"action 字段与码不一致: {p.code}"


def test_qa_permission_count_is_stable() -> None:
    assert len(PERMISSIONS) == 27


def test_deps_permission_codes_are_declared() -> None:
    deps = Path(__file__).resolve().parents[3] / "app/modules/qa/api/_deps.py"
    used = set(re.findall(r'"(qa:[a-z_]+:[a-z_]+)"', deps.read_text()))
    declared = {p.code for p in PERMISSIONS}
    assert used == declared, used ^ declared
