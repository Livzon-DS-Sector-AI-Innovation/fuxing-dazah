"""Ticket 07 — 全量镜像同步脚本逻辑 smoke 测试。

验证三阶段差异对齐（CREATE/UPDATE/DELETE）与编号派生，纯逻辑无 DB/无网络。
实际执行走 --dry-run（差异报告）与 --yes（写库），由人工在真实环境执行。
"""

import importlib.util
import pathlib

_SCRIPT_PATH = (
    pathlib.Path(__file__).resolve().parent.parent.parent.parent.parent.parent
    / "scripts" / "tmp" / "sync_hazard_id_bitable_to_platform.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("sync_hazard_id_script", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_derive_no():
    mod = _load_module()
    assert mod._derive_no("rec1234567890abcd") == "HI-34567890abcd"
    assert mod._derive_no("rec123456789012") == "HI-123456789012"


def test_compute_diff_all_three_phases():
    mod = _load_module()
    bitable = {"r1", "r2", "r3"}
    platform = {"r2", "r3", "r4"}
    to_create, to_update, to_delete = mod._compute_diff(bitable, platform)
    assert to_create == {"r1"}
    assert to_update == {"r2", "r3"}
    assert to_delete == {"r4"}


def test_compute_diff_empty_platform():
    mod = _load_module()
    bitable = {"r1", "r2"}
    to_create, to_update, to_delete = mod._compute_diff(bitable, set())
    assert to_create == {"r1", "r2"}
    assert to_update == set()
    assert to_delete == set()


def test_compute_diff_identical():
    mod = _load_module()
    bitable = {"r1", "r2"}
    to_create, to_update, to_delete = mod._compute_diff(bitable, set(bitable))
    assert to_create == set()
    assert to_update == set(bitable)
    assert to_delete == set()
