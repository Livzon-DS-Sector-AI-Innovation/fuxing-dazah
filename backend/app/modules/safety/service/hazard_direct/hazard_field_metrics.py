"""P2-4 —— ①②⑤字段完整率 + 重大误判分层 纯函数（唯一事实源）。

口径（.scratch/hazard-p2-closeout/spec.md §4.1/4.2，2026-11-10 拍板）：

- **分母 = 各链已处理记录**：① = 分类（AI）非空（`COND_AI_PENDING` 反判据）；
  ② = AI初审结果非空；⑤ = 评分结果非空。
- **① 必填六列**：分类/级别/类别/描述/建议（AI）+ 督办等级。豁免边界：
  督办在 ③ 督办轮询开启时 ① 只算不写（B3 单写者）→ ``supervision_exempt``
  由扫描方传入并单列统计；判定依据（AI）仅 AI 级别 ∈ {较大, 重大} 必填
  （一般豁免 = 空转人工；级别不可归一时豁免并计数）。
- **重大误判以人工级别为真值**（多值取最高归一，复用
  ``field_authority.normalize_level_manual``）：L1 = AI 重大且人工非重大；
  L2 = 其余升格；L3 = 降格只列清单；任一侧空 → 跳过计数。

全部纯函数：吃 Bitable records（``record_id`` + ``fields`` dict），零 IO；
与 ``quality_metrics.py`` 同层同模式，供全表扫描脚本与后续看板复用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.modules.safety.service.hazard_direct import bitable_repo
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
    LEVEL_RANK,
    normalize_level_manual,
)

__all__ = [
    "CHAIN_AI",
    "CHAIN_REVIEW",
    "CHAIN_SCORING",
    "ColumnStat",
    "CompletenessStat",
    "MisjudgementRow",
    "MisjudgementLayers",
    "completeness_report",
    "misjudgement_layers",
]

CHAIN_AI = "ai_analysis"
CHAIN_REVIEW = "review"
CHAIN_SCORING = "scoring"

# 级别严重度序（field_authority.LEVEL_RANK 单一事实源：general < serious < major）
_RANK = LEVEL_RANK
_MAJOR = "major"

# ① 无条件必填列（督办/basis 为条件列，运行期判定）
_AI_ALWAYS_REQUIRED = (
    F_TYPE_AI,
    F_LEVEL_AI,
    F_CATEGORY_AI,
    F_DESC_AI,
    F_ADVICE_AI,
)


@dataclass
class ColumnStat:
    """单列完整率：必填格数 / 已填格数 / 缺值记录。"""

    name: str
    required_cells: int = 0
    filled_cells: int = 0
    missing_records: list[str] = field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.filled_cells / self.required_cells if self.required_cells else 1.0


@dataclass
class CompletenessStat:
    """单链完整率：分母（已处理记录数）+ 逐列统计 + 豁免计数。"""

    chain: str
    denominator: int = 0
    columns: dict[str, ColumnStat] = field(default_factory=dict)
    exempt: dict[str, int] = field(default_factory=dict)

    @property
    def required_total(self) -> int:
        return sum(c.required_cells for c in self.columns.values())

    @property
    def filled_total(self) -> int:
        return sum(c.filled_cells for c in self.columns.values())

    @property
    def overall_rate(self) -> float:
        total = self.required_total
        return self.filled_total / total if total else 1.0


@dataclass
class MisjudgementRow:
    """一条级别差异清单行（人工为真值）。"""

    record_id: str
    ai_level: str
    manual_level: str
    rectify_status: str = ""
    description: str = ""


@dataclass
class MisjudgementLayers:
    l1_fatal: list[MisjudgementRow] = field(default_factory=list)
    l2_upgrades: list[MisjudgementRow] = field(default_factory=list)
    l3_downgrades: list[MisjudgementRow] = field(default_factory=list)
    skipped_missing: int = 0
    agreed: int = 0


def _fields(record: dict[str, Any]) -> dict[str, Any]:
    raw = record.get("fields")
    return raw if isinstance(raw, dict) else {}


def _filled_text(fields: dict[str, Any], name: str) -> bool:
    return bool(bitable_repo.f_text(fields, name).strip())


def _filled_select(fields: dict[str, Any], name: str) -> bool:
    return bool(bitable_repo.f_select(fields, name).strip())


def _column(stat: CompletenessStat, name: str) -> ColumnStat:
    if name not in stat.columns:
        stat.columns[name] = ColumnStat(name=name)
    return stat.columns[name]


def _ai_required_columns(
    fields: dict[str, Any], *, supervision_exempt: bool, stat: CompletenessStat
) -> list[str]:
    """① 条件必填列集合（豁免计数挂 stat.exempt）。"""
    names = list(_AI_ALWAYS_REQUIRED)
    level = normalize_level_manual(bitable_repo.f_select(fields, F_LEVEL_AI))
    if level in ("serious", "major"):
        names.append(F_BASIS_AI)
    elif level == "general":
        stat.exempt["basis_general_level"] = stat.exempt.get("basis_general_level", 0) + 1
    else:  # 级别缺/不可归一 → 条件不可判，豁免并计数
        stat.exempt["basis_level_unknown"] = stat.exempt.get("basis_level_unknown", 0) + 1
    if supervision_exempt:
        stat.exempt["supervision_single_writer"] = (
            stat.exempt.get("supervision_single_writer", 0) + 1
        )
    else:
        names.append(F_SUPERVISION)
    return names


def completeness_report(
    records: list[dict[str, Any]], *, supervision_exempt: bool
) -> dict[str, CompletenessStat]:
    """①②⑤字段完整率（分母=各链已处理记录；条件豁免见模块头）。"""
    stats = {
        CHAIN_AI: CompletenessStat(chain=CHAIN_AI),
        CHAIN_REVIEW: CompletenessStat(chain=CHAIN_REVIEW),
        CHAIN_SCORING: CompletenessStat(chain=CHAIN_SCORING),
    }
    for record in records:
        fields = _fields(record)
        rid = str(record.get("record_id") or "")

        # ① 已处理 = 分类（AI）非空
        if _filled_select(fields, F_TYPE_AI):
            stats[CHAIN_AI].denominator += 1
            for name in _ai_required_columns(
                fields, supervision_exempt=supervision_exempt, stat=stats[CHAIN_AI]
            ):
                col = _column(stats[CHAIN_AI], name)
                col.required_cells += 1
                if _filled_text(fields, name) or _filled_select(fields, name):
                    col.filled_cells += 1
                else:
                    col.missing_records.append(rid)

        # ② 已处理 = AI初审结果非空；两列全必填
        if _filled_select(fields, F_REVIEW_RESULT):
            stats[CHAIN_REVIEW].denominator += 1
            for name in (F_REVIEW_RESULT, F_REVIEW_NOTE):
                col = _column(stats[CHAIN_REVIEW], name)
                col.required_cells += 1
                if _filled_text(fields, name) or _filled_select(fields, name):
                    col.filled_cells += 1
                else:
                    col.missing_records.append(rid)

        # ⑤ 已处理 = 评分结果非空；两列全必填（评分为数字列）
        if bitable_repo.f_number(fields, F_SCORE) is not None:
            stats[CHAIN_SCORING].denominator += 1
            col = _column(stats[CHAIN_SCORING], F_SCORE)
            col.required_cells += 1
            col.filled_cells += 1  # 分母判据本身非空
            note = _column(stats[CHAIN_SCORING], F_SCORING_NOTE)
            note.required_cells += 1
            if _filled_text(fields, F_SCORING_NOTE):
                note.filled_cells += 1
            else:
                note.missing_records.append(rid)

    return stats


def misjudgement_layers(records: list[dict[str, Any]]) -> MisjudgementLayers:
    """重大误判分层（人工多值取最高为真值；任一侧空跳过计数）。"""
    layers = MisjudgementLayers()
    for record in records:
        fields = _fields(record)
        ai = normalize_level_manual(bitable_repo.f_select(fields, F_LEVEL_AI))
        manual = normalize_level_manual(
            bitable_repo.f_select(fields, F_LEVEL_MANUAL)
        )
        if ai is None or manual is None:
            layers.skipped_missing += 1
            continue
        if ai == manual:
            layers.agreed += 1
            continue
        row = MisjudgementRow(
            record_id=str(record.get("record_id") or ""),
            ai_level=ai,
            manual_level=manual,
            rectify_status=bitable_repo.f_select(fields, F_RECTIFY_STATUS),
            description=bitable_repo.f_text(fields, F_DESC),
        )
        if _RANK[ai] > _RANK[manual]:
            (layers.l1_fatal if ai == _MAJOR else layers.l2_upgrades).append(row)
        else:
            layers.l3_downgrades.append(row)
    return layers
