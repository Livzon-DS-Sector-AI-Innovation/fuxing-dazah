"""P2-4 T01 —— ①②⑤字段完整率+重大误判分层 纯函数单测。

口径（.scratch/hazard-p2-closeout/spec.md §4.1/4.2 拍板）：
- 分母=各链已处理（①=分类（AI）非空 / ②=AI初审结果非空 / ⑤=评分结果非空）；
- ①必填六列：分类/级别/类别/描述/建议（AI）+督办等级；督办在③开启时豁免
  单列统计；判定依据（AI）仅 AI 级别∈{较大,重大} 必填（一般豁免=空转人工）；
- 重大误判以人工级别（多值取最高）为真值：L1=AI重大且人工非重大；
  L2=AI>人工其余；L3=AI<人工只列清单；任一侧空→跳过并计数。

全部 fake：纯 dict 输入，零 IO。
"""

from __future__ import annotations

from app.modules.safety.service.hazard_direct import hazard_field_metrics as hfm
from app.modules.safety.service.hazard_direct.field_authority import (
    F_ADVICE_AI,
    F_BASIS_AI,
    F_CATEGORY_AI,
    F_DESC,
    F_DESC_AI,
    F_LEVEL_AI,
    F_LEVEL_MANUAL,
    F_RECTIFY_STATUS,
    F_REVIEW_NOTE,
    F_REVIEW_RESULT,
    F_SCORE,
    F_SCORING_NOTE,
    F_SUPERVISION,
    F_TYPE_AI,
)


def _rec(rid: str, **cols: object) -> dict:
    return {"record_id": rid, "fields": dict(cols)}


# ── 完整率 ──────────────────────────────────────────────────────


def test_chain_denominators() -> None:
    """分母判据：①看分类（AI）、②看初审结果、⑤看评分。"""
    records = [
        # ①已处理（分类AI非空）②未处理 ⑤未处理
        _rec("r1", **{F_TYPE_AI: "物的不安全状态"}),
        # ①未处理 ②已处理
        _rec("r2", **{F_REVIEW_RESULT: "已通过"}),
        # ⑤已处理
        _rec("r3", **{F_SCORE: 63.0}),
    ]
    report = hfm.completeness_report(records, supervision_exempt=True)
    assert report["ai_analysis"].denominator == 1
    assert report["review"].denominator == 1
    assert report["scoring"].denominator == 1


def test_ai_required_columns_and_empty_forms() -> None:
    """①必填列与空值形态（None/""/[] 均空；多选空列表不算填）。"""
    records = [
        _rec(
            "r1",
            **{
                F_TYPE_AI: "物的不安全状态",
                F_LEVEL_AI: "一般隐患",
                F_CATEGORY_AI: "设备设施",
                F_DESC_AI: "描述",
                F_ADVICE_AI: "建议",
                F_BASIS_AI: "",  # 一般级别 → basis 豁免
            },
        ),
        _rec(
            "r2",
            **{
                F_TYPE_AI: "管理缺陷",
                F_LEVEL_AI: None,  # 缺
                F_CATEGORY_AI: "",
                F_DESC_AI: "描述",
                F_ADVICE_AI: "建议",
            },
        ),
    ]
    report = hfm.completeness_report(records, supervision_exempt=True)
    ai = report["ai_analysis"]
    # r2 级别/类别缺 → 2 个缺格
    assert ai.columns[F_LEVEL_AI].missing_records == ["r2"]
    assert ai.columns[F_CATEGORY_AI].missing_records == ["r2"]
    # r1 basis 豁免（一般）→ 不在必填格
    assert F_BASIS_AI not in ai.columns or (
        ai.columns[F_BASIS_AI].required_cells == 0
    )
    assert ai.exempt["basis_general_level"] == 1
    # 总率 = 8 格必填（r1五列 + r2五列，督办豁免+basis全豁免）缺 2
    assert ai.required_total == 10
    assert ai.filled_total == 8
    assert ai.overall_rate == 0.8


def test_supervision_exempt_toggle() -> None:
    """督办豁免开关：exempt=False 时督办列计入必填。"""
    records = [
        _rec(
            "r1",
            **{
                F_TYPE_AI: "物的不安全状态",
                F_LEVEL_AI: "一般隐患",
                F_CATEGORY_AI: "设备设施",
                F_DESC_AI: "描述",
                F_ADVICE_AI: "建议",
                F_SUPERVISION: None,  # ③开时①不写 → 缺但被豁免
            },
        ),
    ]
    exempt_on = hfm.completeness_report(records, supervision_exempt=True)
    exempt_off = hfm.completeness_report(records, supervision_exempt=False)
    assert F_SUPERVISION not in exempt_on["ai_analysis"].columns
    sv = exempt_off["ai_analysis"].columns[F_SUPERVISION]
    assert sv.required_cells == 1 and sv.filled_cells == 0
    assert exempt_off["ai_analysis"].overall_rate == 5 / 6


