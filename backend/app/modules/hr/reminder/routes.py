"""人事提醒：接收人测试发送（系统配置 → 提醒配置页的「发送测试」按钮）。

提醒接收人支持「姓名」或 open_id 两种填法，发送前经 resolve_receivers() 解析成 open_id；
其中「同名多人」会解析失败并静默不发送（宁可不发也不发错人）——配置的人无从察觉。
本接口用同一套解析口径发一张测试卡片，把可送达 / 无法解析 / 发送失败如实返回。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.hr.deps import HrAccessContext, require_hr_access
from app.modules.hr.title_review.notify import _lookup_open_id

router = APIRouter(tags=["HR-人事提醒"])

_KIND_LABEL = {
    "probation": "转正提醒",
    "contract": "合同到期提醒",
    "offboarding_lead": "离职发起时限提醒",
    "offboarding_clearance_due": "离职手续催办",
}
_TEST_KINDS = "|".join(_KIND_LABEL)


class ReminderTestPayload(BaseModel):
    kind: str = Field("contract", pattern=f"^({_TEST_KINDS})$")
    receivers: list[str] = Field(default_factory=list, max_length=50)


@router.post("/reminder-settings/test", summary="发送测试提醒（校验接收人能否收到飞书卡片）")
async def send_test_reminder(
    payload: ReminderTestPayload,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:settings:manage")),
) -> dict:
    """向给定接收人发一张测试卡片，返回可送达 / 无法解析 / 发送失败三类结果。"""
    resolved: list[str] = []
    unresolved: list[str] = []
    # 去重保序；open_id 形如 ou_xxx 直接收录，否则按姓名解析（与 resolve_receivers 同口径）
    for entry in dict.fromkeys(e.strip() for e in payload.receivers if e.strip()):
        if entry.startswith("ou_"):
            resolved.append(entry)
            continue
        open_id = await _lookup_open_id(entry)
        if open_id:
            resolved.append(open_id)
        else:
            unresolved.append(entry)

    if not resolved:
        detail = f"没有可送达的接收人（无法解析：{'、'.join(unresolved)}）" if unresolved else "没有可送达的接收人"
        raise HTTPException(status_code=400, detail=detail)

    from app.platform.integrations.feishu.notification import send_user_card

    kind_label = _KIND_LABEL.get(payload.kind, "人事提醒")
    card = {
        "schema": "2.0",
        "header": {"title": {"tag": "plain_text", "content": f"【测试】{kind_label}"}, "template": "green"},
        "body": {"elements": [
            {"tag": "markdown", "content": (
                f"这是一条测试消息：收到即说明「{kind_label}」可以正常送达你的飞书。\n"
                "正式提醒由系统按配置的时间自动发送，无需任何操作。"
            )},
        ]},
    }
    failed: list[dict[str, str]] = []
    sent = 0
    for open_id in resolved:
        try:
            await send_user_card(open_id, card=card)
            sent += 1
        except Exception as e:  # noqa: BLE001 — 单个接收人失败不影响其余，结果如实返回
            failed.append({"receiver": open_id, "error": str(e)})

    return success_response(
        data={"sent": sent, "failed": failed, "unresolved": unresolved},
        message=f"测试消息已发送给 {sent} 位接收人",
    )
