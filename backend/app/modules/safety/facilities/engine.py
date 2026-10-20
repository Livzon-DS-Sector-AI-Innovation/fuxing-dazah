"""校验任务纯函数引擎（无 DB / 无 IO，today 可注入）。

照 CertWarningEngine 范式：到期筛选、分组键、类别归一、锚点前移判定全部
纯函数化，编排层（dispatch/closure）与单测共用同一口径，防两处漂移。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.modules.safety.facilities.ledger import (
    LedgerRowView,
    anchors_of_biz,
)

# ── 类别标签归一（分组键第一段）──────────────────────────────────────
# 已知类别关键词（命中即归一为该标签；未识别归「其他」桶，不因未知类别拆卡）
KNOWN_CATEGORY_LABELS: tuple[str, ...] = (
    "安全阀", "爆破片", "压力表", "灭火器", "消火栓", "消防栓",
    "锅炉", "压力容器", "呼吸器", "检测报警仪", "静电接地", "应急照明",
)


def category_label(category_raw: str | None) -> str:
    """类别原值 → 归一标签（包含匹配；空/未识别 → 其他）。"""
    raw = (category_raw or "").strip()
    if not raw:
        return "其他"
    for label in KNOWN_CATEGORY_LABELS:
        if label in raw:
            return label
    return "其他"


def group_key_of(department: str | None, label: str, subtype: str) -> str:
    """分组键 = 类别标签×工作性质（部门内分组标签；部门维度的批次卡另分层）。"""
    return f"{label}·{subtype}"


@dataclass(frozen=True)
class DueCandidate:
    """一条到期候选（视图行 × 命中锚点）。"""

    view: LedgerRowView
    anchor_field: str      # next_date / refill_due / scrap_due
    due_date: date        # = 锚点当前值（anchor_at_dispatch 同值快照）
    task_subtype: str     # 校验 / 检查 / 换药 / 报废更换 / 定期检验
    task_kind: str        # 任务文案

    @property
    def group_key(self) -> str:
        return group_key_of(
            self.view.department, category_label(self.view.category), self.task_subtype
        )


def select_due(
    views: list[LedgerRowView], today: date, lead_days: int
) -> list[DueCandidate]:
    """筛选到期候选：在用 + 可派（有编号有主锚点）+ 各锚点 ≤ 今日+lead_days。

    - 编号缺/主锚点缺的行不派任务（信息不全清单口径，页面与速递格子曝光）；
    - 消防特有锚点（换药/报废）独立判定，值缺则该锚点不出候选；
    - 已逾期（锚点 < 今日）同样命中（补派口径：没派过的照派，幂等键防重）。
    """
    horizon = today.fromordinal(today.toordinal() + lead_days)
    out: list[DueCandidate] = []
    for v in views:
        if not v.active or v.anchor is None or not v.equipment_no:
            continue
        for spec in anchors_of_biz(v.biz_type):
            value = v.anchor_value(spec.field)
            if value is None or value > horizon:
                continue
            out.append(
                DueCandidate(
                    view=v,
                    anchor_field=spec.field,
                    due_date=value,
                    task_subtype=spec.subtype,
                    task_kind=spec.task_kind,
                )
            )
    return out


def anchor_field_of_task(task) -> str:
    """任务 → 锚点字段（闭环判定取当前值的列；由 anchors_of_biz 反查派生，
    subtype→字段映射保持单事实源；duck typing 读 biz_type/task_subtype）。"""
    biz_type = getattr(task, "biz_type", "")
    subtype = getattr(task, "task_subtype", "")
    for spec in anchors_of_biz(biz_type):
        if spec.subtype == subtype:
            return spec.field
    return "next_date"


def anchor_advanced(
    *,
    due_date: date,
    issued_on: date,
    current_anchor: date | None,
    current_last: date | None,
    count_last_rule: bool = True,
) -> bool:
    """锚点前移判定（闭环铁律，纯函数）。

    closed 的前置条件是台账行锚点已前移，二者满足其一：
    1. 当前锚点（下次日期或其推算值；消防换药/报废任务为对应到期列）
       已滚动到新周期：current_anchor > 任务 due_date；
    2. 上次校验日期出现/更新为派发之后的新值：current_last ≥ issued_on
       （仅主锚点任务适用——消防换药/报废更换任务的闭环铁律是其**自身**
       到期列前移，更新「上次检查日期」不得连坐闭环锚点未动的换药/报废任务）。

    责任人只改无关列（名称/备注等）时两条件均不命中 → 保持 issued。
    """
    if current_anchor is not None and current_anchor > due_date:
        return True
    if count_last_rule and current_last is not None and current_last >= issued_on:
        return True
    return False