def test_basis_required_for_serious_and_major() -> None:
    """basis 条件必填：较大/重大必填，一般豁免，级别不可归一时豁免并计数。"""
    records = [
        _rec("r1", **{F_TYPE_AI: "x", F_LEVEL_AI: "较大隐患"}),
        _rec("r2", **{F_TYPE_AI: "x", F_LEVEL_AI: "重大隐患"}),
        _rec("r3", **{F_TYPE_AI: "x", F_LEVEL_AI: "一般隐患"}),
        _rec("r4", **{F_TYPE_AI: "x", F_LEVEL_AI: "未知值"}),
    ]
    report = hfm.completeness_report(records, supervision_exempt=True)
    basis = report["ai_analysis"].columns[F_BASIS_AI]
    assert basis.required_cells == 2  # r1/r2 必填（均空 → 均缺）
    assert basis.missing_records == ["r1", "r2"]
    assert report["ai_analysis"].exempt["basis_general_level"] == 1
    assert report["ai_analysis"].exempt["basis_level_unknown"] == 1


def test_review_and_scoring_two_columns() -> None:
    """②⑤各两列全必填；评分空值=None。"""
    records = [
        _rec("r1", **{F_REVIEW_RESULT: "已通过", F_REVIEW_NOTE: "说明"}),
        _rec("r2", **{F_REVIEW_RESULT: "未通过"}),  # 说明缺
        _rec("r3", **{F_SCORE: 63.0, F_SCORING_NOTE: "LEC"}),
        _rec("r4", **{F_SCORE: 63.0}),  # 说明缺
    ]
    report = hfm.completeness_report(records, supervision_exempt=True)
    rv = report["review"]
    assert rv.denominator == 2
    assert rv.columns[F_REVIEW_NOTE].missing_records == ["r2"]
    sc = report["scoring"]
    assert sc.denominator == 2
    assert sc.columns[F_SCORING_NOTE].missing_records == ["r4"]


# ── 重大误判分层 ────────────────────────────────────────────────


def test_misjudgement_layers() -> None:
    """L1=AI重大且人工非重大；L2=其余升格；L3=降格；一致不计。"""
    records = [
        _rec("l1a", **{F_LEVEL_AI: "重大隐患", F_LEVEL_MANUAL: "一般隐患"}),
        _rec("l1b", **{F_LEVEL_AI: "重大隐患", F_LEVEL_MANUAL: "较大隐患"}),
        _rec("l2a", **{F_LEVEL_AI: "较大隐患", F_LEVEL_MANUAL: "一般隐患"}),
        _rec("l3a", **{F_LEVEL_AI: "一般隐患", F_LEVEL_MANUAL: "较大隐患"}),
        _rec("same", **{F_LEVEL_AI: "重大隐患", F_LEVEL_MANUAL: "重大隐患"}),
    ]
    layers = hfm.misjudgement_layers(records)
    assert [row.record_id for row in layers.l1_fatal] == ["l1a", "l1b"]
    assert [row.record_id for row in layers.l2_upgrades] == ["l2a"]
    assert [row.record_id for row in layers.l3_downgrades] == ["l3a"]


def test_misjudgement_manual_multivalue_and_skips() -> None:
    """人工多值取最高归一；任一侧空→跳过计数。"""
    records = [
        # 人工多值「较大, 一般」→ serious；AI general → 降格
        _rec("multi", **{F_LEVEL_AI: "一般隐患", F_LEVEL_MANUAL: ["较大隐患", "一般隐患"]}),
        _rec("noai", **{F_LEVEL_MANUAL: "一般隐患"}),
        _rec("nomanual", **{F_LEVEL_AI: "重大隐患"}),
    ]
    layers = hfm.misjudgement_layers(records)
    assert [row.record_id for row in layers.l3_downgrades] == ["multi"]
    assert layers.skipped_missing == 2


def test_misjudgement_row_payload() -> None:
    """清单行携带 record_id/AI值/人工值/整改状态/描述摘要。"""
    records = [
        _rec(
            "l1a",
            **{
                F_LEVEL_AI: "重大隐患",
                F_LEVEL_MANUAL: "一般隐患",
                F_RECTIFY_STATUS: "未关闭",
                F_DESC: "配电箱未上锁",
            },
        ),
    ]
    row = hfm.misjudgement_layers(records).l1_fatal[0]
    assert row.record_id == "l1a"
    assert row.ai_level == "major"
    assert row.manual_level == "general"
    assert row.rectify_status == "未关闭"
    assert row.description == "配电箱未上锁"
