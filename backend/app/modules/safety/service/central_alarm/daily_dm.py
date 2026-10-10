"""中控报警日报私发 — 按部门过滤的日报卡片 DM 给提炼四/五/六部指定人员。

用户确认：
- 2026-09-30：参考消防报警日报私发（``fire_alarm/daily_dm.py``）的独立任务模式；
  收件人名单见 DM_RECIPIENTS
- 2026-10-08：车间/产线 → 部门归属映射（TABLE_DEPT_MAP，14 张分表全覆盖），
  每位收件人只收**本部门所属车间**的报警（统计与明细按子集重算）；
  群内安全速递总卡保持全量不变
- 开关 ``SAFETY_CENTRAL_ALARM_DAILY_DM_ENABLED`` 默认 false（未开启直接跳过）

表级归属（车间+产线二元组；同车间不同产线可属不同部门）：
- 提炼工程五部：车间一（达托/达巴）、车间二（达巴、非达 / 达托）
- 提炼工程四部：车间一（雷帕）、车间二（莫西）、车间四（米尔贝/塞拉）、
  新罐区、酒精回收和旧罐区、异丙醇回收、乙腈回收
- 提炼工程六部：车间二（替考 / 替考精烘包）
未命中映射的记录（如历史脏行 workshop=tblXXX）不计入任何部门的私发卡。

身份链路：
- 统一走 ``feishu.mention.resolve_open_ids``（邮箱 batch_get_id / user_id 反查
  → 安全应用作用域 open_id），``send_user_card(open_id)`` 直发；
  林锴彬在 identity.users 无邮箱、有 feishu_user_id，user_id 反查是唯一可用通道
  （2026-09-30 真机验证四人 open_id 均可解析）
"""

from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any

from app.modules.safety.feishu.notification import send_user_card

logger = logging.getLogger(__name__)

# 私发开关（默认关；确认后再置 true，17:00 随日报自动私发）
DM_ENABLED = os.getenv("SAFETY_CENTRAL_ALARM_DAILY_DM_ENABLED", "false").lower() == "true"

# 卡片 header 标题颜色（日报卡：蓝头信息卡，区别于消防一卡一条的 red 告警卡）
HEADER_TEMPLATE = "blue"

# 私发收件人名单：部门 → [姓名]。卡片内容按部门过滤（本部门所属车间的报警）。
DM_RECIPIENTS: dict[str, list[str]] = {
    "提炼工程四部": ["杨昆", "林锴彬"],
    "提炼工程五部": ["蔡嘉旺"],
    "提炼工程六部": ["陈美丽"],
}

# 车间+产线（分表）→ 部门归属映射（2026-10-08 业务确认，14 张分表全覆盖）。
# 产线 None = 该表无括号产线（罐区/回收类，表名即车间）。
TABLE_DEPT_MAP: dict[tuple[str, str | None], str] = {
    # 提炼工程五部
    ("车间一", "达托"): "提炼工程五部",
    ("车间一", "达巴"): "提炼工程五部",
    ("车间二", "达巴、非达"): "提炼工程五部",
    ("车间二", "达托"): "提炼工程五部",
    # 提炼工程四部
    ("车间一", "雷帕"): "提炼工程四部",
    ("车间二", "莫西"): "提炼工程四部",
    ("车间四", "米尔贝"): "提炼工程四部",
    ("车间四", "塞拉"): "提炼工程四部",
    ("新罐区", None): "提炼工程四部",
    ("酒精回收和旧罐区", None): "提炼工程四部",
    ("异丙醇回收", None): "提炼工程四部",
    ("乙腈回收", None): "提炼工程四部",
    # 提炼工程六部
    ("车间二", "替考"): "提炼工程六部",
    ("车间二", "替考精烘包"): "提炼工程六部",
}

# 镜像历史脏行兜底：部分同步批次把 workshop 写成了 table_id（近 90 天约 0.7%）。
# 经 table_id → 分表名 → derive_workshop_line 还原 (车间, 产线) 后再查主映射。
_TABLE_ID_TO_TABLE_NAME: dict[str, str] = {
    "tblpO3p8tMal4B1n": "车间一（达托）",
    "tblqwBhprwCZcpCp": "车间一（达巴）",
    "tblivTu1wN9JJIfv": "车间一（雷帕）",
    "tblHvWwh2NRcgk2A": "车间二（达巴、非达）",
    "tblPhO4rjLFRdBAL": "车间二（达托）",
    "tblvWbXdrx282OAw": "车间二（替考）",
    "tblrZl7EfccGdYvg": "车间二（替考精烘包）",
    "tblWWztfPQTIJXEw": "车间二（莫西）",
    "tblJ6Tt0V8lNhxKy": "车间四（米尔贝）",
    "tblvXo7W3hSTHn7Q": "车间四（塞拉）",
    "tblIST5RYnGGz1zc": "新罐区",
    "tblLhez3NmikW12Q": "酒精回收和旧罐区",
    "tbl0Cw9HdKbF6jRj": "异丙醇回收",
    "tblBoLEBUXPnM8qo": "乙腈回收",
}


