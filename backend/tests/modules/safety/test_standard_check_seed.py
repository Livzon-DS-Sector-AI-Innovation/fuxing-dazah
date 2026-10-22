"""标准清单 v1 种子数据完整性测试。

防「清单与注册表漂移」：自动项指标键必须在注册表、待接入键不在注册表、
枚举值与 schema 选项一致、编号唯一。这些是播种前最后一道闸。
"""

from __future__ import annotations

from app.modules.safety.service.standard_check import metrics as sc_metrics
from app.modules.safety.service.standard_check import seed_data


def test_55_standards_unique_nos() -> None:
    nos = [s["no"] for s in seed_data.STANDARDS]
    assert len(nos) == 55
    assert len(set(nos)) == 55
    # 要素分布（附录 A 分组计数）
    from collections import Counter

    counts = Counter(s["element"] for s in seed_data.STANDARDS)
    assert counts == {
        "目标职责": 8, "制度化管理": 6, "教育培训": 7, "现场管理": 13,
        "风险管控与隐患治理": 7, "应急管理": 8, "事故管理": 4, "持续改进": 2,
    }


PENDING_KEYS = [
    "accident.severe.count",
    "incident.near_miss_rate", "capa.on_time_close_rate",
]


def test_auto_metric_keys_all_registered() -> None:
    """清单指标键与注册表对齐（随票收紧）。

    T1 后：drill 3 键已注册；待接入键禁止注册（未接域误注册=假数据）。
    S6 接入（2026-10-22）后：training 两键已注册，待接入仅剩 incidents 3 键。
    """
    auto_keys = {s["metric_key"] for s in seed_data.STANDARDS if s["metric_key"]}
    unregistered = {k for k in auto_keys if sc_metrics.get_metric(k) is None}
    # 终态：除待接入键外全部注册
    assert unregistered == set(PENDING_KEYS), f"未注册键超出待接入清单: {sorted(unregistered)}"
    for key in PENDING_KEYS:
        assert key in auto_keys


def test_schema_covers_all_used_option_values() -> None:
    fields = {f["field_name"]: f for f in seed_data.table_schema()["table"]["fields"]}
    assert len(fields) == 15

    def options(name: str) -> set[str]:
        return {o["name"] for o in fields[name].get("property", {}).get("options", [])}

    for s in seed_data.STANDARDS:
        assert s["element"] in options("要素归属"), s["no"]
        assert s["period"] in options("周期"), s["no"]
        if s["metric_key"]:
            assert s["metric_key"] in options("指标键"), s["no"]
        if s["operator"]:
            assert s["operator"] in options("比较符"), s["no"]
        if s["unit"]:
            assert s["unit"] in options("单位"), s["no"]


def test_row_fields_shape() -> None:
    fields = seed_data.row_fields(seed_data.STANDARDS[0], year="2026")
    assert fields["标准编号"] == "D1-01"
    assert fields["年度"] == "2026"
    assert set(fields) == {
        "标准编号", "年度", "标准条款", "依据", "要素归属",
        "指标键", "比较符", "目标值", "单位", "周期", "备注",
    }
