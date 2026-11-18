"""AI+安全日报 REST——与卡片回调共用 service 同源核心（对等鉴权）。

- status：当日进度视图（RequireUser）
- daily-card：(re)post 入口卡（RequireAdmin；测试与管理面）
- submit：表单提交对等入口（RequireUser，operator=鉴权用户 open_id；
  wait_post=True 时内联跑完评价/刷卡，供 E2E 确定性验证）
- evaluate / generate / publish：评价重试 / 负责人汇总 / 发布
  （evaluate 本人或 admin；generate/publish 负责人名单∪admin，service 内 fail-closed）
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.response import success_response
from app.modules.safety.service.daily_report import service
from app.platform.permission.deps import RequireAdmin, RequireUser

logger = logging.getLogger(__name__)

daily_report_router = APIRouter()


async def _safety_open_id(user: object) -> str:
    """鉴权用户 → 安全应用作用域 open_id。

    identity 库 feishu_open_id 是平台/跨应用值（如库存 ou_5773…），而日报
    名单/卡片回调/DM/Bitable 全部走 safety 作用域（如 ou_4950…）——直用会
    撞出「同一人两条记录」。经 mention.resolve_open_ids（identity 姓名链
    →邮箱批量→user_id 反查）映射；解析失败回落直链（降级，仅 REST 路径）。
    """
    raw = getattr(user, "feishu_open_id", None) or ""
    name = (getattr(user, "name", None) or "").strip()
    if not name:
        return raw
    try:
        from app.modules.safety.feishu.mention import resolve_open_ids

        resolved = await resolve_open_ids([name])
        return resolved.get(name) or raw
    except Exception:  # noqa: BLE001 — 解析链异常回落直链
        logger.warning("日报 REST open_id 作用域映射失败，回落直链: name=%s", name)
        return raw


class DailyReportSubmitIn(BaseModel):
    date_key: str | None = Field(None, description="日期键 YYYY-MM-DD，缺省=当天")
    work: str = Field("", max_length=2000)
    done: str = Field("", max_length=2000)
    issue: str = Field("", max_length=2000)
    plan: str = Field("", max_length=2000)
    wait_post: bool = Field(False, description="内联执行提交后处理（评价/刷卡），E2E 用")


class DateKeyIn(BaseModel):
    date_key: str | None = Field(None, description="日期键 YYYY-MM-DD，缺省=当天")


@daily_report_router.get("/daily-report/status")
async def get_daily_report_status(
    date: str | None = Query(None, description="日期键 YYYY-MM-DD，缺省=当天"),
    *,
    _user: RequireUser,
) -> JSONResponse:
    return success_response(await service.get_status(date))


@daily_report_router.post("/daily-report/daily-card")
async def post_daily_report_card(
    body: DateKeyIn | None = None,
    *,
    _admin: RequireAdmin,
) -> JSONResponse:
    msg_id = await service.refresh_daily_card((body or DateKeyIn()).date_key)
    return success_response({"message_id": msg_id})


@daily_report_router.post("/daily-report/submit")
async def post_daily_report_submit(
    body: DailyReportSubmitIn,
    user: RequireUser,
) -> JSONResponse:
    operator = await _safety_open_id(user)
    sections = {"work": body.work, "done": body.done, "issue": body.issue, "plan": body.plan}
    result = await service.submit(operator, sections, body.date_key)
    if result["ok"] and body.wait_post:
        try:
            await service.post_submit(operator, result["stage"], body.date_key)
        except Exception:  # noqa: BLE001 — 提交已成功，后处理失败记日志不炸端点
            logger.exception("submit 后处理失败: operator=%s stage=%s", operator, result["stage"])
    return success_response(result)


@daily_report_router.post("/daily-report/evaluate")
async def post_daily_report_evaluate(
    body: DateKeyIn | None = None,
    *,
    user: RequireUser,
) -> JSONResponse:
    operator = await _safety_open_id(user)
    result = await service.run_evaluation(
        (body or DateKeyIn()).date_key or "", operator, force=True,
    )
    return success_response(result)


@daily_report_router.post("/daily-report/generate")
async def post_daily_report_generate(
    body: DateKeyIn | None = None,
    *,
    user: RequireUser,
) -> JSONResponse:
    operator = await _safety_open_id(user)
    result = await service.generate_leader(operator, (body or DateKeyIn()).date_key)
    return success_response(result)


@daily_report_router.post("/daily-report/publish")
async def post_daily_report_publish(
    body: DateKeyIn | None = None,
    *,
    user: RequireUser,
) -> JSONResponse:
    operator = await _safety_open_id(user)
    result = await service.publish(operator, (body or DateKeyIn()).date_key)
    return success_response(result)