def dept_for_record(record: Any) -> str | None:
    """记录 → 归属部门（workshop/line strip 后查 TABLE_DEPT_MAP）；未命中返回 None。

    workshop 形如 tblXXX（镜像历史脏行）时经分表名还原 (车间, 产线) 再查主映射。
    """
    workshop = str(getattr(record, "workshop", None) or "").strip()
    line_raw = getattr(record, "line", None)
    line: str | None = line_raw.strip() if isinstance(line_raw, str) else line_raw
    # 空 workshop（""）在映射键中不存在，天然未命中，无需转 None
    dept = TABLE_DEPT_MAP.get((workshop, line))
    if dept is None and workshop.startswith("tbl"):
        from app.modules.safety.service.central_alarm.bitable_mapper import (
            derive_workshop_line,
        )

        table_name = _TABLE_ID_TO_TABLE_NAME.get(workshop)
        if table_name:
            ws, ln = derive_workshop_line(table_name)
            dept = TABLE_DEPT_MAP.get((ws or "", ln))
    return dept


def group_records_by_dept(
    records: list[Any],
) -> tuple[dict[str, list[Any]], int]:
    """按部门归属分组记录。

    Returns:
        (部门 → 记录列表, 未命中映射条数)——未命中映射的记录不计入任何部门
        （如历史脏行 workshop=tblXXX），由调用方记日志。
    """
    by_dept: dict[str, list[Any]] = {}
    unmapped = 0
    for r in records:
        dept = dept_for_record(r)
        if dept is None:
            unmapped += 1
            continue
        by_dept.setdefault(dept, []).append(r)
    return by_dept, unmapped


def dm_recipient_names() -> list[str]:
    """全部私发收件人姓名（按配置顺序去重）。"""
    seen: list[str] = []
    for names in DM_RECIPIENTS.values():
        for name in names:
            if name and name not in seen:
                seen.append(name)
    return seen


def build_dm_card(dept: str, report_date: date, markdown: str) -> tuple[str, dict[str, Any]]:
    """构建私发日报卡片，返回 (markdown 正文, 卡片 dict)。

    正文即该部门的过滤版日报 markdown（统计区间/指标/明细/AI 汇总完整保留，
    与群内全量总卡同款渲染器）。
    """
    content = markdown
    card = {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"📊 中控报警日报 · {dept} · {report_date.isoformat()}",
            },
            "template": HEADER_TEMPLATE,
        },
        "body": {"elements": [{"tag": "markdown", "content": content}]},
    }
    return content, card


async def send_daily_central_alarm_dms(
    report_date: date,
    dept_markdowns: dict[str, str],
    *,
    resolver: Any = None,
    sender: Any = None,
) -> dict[str, int]:
    """按部门过滤的日报卡片私发给 DM_RECIPIENTS 全员（一人一卡，同部门同内容）。

    Args:
        report_date: 报告日期（卡片标题用）
        dept_markdowns: 部门 → 过滤版日报 markdown（窗口内无报警的部门不在
            dict 中，该部门收件人当天不收私发卡——与消防私发「无报警不发」同口径）
        resolver: 姓名 → open_id 解析器（默认 ``mention.resolve_open_ids``，测试替身）
        sender: 卡片发送器（默认 ``send_user_card``，测试替身）

    Returns:
        {"sent", "skipped", "errors", "unresolved", "dept_empty"}：
        sent=发送成功卡片数；skipped=发送返回失败；
        errors=异常条数；unresolved=收件人未解析到 open_id 条数；
        dept_empty=因窗口内无报警而未发卡的收件人次数
        （开关关闭时返回 {"disabled": 1, ...全 0}）
    """
    if not DM_ENABLED:
        logger.info("中控报警日报私发已关闭 (SAFETY_CENTRAL_ALARM_DAILY_DM_ENABLED=false)")
        return {"disabled": 1, "sent": 0, "skipped": 0, "errors": 0,
                "unresolved": 0, "dept_empty": 0}

    names = dm_recipient_names()
    if not names:
        logger.info("中控报警日报私发：收件人名单为空")
        return {"sent": 0, "skipped": 0, "errors": 0, "unresolved": 0, "dept_empty": 0}

    if resolver is None:
        from app.modules.safety.feishu import mention

        resolver = mention.resolve_open_ids
    sender = sender or send_user_card

    try:
        name_to_open_id = dict(await resolver(names))
    except Exception:
        logger.warning("中控报警日报私发：open_id 解析失败", exc_info=True)
        name_to_open_id = {}

    sent = skipped = errors = unresolved = dept_empty = 0
    for dept, dept_names in DM_RECIPIENTS.items():
        markdown = dept_markdowns.get(dept, "")
        if not markdown:
            dept_empty += len(dept_names)
            logger.info("中控报警日报私发：%s 当日无报警，不私发（%s）",
                        dept, "、".join(dept_names))
            continue
        _content, card = build_dm_card(dept, report_date, markdown)
        title = card["header"]["title"]["content"]
        for name in dept_names:
            open_id = name_to_open_id.get(name, "")
            if not open_id:
                unresolved += 1
                logger.warning("中控报警日报私发：收件人未解析 open_id: %s", name)
                continue
            try:
                ok = await sender(
                    open_id=open_id, title=title, content=_content,
                    header_template=HEADER_TEMPLATE,
                )
                if ok:
                    sent += 1
                    logger.info("中控报警日报私发成功: %s=%s", dept, name)
                else:
                    skipped += 1
                    logger.warning("中控报警日报私发失败: %s=%s", dept, name)
            except Exception:
                errors += 1
                logger.exception("中控报警日报私发异常: %s=%s", dept, name)

    logger.info(
        "中控报警日报私发完成: sent=%d skipped=%d errors=%d unresolved=%d dept_empty=%d",
        sent, skipped, errors, unresolved, dept_empty,
    )
    return {"sent": sent, "skipped": skipped, "errors": errors,
            "unresolved": unresolved, "dept_empty": dept_empty}
