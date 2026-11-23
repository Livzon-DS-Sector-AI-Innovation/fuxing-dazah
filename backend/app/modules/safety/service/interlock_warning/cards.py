"""红色预警提醒卡构建 —— 纯函数（复用 send_user_card 的信封，产出 title+markdown 正文）。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from .records import RedRecord

CARD_TITLE = "🔴 安全设施摘除超期·红色预警提醒"
_BASE_URL = "https://j0eukrlohu.feishu.cn/base"
# 台账记录链接兜底值（正常由 service 层按 bitable_config 实际连接传入，防换表漂移）
_LEDGER_APP_TOKEN = "FGUHbF1DJamdjJskoKhcj7kbngf"
_LEDGER_TABLE_ID = "tblWlELZ5YiKMB95"
_OVERDUE_ESCALATE_DAYS = 30
_BLOCK_SEPARATOR = "\n\n━━━━━━━━━━━━\n\n"


def record_url_builder(app_token: str, table_id: str) -> Callable[[str], str]:
    """按实际连接生成台账记录直链构造器。"""
    def _url(record_id: str) -> str:
        return f"{_BASE_URL}/{app_token}?table={table_id}&record={record_id}"

    return _url


ledger_record_url = record_url_builder(_LEDGER_APP_TOKEN, _LEDGER_TABLE_ID)
"""台账记录直链（registry 默认连接兜底版；service 层优先传连接驱动版）。"""


def _overdue_line(rec: RedRecord) -> str:
    if rec.overdue_days is None:
        return "🚨 已超期：-（未填预计恢复时间）"
    heavy = " ⚠️⚠️⚠️" if rec.overdue_days > _OVERDUE_ESCALATE_DAYS else ""
    return f"🚨 已超期：**{rec.overdue_days} 天**{heavy}"


def _record_block(
    rec: RedRecord,
    roles: tuple[str, ...],
    round_no: int | None,
    record_url: Callable[[str], str],
) -> str:
    head = f"**📋 {rec.code or rec.record_id} · {rec.department or '未知部门'}**"
    if round_no:
        head += f"（第{round_no}次提醒）"
    facility = rec.facility_type or "未填"
    if rec.is_critical:
        facility += "（关键装置/重点部位）"
    lines = [head, f"⚙️ 设施类型：{facility}"]
    if rec.location:
        lines.append(f"📍 设备位置：{rec.location}")
    lines.append(
        f"📅 变更时间：{rec.changed_on or '-'} ｜ ⏰ 预计恢复：{rec.expected_recovery_on or '-'}"
    )
    lines.append(_overdue_line(rec))
    node = f"🔄 当前节点：{rec.node or '-'}"
    if rec.handler_name:
        node += f"（处理人：{rec.handler_name}）"
    lines.append(node)
    lines.append(f"👤 您的角色：{'、'.join(roles) or '-'}")
    links = []
    if rec.approval_url:
        links.append(f"[查看审批详情]({rec.approval_url})")
    links.append(f"[打开台账]({record_url(rec.record_id)})")
    lines.append("🔗 " + " ｜ ".join(links))
    return "\n".join(lines)


def build_warning_card(
    person_name: str,
    entries: list[tuple[RedRecord, tuple[str, ...]]],
    *,
    rounds: dict[str, int | None],
    record_url: Optional[Callable[[str], str]] = None,
) -> tuple[str, str]:
    """一人一卡：entries=[(记录, 该人角色元组)]，rounds={record_id: 轮次}。

    record_url：台账记录直链构造器（service 层按 bitable_config 实际连接传入，
    缺省回落 registry 默认连接常量版 ledger_record_url）。
    """
    url_fn = record_url or ledger_record_url
    greeting = f"{person_name} 您好，您名下有 {len(entries)} 条设施摘除红色超期记录："
    blocks = [
        _record_block(rec, roles, rounds.get(rec.record_id), url_fn)
        for rec, roles in entries
    ]
    footer = "设施恢复并完成「恢复确认」后，提醒自动停止（每 2 天提醒一次）。"
    return CARD_TITLE, greeting + "\n\n" + _BLOCK_SEPARATOR.join(blocks) + "\n\n" + footer
