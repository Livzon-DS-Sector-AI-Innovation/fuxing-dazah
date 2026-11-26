"""清退会签明细：默认清单落库 + 飞书清退交接实例表单回读（方案 §3.4）。

平台清退单是工作数据源：进入清退阶段先落一份四部门默认清单（需求「多部门会签」
列明的事项），HR 在办理抽屉逐项确认；飞书清退交接实例办结后再按控件名约定回读。

控件名约定（人事在清退交接审批定义里按名称建控件；缺失不报错，HR 手工登记兜底）：
- 每部门一个多行文本控件，一行一条清退事项，竖线分隔，后四段可省：
      事项名称｜状态｜扣款｜补发｜备注
  状态写法：已清退 / 有扣补 / 待确认（不写按已清退）；金额单位元，
  写了金额即记为「有扣补」。「无扣款」「没有补发」这类否定写法不算扣补。
- 可选数字控件「<部门>扣款金额」「<部门>补发金额」：该部门文本控件无明细时
  汇总成一条「扣补结算」。

回读只替换 source=feishu_form 的行，并撤掉该部门尚未动过的默认行（seed）；
HR 手工登记/确认过的行（manual）不动。
"""

import logging
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.offboarding import repository as repo
from app.modules.hr.offboarding.models import OffboardingCase, OffboardingClearanceItem

logger = logging.getLogger(__name__)

CATEGORY_ORDER: tuple[str, ...] = (
    OffboardingClearanceItem.CATEGORY_ADMIN,
    OffboardingClearanceItem.CATEGORY_FINANCE,
    OffboardingClearanceItem.CATEGORY_HR,
    OffboardingClearanceItem.CATEGORY_WORK,
)
# 控件名里的部门简称（「行政后勤清退事项」「财务扣款金额」……）
_WIDGET_DEPT = {
    "admin": "行政后勤", "finance": "财务", "hr": "人力资源", "work": "工作部门",
}
# 需求「多部门会签」列明的清退事项，进入清退阶段时作为默认清单落库
DEFAULT_ITEMS: dict[str, tuple[str, ...]] = {
    "admin": ("宿舍钥匙", "个人物品", "餐卡", "车辆通行证"),
    "finance": ("电脑", "借款", "U盘"),
    "hr": ("工号牌", "社保医保", "培训费"),
    "work": ("业务往来",),
}

# 状态写法 → 清退状态。待办/扣补词优先于「已清退」（「已清退，有扣补」应记为有扣补）
_STATUS_WORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("待确认", "未完成", "未清退", "待办", "未交接"), OffboardingClearanceItem.STATUS_PENDING),
    (("有扣补", "扣补", "扣款", "补发", "罚款", "赔偿"), OffboardingClearanceItem.STATUS_DEDUCTED),
    (("已清退", "已完成", "已确认", "已交接", "确认", "无"), OffboardingClearanceItem.STATUS_CONFIRMED),
)
# 否定掉的扣补说法（「已清退，无扣款」）先整体剔除，否则会被「扣款」命中成有扣补
_NEGATED_DEDUCTION = re.compile(r"(?:无|没有|未|不)(?:扣补|扣款|补发|罚款|赔偿)")
_LINE_SPLIT = re.compile(r"[|｜\t]")
_AMOUNT_STRIP = re.compile(r"[￥¥,\s元]")


def staggered_timestamps(count: int) -> list[datetime]:
    """一批行按录入顺序排的 created_at。

    同一事务里插入的多行，created_at 的默认值 now() 是事务开始时间、完全相同，
    按时间排序等于没排（实测回读顺序会乱）。逐行加 1 微秒偏移，列表按 created_at
    排序即等于录入顺序。
    """
    base = datetime.now(UTC)
    return [base + timedelta(microseconds=offset) for offset in range(count)]


def in_entry_order(rows: list[OffboardingClearanceItem]) -> list[OffboardingClearanceItem]:
    for row, stamp in zip(rows, staggered_timestamps(len(rows)), strict=True):
        row.created_at = stamp
    return rows


async def seed_default_items(db: AsyncSession, case: OffboardingCase) -> int:
    """进入清退阶段时落默认清单；已有明细（重复推进/回读先到）则不动。"""
    if await repo.list_clearance_items(db, case.id):
        return 0
    rows = [
        OffboardingClearanceItem(
            case_id=case.id, category=category, item_name=item_name,
            status=OffboardingClearanceItem.STATUS_PENDING,
            source=OffboardingClearanceItem.SOURCE_SEED,
        )
        for category in CATEGORY_ORDER
        for item_name in DEFAULT_ITEMS[category]
    ]
    db.add_all(in_entry_order(rows))
    await db.flush()
    return len(rows)


