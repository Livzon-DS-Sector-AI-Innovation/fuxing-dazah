"""部门负责人 / 分管领导的账号就绪状态：部门管理列表上提示 HR 谁收不到提醒和审批。

为什么需要：劳动合同续签审批提醒、转正审批、离职审批都靠「姓名 → 飞书账号」找人
（title_review.notify._lookup_open_id），而部门负责人只能在部门管理里手工选。
填了名字不等于发得出去——没登录过系统、同名多账号、后来离职了，都得让 HR 当场看见。

判断口径与 _lookup_open_id 一致（先看登录账号 identity.users，没有再看员工档案的飞书 ID）：
- ok           能唯一解析到飞书账号，且仍在职
- no_account   没登录过本系统，员工档案里也没有飞书 ID —— 收不到
- ambiguous    同名多个账号，无法确定发给谁 —— 不会发（宁可不发也不发错人）
- left         能解析到账号，但人已不在职 —— 会发给已离职的人

「是否在职」要同时看员工档案和离职台账：离职员工通常已被同步移出员工档案，
离职事实只留在离职台账里，只看员工档案会把离职的人判成就绪。

集合式查询（三条 SQL），不像 _lookup_open_id 那样逐人开会话、逐人打警告日志。
"""

from collections.abc import Iterable

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

STATUS_OK = "ok"
STATUS_NO_ACCOUNT = "no_account"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_LEFT = "left"


async def account_statuses(
    db: AsyncSession, names: Iterable[str | None],
) -> dict[str, str]:
    """一批姓名 → 账号就绪状态，返回 {姓名: 状态}；空姓名不出现在结果里。"""
    wanted = sorted({name for name in names if name})
    if not wanted:
        return {}
    in_names = bindparam("names", expanding=True)
    identity_counts = dict((await db.execute(
        text(
            "SELECT name, COUNT(DISTINCT feishu_open_id) FROM identity.users "
            "WHERE name IN :names AND is_deleted = false AND feishu_open_id IS NOT NULL "
            "GROUP BY name"
        ).bindparams(in_names),
        {"names": wanted},
    )).all())
    employee_rows = (await db.execute(
        text(
            "SELECT name, "
            "COUNT(DISTINCT feishu_open_id) FILTER (WHERE feishu_open_id IS NOT NULL) AS open_ids, "
            "COUNT(*) FILTER (WHERE status <> '离职') AS in_service "
            "FROM hr.employees "
            "WHERE name IN :names AND is_deleted = false "
            "GROUP BY name"
        ).bindparams(in_names),
        {"names": wanted},
    )).all()
    employees = {name: (open_ids, in_service) for name, open_ids, in_service in employee_rows}
    departed_names = set((await db.execute(
        text(
            "SELECT DISTINCT name FROM hr.departure_records "
            "WHERE name IN :names AND is_deleted = false"
        ).bindparams(in_names),
        {"names": wanted},
    )).scalars().all())

    statuses: dict[str, str] = {}
    for name in wanted:
        n_identity = identity_counts.get(name, 0)
        n_employee, in_service = employees.get(name, (0, 0))
        if n_identity > 1 or (n_identity == 0 and n_employee > 1):
            statuses[name] = STATUS_AMBIGUOUS
        elif n_identity == 0 and n_employee == 0:
            statuses[name] = STATUS_NO_ACCOUNT
        elif in_service == 0 and (name in employees or name in departed_names):
            statuses[name] = STATUS_LEFT
        else:
            statuses[name] = STATUS_OK
    return statuses
