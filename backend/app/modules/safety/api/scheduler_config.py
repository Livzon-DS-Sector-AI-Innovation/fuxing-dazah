"""Safety API — 定时任务 + AI 配置读写端点。

GET /scheduler-config/ai-config                → AI 配置总览（只读，脱敏）
PUT /scheduler-config/ai-config/{profile}      → 单组更新（校验 + 审计 + 失效）
GET /scheduler-config/ai-config/audits         → 变更审计列表（profile 可选过滤）
POST /scheduler-config/ai-config/test          → 连通性探测（httpx 最小请求，不写审计）
GET /scheduler-config/ai-scenarios             → 场景合并视图（注册元信息 + 配置状态）
PUT /scheduler-config/ai-scenarios/{scenario}  → 单场景更新（未知 404、白名单外 422）
GET /scheduler-config/ai-scenarios/audits      → 场景配置审计列表（scenario 可选过滤）
GET /scheduler-config/tasks                    → 代码默认 + DB 覆写 + 今日运行状态
PUT /scheduler-config/tasks/{job_name}         → 覆写配置（写安全模块审计表）
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import success_response
from app.modules.safety.ai_config import registry
from app.modules.safety.ai_config.probe import probe_profile
from app.modules.safety.ai_config.scenario_registry import (
    get_scenario_info,
    iter_scenarios,
)
from app.modules.safety.ai_config.scenario_store import ScenarioView, scenario_store
from app.modules.safety.ai_config.store import ProfileView, store
from app.modules.safety.models import (
    AiConfigAudit,
    AiScenarioConfigAudit,
    SchedulerJobRun,
)
from app.modules.safety.schemas.ai_config import (
    AiConfigAuditItem,
    AiConfigTestRequest,
    AiProfileUpdate,
    AiScenarioAuditItem,
    AiScenarioItemOut,
    AiScenarioUpdate,
)
from app.modules.safety.schemas.scheduler_config import (
    SchedulerPreviewRequest,
    SchedulerTaskUpdate,
)
from app.modules.safety.service.ai_config import build_ai_config_view
from app.modules.safety.service.feishu_groups import list_feishu_groups
from app.modules.safety.service.scheduler_config import (
    load_scheduled_jobs_with_overrides,
    upsert_task_config,
)
from app.modules.safety.service.scheduler_preview import preview_task_report

logger = logging.getLogger(__name__)

scheduler_config_router = APIRouter()


async def _attach_target_names(
    tasks: list[dict[str, Any]], db: AsyncSession
) -> None:
    """把 target_chat_id 解析成名称写入 target_chat_name（DB 未存名称时）。

    群聊（oc_）经飞书群列表解析；个人（ou_）经 identity.users 按 open_id 反查姓名。
    解析失败仅名称为空，不影响接口。
    """
    if not any(t.get("target_chat_id") for t in tasks):
        return
    group_name_map: dict[str, str] = {}
    try:
        groups_data = await list_feishu_groups()
        group_name_map = {
            g.get("chat_id", ""): (g.get("name") or "")
            for g in groups_data.get("items", [])
        }
    except Exception:
        logger.exception("发送对象名称解析失败（不影响接口）")

    ou_ids = [
        t["target_chat_id"]
        for t in tasks
        if (t.get("target_chat_id") or "").startswith("ou_")
    ]
    person_name_map: dict[str, str] = {}
    if ou_ids:
        try:
            from app.platform.identity.models import User

            rows = (
                await db.execute(select(User).where(User.feishu_open_id.in_(ou_ids)))
            ).scalars().all()
            person_name_map = {
                u.feishu_open_id: u.name for u in rows if u.feishu_open_id
            }
        except Exception:
            logger.exception("人员名称解析失败（不影响接口）")

    for t in tasks:
        cid = t.get("target_chat_id")
        if not cid or t.get("target_chat_name"):
            continue
        if str(cid).startswith("ou_"):
            t["target_chat_name"] = person_name_map.get(cid) or None
        else:
            t["target_chat_name"] = group_name_map.get(cid) or None


def _get_profile_or_404(profile: str) -> None:
    """未知 profile → 404（detail 以「未知 profile」开头，与 scheduler 惯例一致）。"""
    try:
        registry.get_profile(profile)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _profile_out(view: ProfileView) -> dict[str, Any]:
    """store.ProfileView → 响应 dict：config.api_key 恒为空串（密钥绝不回显）。"""
    config = {k: ("" if k == "api_key" else v) for k, v in view.config.items()}
    return {
        "profile": view.profile,
        "label": view.label,
        "config": config,
        "api_key_masked": view.api_key_masked,
        "enabled": view.enabled,
        "status": view.status,
        "sources": dict(view.sources),
    }


def _get_scenario_or_404(scenario: str) -> None:
    """未知场景 → 404（detail 以「未知场景」开头，与 registry 消息一致）。"""
    try:
        get_scenario_info(scenario)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _scenario_out(view: ScenarioView) -> dict[str, Any]:
    """store.ScenarioView → 响应 dict（allowed_profiles tuple → list，与 schema 同构）。"""
    return AiScenarioItemOut.model_validate(view).model_dump(mode="json")


@scheduler_config_router.get("/scheduler-config/ai-config", summary="AI 配置总览（只读）")
async def get_ai_config() -> Any:
    """返回当前 AI 模型配置（脱敏）与已注册 AI 调用功能清单。"""
    return success_response(data=build_ai_config_view())


@scheduler_config_router.put(
    "/scheduler-config/ai-config/{profile}", summary="更新单个 AI 模型配置"
)
async def update_ai_config_profile(
    profile: str,
    data: AiProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> Any:
    """单组更新：store 事务内写审计 before/after + 失效缓存。

    错误语义（§5.2）：未知 profile → 404；Pydantic 校验失败 / profile 无关字段
    （store ValueError）→ 422；成功返回合并视图（api_key 恒空串，只给脱敏展示）。
    """
    _get_profile_or_404(profile)
    operator_name = current_user.name if current_user else None
    try:
        view = await store.set_profile(
            db,
            profile,
            data.model_dump(exclude_unset=True),
            operator_name=operator_name,
        )
    except ValueError as exc:
        message = str(exc)
        if message.startswith("未知"):
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc
    return success_response(data=_profile_out(view))


@scheduler_config_router.get(
    "/scheduler-config/ai-config/audits", summary="AI 配置变更审计列表"
)
async def list_ai_config_audits(
    profile: str | None = Query(None, description="按 profile 过滤"),
    limit: int = Query(50, ge=1, le=200, description="返回条数上限"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> Any:
    """变更审计列表（append-only，最新在前；before/after 的 api_key 已脱敏）。"""
    if profile is not None:
        _get_profile_or_404(profile)
    stmt = (
        select(AiConfigAudit)
        .where(AiConfigAudit.is_deleted.is_(False))
        .order_by(AiConfigAudit.created_at.desc())
        .limit(limit)
    )
    if profile is not None:
        stmt = stmt.where(AiConfigAudit.profile == profile)
    rows = (await db.execute(stmt)).scalars().all()
    items = [AiConfigAuditItem.model_validate(r).model_dump(mode="json") for r in rows]
    return success_response(data=items)


@scheduler_config_router.get(
    "/scheduler-config/ai-scenarios", summary="AI 场景配置列表（注册元信息 + 配置状态）"
)
def list_ai_scenarios(
    current_user: CurrentUser | None = Depends(get_current_user),
) -> Any:
    """遍历场景注册表合并 store 视图（enabled 缺省 true、effective_profile 已派生）。

    注册表即事实源：未注册场景不出现；含 deprecated（drill_report_generation=true 标注）。
    """
    items = [
        _scenario_out(scenario_store.get_scenario_view(info.scenario))
        for info in iter_scenarios()
    ]
    return success_response(data=items)


@scheduler_config_router.get(
    "/scheduler-config/ai-scenarios/audits", summary="AI 场景配置变更审计列表"
)
async def list_ai_scenario_audits(
    scenario: str | None = Query(None, description="按场景过滤"),
    limit: int = Query(50, ge=1, le=200, description="返回条数上限"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> Any:
    """场景配置变更审计列表（append-only，最新在前；场景表无密钥，不脱敏）。"""
    if scenario is not None:
        _get_scenario_or_404(scenario)
    stmt = (
        select(AiScenarioConfigAudit)
        .where(AiScenarioConfigAudit.is_deleted.is_(False))
        .order_by(AiScenarioConfigAudit.created_at.desc())
        .limit(limit)
    )
    if scenario is not None:
        stmt = stmt.where(AiScenarioConfigAudit.scenario == scenario)
    rows = (await db.execute(stmt)).scalars().all()
    items = [AiScenarioAuditItem.model_validate(r).model_dump(mode="json") for r in rows]
    return success_response(data=items)


@scheduler_config_router.put(
    "/scheduler-config/ai-scenarios/{scenario}", summary="更新单个 AI 场景配置"
)
async def update_ai_scenario(
    scenario: str,
    data: AiScenarioUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> Any:
    """单场景更新：store 事务内写审计 before/after + 失效缓存（部分更新）。

    错误语义（§6.3）：未知场景 → 404（「未知场景: xxx」）；Pydantic 校验失败 /
    白名单外绑定（store ValueError）→ 422；成功返回合并视图（与 GET 单条同构）。
    """
    _get_scenario_or_404(scenario)
    operator_name = current_user.name if current_user else None
    try:
        view = await scenario_store.set_scenario(
            db,
            scenario,
            data.model_dump(exclude_unset=True),
            operator_name=operator_name,
        )
    except ValueError as exc:
        message = str(exc)
        if message.startswith("未知"):
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc
    return success_response(data=_scenario_out(view))


@scheduler_config_router.post(
    "/scheduler-config/ai-config/test", summary="AI 配置连通性探测"
)
async def test_ai_config(
    data: AiConfigTestRequest,
    current_user: CurrentUser | None = Depends(get_current_user),
) -> Any:
    """httpx 最小请求连通性探测（不写库不写审计，对齐 bitable test-connection）。

    错误语义（§5.4）：未知 profile → 404；参数非法 → 422；
    上游 5xx / 网络异常 → 502；其余失败（含 4xx、未配置）→ 200 返回 ok=False，
    由前端展示失败原因。
    """
    _get_profile_or_404(data.profile)
    result = await probe_profile(data.profile, data.config)
    if not result.get("ok"):
        status_code = result.get("status_code")
        upstream_failure = status_code is not None and status_code >= 500
        # 网络/超时异常（status_code=None 且非「未配置」）→ 502
        network_failure = (
            status_code is None and not str(result.get("message", "")).startswith("未配置")
        )
        if upstream_failure or network_failure:
            raise HTTPException(
                status_code=502,
                detail=f"AI 服务探测失败: {result.get('message')}",
            )
    return success_response(data=result)


@scheduler_config_router.get("/scheduler-config/feishu/groups", summary="飞书机器人所在群聊列表")
async def get_feishu_groups(force: bool = False) -> Any:
    """返回安全模块飞书应用可见的群聊列表（5 分钟缓存）。"""
    return success_response(data=await list_feishu_groups(force=force))


@scheduler_config_router.get("/scheduler-config/persons", summary="人员列表（发送对象-个人）")
async def list_persons(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> Any:
    """返回已绑定飞书 open_id 的用户（个人 DM 发送对象候选）。"""
    from app.platform.identity.models import User

    rows = (
        await db.execute(
            select(User)
            .where(User.feishu_open_id.isnot(None))
            .where(User.feishu_open_id != "")
            .order_by(User.name.asc())
        )
    ).scalars().all()
    data = [
        {
            "open_id": u.feishu_open_id,
            "name": u.name,
            "department": getattr(u, "department", None) or None,
        }
        for u in rows
    ]
    return success_response(data=data)


@scheduler_config_router.get("/scheduler-config/tasks", summary="定时任务列表")
async def list_scheduler_tasks(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> Any:
    """返回合并后的定时任务列表（含 run_state）。"""
    tasks = await load_scheduled_jobs_with_overrides(db)
    run_rows = (
        await db.execute(
            select(SchedulerJobRun).where(SchedulerJobRun.is_deleted.is_(False))
        )
    ).scalars().all()
    run_map = {r.job_name: r for r in run_rows}
    for task in tasks:
        row = run_map.get(task["job_name"])
        task["run_state"] = {
            "fired_date": row.fired_date.isoformat() if row else None,
            "status": row.status if row else None,
            "attempt_count": row.attempt_count if row else 0,
            "last_attempt_at": row.last_attempt_at.isoformat() if row and row.last_attempt_at else None,
            "alerted": row.alerted if row else False,
        }
    to_return = list(tasks)
    await _attach_target_names(to_return, db)
    return success_response(data=to_return)


@scheduler_config_router.put("/scheduler-config/tasks/{job_name}", summary="更新定时任务配置")
async def update_scheduler_task(
    job_name: str,
    data: SchedulerTaskUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> Any:
    """更新任务覆写配置，并写审计记录。"""
    operator_name = current_user.name if current_user else None
    try:
        task = await upsert_task_config(
            db,
            job_name,
            data.model_dump(exclude_unset=True),
            operator_name=operator_name,
        )
    except ValueError as exc:
        message = str(exc)
        if message.startswith("未知"):
            raise HTTPException(status_code=404, detail=message)
        raise HTTPException(status_code=400, detail=message)
    to_return = [task]
    await _attach_target_names(to_return, db)
    return success_response(data=to_return[0])


@scheduler_config_router.post("/scheduler-config/tasks/{job_name}/preview", summary="预览报告（不推送）")
async def preview_scheduler_task(
    job_name: str,
    body: SchedulerPreviewRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
) -> Any:
    """只读生成报告 Markdown，绝不发送飞书。"""
    req = body or SchedulerPreviewRequest(date=None)
    try:
        preview = await preview_task_report(db, job_name, req.date)
    except ValueError as exc:
        message = str(exc)
        if message.startswith("未知"):
            raise HTTPException(status_code=404, detail=message)
        raise HTTPException(status_code=400, detail=message)
    return success_response(data=preview)