def _plain_text(raw: Any) -> str:
    """控件值 → 纯文本：字符串原样；富文本是 [{text,type}] 段落列表，拼接 text。"""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        # 富文本控件返回段落片段列表，换行自带在片段里：直接拼接，不能自行插换行
        # （否则「钥匙｜已清退」会被拆成两条）
        return "".join(
            seg.get("text", "") if isinstance(seg, dict) else str(seg) for seg in raw
        )
    return str(raw)


def _match_status(text: str) -> str | None:
    compact = _NEGATED_DEDUCTION.sub("", text.replace(" ", ""))
    for words, status in _STATUS_WORDS:
        if any(word in compact for word in words):
            return status
    return None


def _to_amount(text: str) -> Decimal | None:
    """「￥1,200.50 元」→ Decimal；不是金额返回 None。"""
    cleaned = _AMOUNT_STRIP.sub("", text)
    if not cleaned:
        return None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return value if value >= 0 else None


def parse_items(raw: Any, category: str) -> list[dict[str, Any]]:
    """多行文本控件 → 清退明细行（见模块 docstring 的行格式约定）。"""
    items: list[dict[str, Any]] = []
    for line in _plain_text(raw).splitlines():
        line = line.strip().lstrip("-•·*　").strip()
        if not line:
            continue
        parts = [p.strip() for p in _LINE_SPLIT.split(line)]
        item_name = parts[0]
        if not item_name:
            continue
        rest = parts[1:]
        status = OffboardingClearanceItem.STATUS_CONFIRMED
        if rest:
            matched = _match_status(rest[0])
            if matched:
                status = matched
                rest = rest[1:]
        deduction = supplement = None
        amounts: list[Decimal] = []
        for seg in rest:
            value = _to_amount(seg)
            if value is None:
                break
            amounts.append(value)
        if amounts:
            deduction, *extra = amounts
            supplement = extra[0] if extra else None
            status = OffboardingClearanceItem.STATUS_DEDUCTED
        remark = " ".join(rest[len(amounts):]).strip() or None
        items.append({
            "category": category,
            "item_name": item_name[:64],
            "status": status,
            "deduction_amount": deduction,
            "supplement_amount": supplement,
            "remark": remark[:255] if remark else None,
        })
    return items


def _build_rows(fields: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for category in CATEGORY_ORDER:
        dept = _WIDGET_DEPT[category]
        items = parse_items(fields.get(f"{dept}清退事项"), category)
        if not items:
            deduction = _to_amount(_plain_text(fields.get(f"{dept}扣款金额")))
            supplement = _to_amount(_plain_text(fields.get(f"{dept}补发金额")))
            if deduction is not None or supplement is not None:
                items = [{
                    "category": category, "item_name": "扣补结算",
                    "status": OffboardingClearanceItem.STATUS_DEDUCTED,
                    "deduction_amount": deduction, "supplement_amount": supplement,
                    "remark": None,
                }]
        rows.extend(items)
    return rows


async def import_from_instance(
    db: AsyncSession, case: OffboardingCase, fields: dict[str, Any],
) -> int:
    """飞书清退实例表单 → 平台清退单；返回写入条数（无映射控件返回 0，不堵流程）。"""
    rows = _build_rows(fields)
    if not rows:
        logger.info("清退实例表单无可回读明细: case=%s", case.id)
        return 0
    imported_categories = {row["category"] for row in rows}
    # 只替换飞书来源行；该部门尚未动过的默认行（seed）撤掉，避免与回读结果重复
    for old in await repo.list_clearance_items(db, case.id):
        if old.source == OffboardingClearanceItem.SOURCE_FEISHU or (
            old.source == OffboardingClearanceItem.SOURCE_SEED
            and old.category in imported_categories
            and old.status == OffboardingClearanceItem.STATUS_PENDING
        ):
            old.is_deleted = True
    stamp = datetime.now(UTC)
    imported = []
    for row in rows:
        confirmed = row["status"] != OffboardingClearanceItem.STATUS_PENDING
        imported.append(OffboardingClearanceItem(
            case_id=case.id,
            source=OffboardingClearanceItem.SOURCE_FEISHU,
            confirmed_by="飞书会签" if confirmed else None,
            confirmed_at=stamp if confirmed else None,
            **row,
        ))
    db.add_all(in_entry_order(imported))
    await db.flush()
    logger.info("清退实例表单回读: case=%s 写入 %d 条", case.id, len(rows))
    return len(rows)
