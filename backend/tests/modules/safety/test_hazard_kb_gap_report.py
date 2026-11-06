"""① KB 缺失清单脚本纯函数单测（P1-1 R3a，S4 接缝）—— 全合成数据。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "hazard_kb_gap_report.py"
)


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("hazard_kb_gap_report", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gap = _load_script()


def _snapshot(tmp_path: Path) -> Path:
    entries = [
        {  # 有标签、多路未命中 → 标签法规进缺失清单
            "record_id": "r1", "description": "提炼二部5#层析液罐，受限空间标识脱落",
            "source": "failure_57", "weak_labels": ["受限空间作业安全管理制度", "GB 30871"],
            "label_provenance": "聚类建议",
        },
        {  # 有标签、多路命中 → 不进缺失清单
            "record_id": "r2", "description": "罐区动火作业未办理作业票",
            "source": "failure_57", "weak_labels": ["已入库法规X"],
        },
        {  # 无标签 → 保洁类形态（非缺口）
            "record_id": "r3", "description": "学生楼6栋4层楼梯处堆放大量纸箱",
            "source": "failure_57", "weak_labels": [],
        },
    ]
    path = tmp_path / "snapshot.jsonl"
    path.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in entries), encoding="utf-8"
    )
    return path


def _dump(tmp_path: Path) -> Path:
    dump = {
        "baseline": [{"record_id": "r1", "hit": False, "docs": ["无关"]},
                     {"record_id": "r2", "hit": True, "docs": ["已入库法规X"]}],
        "multi": [{"record_id": "r1", "hit": False, "docs": ["无关"]},
                  {"record_id": "r2", "hit": True, "docs": ["已入库法规X"]}],
    }
    path = tmp_path / "dump.json"
    path.write_text(json.dumps(dump, ensure_ascii=False), encoding="utf-8")
    return path


class TestGapAnalysis:
    def test_missing_labels_collected_with_samples(self, tmp_path: Path) -> None:
        report = gap.build_gap_report(_snapshot(tmp_path), _dump(tmp_path))
        # 未命中的两条标签法规都进缺失清单
        assert "受限空间作业安全管理制度" in report
        assert "GB 30871" in report
        # 样本描述与「待业务复核」标注在清单里
        assert "受限空间标识脱落" in report
        assert "待业务复核" in report

    def test_hit_label_not_in_gap_list(self, tmp_path: Path) -> None:
        report = gap.build_gap_report(_snapshot(tmp_path), _dump(tmp_path))
        # 已入库命中的法规不进缺失清单（区分「缺法规」与「检索没找到」）
        assert "已入库法规X" not in report.split("## 保洁类")[0]

    def test_unlabeled_form_explained(self, tmp_path: Path) -> None:
        report = gap.build_gap_report(_snapshot(tmp_path), _dump(tmp_path))
        assert "保洁类" in report
        # 无标签条目不进缺失清单表格段（表格段 = 缺失清单标题与保洁类段之间）
        gap_table = report.split("## 缺失法规清单")[1].split("## 保洁类")[0]
        assert "堆放大量纸箱" not in gap_table
        # 无标签条目计数在保洁类段呈现
        housekeeping = report.split("## 保洁类")[1].split("## 与设计")[0]
        assert "共 1 条" in housekeeping

    def test_known_gaps_cross_checked(self, tmp_path: Path) -> None:
        report = gap.build_gap_report(_snapshot(tmp_path), _dump(tmp_path))
        # 与设计 §C12 已知缺口交叉核对段存在
        assert "设计 §C12" in report or "已知缺口" in report

    def test_dump_missing_treated_as_unhit(self, tmp_path: Path) -> None:
        """dump 缺某 record（评测未覆盖）→ 按未命中处理进缺失清单（保守）。"""
        snapshot = _snapshot(tmp_path)
        dump = tmp_path / "empty.json"
        dump.write_text(json.dumps({"baseline": [], "multi": []}), encoding="utf-8")
        report = gap.build_gap_report(snapshot, dump)
        assert "已入库法规X" in report  # r2 未被评测覆盖 → 保守进清单
