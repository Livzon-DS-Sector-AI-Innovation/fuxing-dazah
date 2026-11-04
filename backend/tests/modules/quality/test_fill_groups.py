"""机器人填报分组去重（_unfilled_groups）纯函数测试。"""

import json
import uuid

from app.modules.quality.feishu.fill_service import _unfilled_groups
from app.modules.quality.models import QualityTestResult


def _row(item_name: str, sop_no: str, *, is_pass=None, judge_mode="auto",
         standard_text="≤3.0%", operator="≤", limit_max=3.0) -> QualityTestResult:
    r = QualityTestResult(
        task_id=uuid.uuid4(), item_name=item_name, sop_no=sop_no, standard_text=standard_text,
    )
    r.id = uuid.uuid4()
    r.judge_mode = judge_mode
    r.is_pass = is_pass
    r.operator = operator
    r.limit_min = None
    r.limit_max = limit_max
    r.source = "manual"
    return r


def _flatten(groups: tuple[list[dict], list[dict]]) -> list[dict]:
    bio, chem = groups
    return bio + chem


def test_same_sop_merged_into_one_entry():
    rows = [_row("水分", "SOP.03.1111"), _row("干燥失重", "SOP.03.1111")]
    out = _flatten(_unfilled_groups(rows))
    assert len(out) == 1
    assert "SOP.03.1111" in out[0]["label"]
    assert "水分" in out[0]["label"] and "干燥失重" in out[0]["label"]
    ids = json.loads(out[0]["map_value"])
    assert len(ids) == 2


def test_different_sop_stay_separate():
    rows = [_row("水分", "SOP.03.1111"), _row("酸度", "SOP.03.2222")]
    out = _flatten(_unfilled_groups(rows))
    assert len(out) == 2


def test_excludes_filled_manual_lc_and_defaults():
    rows = [
        _row("水分", "SOP.03.1111", is_pass=True),            # 已填 → 排除
        _row("性状", "SOP.03.3333", judge_mode="manual"),     # 文字型 → 排除
        _row("总杂质", "SOP.03.4444"),                        # 液相解析覆盖 → 排除
        _row("细菌内毒素", "SOP.03.5555"),                    # 默认规则 → 排除
        _row("酸度", "SOP.03.2222"),                          # 正常保留
    ]
    out = _flatten(_unfilled_groups(rows))
    assert len(out) == 1
    assert "酸度" in out[0]["label"]


def test_bio_chem_split():
    rows = [_row("需氧菌总数", "SOP.03.1111"), _row("水分", "SOP.03.2222")]
    bio, chem = _unfilled_groups(rows)
    assert len(bio) == 1 and "需氧菌总数" in bio[0]["label"]
    assert len(chem) == 1 and "水分" in chem[0]["label"]


def test_rows_without_sop_stay_individual():
    rows = [_row("水分", ""), _row("酸度", "")]
    out = _flatten(_unfilled_groups(rows))
    assert len(out) == 2
