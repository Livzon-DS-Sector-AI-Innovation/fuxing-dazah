"""HR 模块后台服务声明：飞书事件回调、定时任务、职称评审专属长连接、MCP 工具注册触发。

main.py 只认 HR_EXTENSION 实例，不再感知本模块内部细节。
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import get_settings
from app.modules.hr import mcp_tools  # noqa: F401 — 触发 @mcp.tool() 注册
from app.platform.module_lifecycle import ModuleExtension, ModuleHost

logger = logging.getLogger(__name__)


async def _warm_probation_config() -> None:
    """启动时把试用期时长配置（hr.system_settings KV）读进进程缓存。

    computed_probation_end 是 ORM 同步 property，只能读缓存：不预热的话，自定义过时长的情况下
    重启后到首次刷新之间，列表里的试用期结束日期都按默认时长算。

    register 阶段不做 I/O、start 是同步钩子，所以借宿主的后台任务在框架启动阶段执行；
    协程一次性返回即结束。读失败不阻断启动——缓存初值即默认时长，
    转正发起与每日提醒任务运行时会再刷新。
    """
    from app.core.database import async_session_factory
    from app.modules.hr.probation_config import reload_probation_config

    try:
        async with async_session_factory() as db:
            await reload_probation_config(db)
    except Exception:
        logger.warning("试用期时长配置预热失败，暂用默认时长", exc_info=True)


class HrExtension(ModuleExtension):
    """HR 模块对进程生命周期的声明。"""

    code = "hr"

    def register(self, host: ModuleHost) -> None:
        from app.modules.hr.employee_info_collection_service import (
            register_feishu_callbacks as register_eic_callbacks,
        )
        from app.modules.hr.employee_sync.scheduled import EMPLOYEE_SYNC_TASK
        from app.modules.hr.interview_score_service import (
            register_feishu_callbacks as register_iv_score_callbacks,
        )
        from app.modules.hr.probation_service import (
            register_feishu_callbacks as register_probation_callbacks,
        )
        from app.modules.hr.reminder import register_reminder_tasks
        from app.modules.hr.title_review.bitable_handler import (
            register_feishu_callbacks as register_hr_feishu_callbacks,
        )
        from app.modules.hr.title_review.scheduled import TITLE_REVIEW_SYNC_TASK

        # ── 飞书事件回调（注册制分发；框架保证全部 register 完成后才启动 WS）──
        register_hr_feishu_callbacks()
        register_eic_callbacks()
        register_probation_callbacks()
        register_iv_score_callbacks()

        if get_settings().HR_TITLE_REVIEW_SYNC_ENABLED:
            host.scheduler.register_task(TITLE_REVIEW_SYNC_TASK)
        # 员工档案多维表格同步：任务内部读 DB 配置决定是否执行（无需 env 开关）
        host.scheduler.register_task(EMPLOYEE_SYNC_TASK)
        # 人事提醒任务聚合注册（转正 09:00 / 合同到期 09:10；接收人未配置时仅日志，
        # 配置存 hr.system_settings）。转正提醒任务也由它登记，此处不要再单独注册——重名会抛错。
        register_reminder_tasks(host.scheduler)

        host.add_background_loop("hr:probation_config_warmup", _warm_probation_config)

    def start(self, host: ModuleHost) -> None:
        settings = get_settings()
        # ── 职称评审专属多维表格事件长连接（独立应用凭证，事件共享同一处理器）──
        # 单实例确认：lark_oapi SDK 的 WS 客户端使用模块级全局 loop，不支持与
        # 平台全局长连接并发（后启动者会互相覆盖 loop 导致 RuntimeError 崩溃）。
        # 平台全局长连接已启用时跳过；职称评审的表事件由全局连接（全局应用订阅）送达。
        if not (
            settings.HR_TITLE_REVIEW_FEISHU_WS_ENABLED
            and settings.HR_TITLE_REVIEW_FEISHU_APP_ID
            and not settings.FEISHU_WS_ENABLED
        ):
            return
        from app.platform.integrations.feishu.event_handler import (
            build_event_handler,
            set_main_loop,
        )
        from app.platform.integrations.feishu.ws_client import start_ws_client

        set_main_loop(asyncio.get_running_loop())
        start_ws_client(
            settings.HR_TITLE_REVIEW_FEISHU_APP_ID,
            settings.HR_TITLE_REVIEW_FEISHU_APP_SECRET,
            build_event_handler(),
            name="title-review-ws",
        )


HR_EXTENSION = HrExtension()
