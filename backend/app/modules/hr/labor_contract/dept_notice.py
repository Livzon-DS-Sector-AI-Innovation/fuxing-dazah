"""部门负责人续签审批提醒：合同到期预警对用人部门负责人的推送。

需求：合同到期（进入公告期）要通知用人部门负责人。部门审批默认在系统内完成
（service.apply_dept_decision），负责人收不到飞书审批待办，所以合同一旦变成
「公告期 · 站内待审批」就按负责人各发一张卡片，列出待其勾选「同意 / 不同意续签」
的合同。收件人与飞书原生审批的审批人同源（renewal_approval.resolve_approver）。

触发点见 scheduled.py：每天公告期扫描新进入的合同；飞书审批被撤销后退回站内的合同。
卡片只发一次、不逐日重复；负责人匹配不到或推送失败的合同交 HR 摘要兜底。
开关 hr_contract.dept_head_notice_enabled 缺省开（labor_contract/settings.py）。
"""

import logging
from datetime import date

from app.core.config import get_settings
from app.modules.hr.labor_contract import service as contract_service
from app.modules.hr.labor_contract.models import LaborContract
from app.modules.hr.labor_contract.notify import _send

logger = logging.getLogger(__name__)

TITLE = "劳动合同续签审批提醒"
# 卡片正文有长度上限：每位负责人最多列这么多条，其余合并成一行
_MAX_LINES = 20


def ledger_url() -> str:
    """合同台账页地址（卡片按钮用）：取 Settings.FRONTEND_URL，未配置返回空串、不带按钮。"""
    base = (get_settings().FRONTEND_URL or "").strip().rstrip("/")
    return f"{base}/hr/labor-contracts" if base else ""


def _expiry_text(end_date: date | None, today: date) -> str:
    if end_date is None:
        return "无固定期限"
    left = (end_date - today).days
    if left > 0:
        return f"{end_date} 到期（剩 {left} 天）"
    if left == 0:
        return f"{end_date} 到期（今天）"
    return f"{end_date} 已到期 {-left} 天"


def approval_reminder_markdown(
    contracts: list[LaborContract], *, today: date | None = None, note: str | None = None,
) -> str:
    """给一位负责人的待审批清单正文。note 为附加说明（如飞书审批被撤销的情形）。"""
    today = today or date.today()
    lines = [f"您部门有 **{len(contracts)}** 名员工的劳动合同已进入公告期，请审批是否续签："]
    for contract in contracts[:_MAX_LINES]:
        who = [contract.name, f"工号 {contract.employee_number}"]
        if contract.department:
            who.append(contract.department)
        if contract.position:
            who.append(contract.position)
        lines.append(
            f"- {'，'.join(who)}；现合同 {_expiry_text(contract.end_date, today)}，"
            f"续签为「{contract_service.next_term_preview(contract.seq_no + 1)}」"
        )
    rest = contracts[_MAX_LINES:]
    if rest:
        lines.append(f"- 其余 {len(rest)} 人请在合同台账中查看")
    if note:
        lines += ["", note]
    lines += [
        "",
        "请打开 **人事管理 → 人员管理 → 劳动合同**，在「在职合同台账」筛选「公告期/续签办理中」，"
        "点「详情」选择**同意续签**或**不同意续签**。",
    ]
    return "\n".join(lines)


async def notify_dept_heads(
    targets: list[tuple[LaborContract, str, str]], *, note: str | None = None,
) -> dict[str, list[tuple[LaborContract, str]]]:
    """按负责人分组各发一张卡片。targets: (合同, 负责人姓名, 负责人 open_id)。

    返回 {"notified": [(合同, 负责人)], "failed": [(合同, 负责人)]}；
    推送失败的由调用方并入 HR 摘要的「未通知到」。
    """
    grouped: dict[str, list[LaborContract]] = {}
    manager_names: dict[str, str] = {}
    for contract, manager_name, open_id in targets:
        grouped.setdefault(open_id, []).append(contract)
        manager_names.setdefault(open_id, manager_name)
    result: dict[str, list[tuple[LaborContract, str]]] = {"notified": [], "failed": []}
    elements = None
    url = ledger_url()
    if url:
        elements = [{
            "tag": "action",
            "actions": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": "去合同台账审批"},
                "type": "primary",
                "url": url,
            }],
        }]
    for open_id, contracts in grouped.items():
        ok = await _send(
            open_id, TITLE, approval_reminder_markdown(contracts, note=note), elements,
        )
        result["notified" if ok else "failed"].extend(
            (contract, manager_names[open_id]) for contract in contracts
        )
    return result
