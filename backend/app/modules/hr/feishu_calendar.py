"""飞书日历集成 —— 面试日程创建与管理

使用 lark_oapi SDK（与 platform/integrations/feishu/ 模式一致）。
日历操作失败不阻塞面试 CRUD（所有异常内部捕获，log warning）。
"""

import asyncio
import logging
from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import lark_oapi as lark
from lark_oapi.api.calendar.v4 import (
    CalendarEvent,
    CreateCalendarEventRequest,
    DeleteCalendarEventRequest,
    EventOrganizer,
    EventTime,
    PatchCalendarEventRequest,
)

from app.core.config import get_settings
from app.modules.hr.config import HR_FEISHU_CALENDAR_ID

logger = logging.getLogger(__name__)


class FeishuCalendarService:
    """封装飞书日历 API，用于面试日程管理。"""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = (
            lark.Client.builder()
            .app_id(settings.FEISHU_APP_ID)
            .app_secret(settings.FEISHU_APP_SECRET)
            .domain(lark.FEISHU_DOMAIN)
            .app_type(lark.AppType.SELF)
            .build()
        )
        self._calendar_id = HR_FEISHU_CALENDAR_ID

    async def create_interview_event(
        self,
        interview_id: UUID,
        candidate_name: str,
        position: str,
        interview_date_val: date,
        interviewer_name: str,
        location: str,
        interview_type: str = "初试",
    ) -> str:
        """创建飞书日历日程，返回 event_id。日程时长默认 1 小时，从 09:00 开始。"""
        # 明确按 Asia/Shanghai 解释时间：服务器为 UTC（容器默认）时 naive
        # .timestamp() 会按服务器本地时区算 epoch，导致日程时间错 8 小时
        start_time = datetime.combine(
            interview_date_val,
            datetime.strptime("09:00", "%H:%M").time(),
            tzinfo=ZoneInfo("Asia/Shanghai"),
        )
        end_time = start_time + timedelta(hours=1)

        attendees = []
        interviewer_open_id = await self._lookup_open_id(interviewer_name)
        if interviewer_open_id:
            attendees.append(
                {"type": "user", "user_id": interviewer_open_id}
            )
        else:
            # organizer 为飞书必填项：面试官 open_id 解析不到时无法创建有效日程，
            # 显式报错由上层提示，而不是静默建出无主人的日程
            raise RuntimeError(f"无法解析面试官 {interviewer_name} 的 open_id，日程未创建")

        event = (
            CalendarEvent.builder()
            .summary(f"面试-{candidate_name}-{position}")
            .description(
                f"面试类型：{interview_type}\n"
                f"候选人：{candidate_name}\n"
                f"岗位：{position}\n"
                f"面试官：{interviewer_name}\n"
                f"地点：{location}\n"
                f"（此日程由 HR 系统自动创建）"
            )
            .start_time(
                EventTime.builder()
                .timestamp(str(int(start_time.timestamp())))
                .timezone("Asia/Shanghai")
                .build()
            )
            .end_time(
                EventTime.builder()
                .timestamp(str(int(end_time.timestamp())))
                .timezone("Asia/Shanghai")
                .build()
            )
            .organizer(
                EventOrganizer.builder().open_id(interviewer_open_id).build()
            )
            .attendees(attendees if attendees else None)
            .location(location)
            .need_notification(True)
            .build()
        )

        # 本仓 lark_oapi 版本的 request_body 直接收 CalendarEvent（无 *RequestBody 包装类，
        # 旧代码导入的 CreateCalendarEventRequestBody 在该版本不存在 → ImportError，
        # 惰性导入使日程同步一直静默失败）
        request = (
            CreateCalendarEventRequest.builder()
            .calendar_id(self._calendar_id)
            .request_body(event)
            .build()
        )

        response = await asyncio.to_thread(self._client.calendar.v4.calendar_event.create, request)
        if not response.success():
            msg = f"创建飞书日历事件失败: code={response.code}, msg={response.msg}"
            logger.error(msg)
            raise RuntimeError(msg)

        event_id = response.data.event.event_id
        logger.info("已为面试 %s 创建飞书日历事件 %s", interview_id, event_id)
        return event_id

    async def update_interview_event(
        self,
        event_id: str,
        *,
        interview_date_val: date | None = None,
        location: str | None = None,
        interviewer_name: str | None = None,
    ) -> None:
        """更新日历事件（日期 / 地点 / 面试官变更时调用）。"""
        event_builder = CalendarEvent.builder()

        if interview_date_val:
            start_time = datetime.combine(
                interview_date_val,
                datetime.strptime("09:00", "%H:%M").time(),
                tzinfo=ZoneInfo("Asia/Shanghai"),
            )
            end_time = start_time + timedelta(hours=1)
            event_builder.start_time(
                EventTime.builder()
                .timestamp(str(int(start_time.timestamp())))
                .timezone("Asia/Shanghai")
                .build()
            )
            event_builder.end_time(
                EventTime.builder()
                .timestamp(str(int(end_time.timestamp())))
                .timezone("Asia/Shanghai")
                .build()
            )

        if location:
            event_builder.location(location)

        if interviewer_name:
            open_id = await self._lookup_open_id(interviewer_name)
            if open_id:
                event_builder.attendees(
                    [{"type": "user", "user_id": open_id}]
                )
            else:
                # 新面试官解析不到：显式清空参会人，避免日程残留旧面试官
                event_builder.attendees([])

        request = (
            PatchCalendarEventRequest.builder()
            .calendar_id(self._calendar_id)
            .event_id(event_id)
            .request_body(event_builder.build())
            .build()
        )

        response = await asyncio.to_thread(self._client.calendar.v4.calendar_event.patch, request)
        if not response.success():
            logger.warning(
                "更新日历事件失败: code=%s, msg=%s (事件 %s)",
                response.code, response.msg, event_id,
            )

    async def delete_interview_event(self, event_id: str) -> None:
        """删除日历事件（面试取消时调用）。"""
        request = (
            DeleteCalendarEventRequest.builder()
            .calendar_id(self._calendar_id)
            .event_id(event_id)
            .build()
        )

        response = await asyncio.to_thread(self._client.calendar.v4.calendar_event.delete, request)
        if not response.success():
            logger.warning(
                "删除日历事件失败: code=%s, msg=%s (事件 %s，可能已被手动删除)",
                response.code, response.msg, event_id,
            )

    async def _lookup_open_id(self, name: str) -> str | None:
        """通过姓名查找飞书 open_id（从 identity.users 表查询）。

        同名多账户时按 created_at 取最早一个（保证结果确定，不再随机命中），
        并记录告警提示治理重复账户。
        """
        if not name or name == "未指定":
            return None
        try:
            from sqlalchemy import text

            from app.core.database import async_session_factory

            async with async_session_factory() as db:
                r = await db.execute(
                    text(
                        "SELECT feishu_open_id FROM identity.users "
                        "WHERE name = :name AND is_deleted = false "
                        "ORDER BY created_at LIMIT 2"
                    ),
                    {"name": name},
                )
                rows = r.fetchall()
                if len(rows) > 1:
                    logger.warning("系统用户「%s」存在 %d 条同名记录，日程参与人取最早一条", name, len(rows))
                if rows and rows[0][0]:
                    return rows[0][0]
            logger.warning("未找到系统用户 %s 的 open_id，跳过添加为参与人", name)
            return None
        except Exception as e:
            logger.warning("查找 open_id 失败(%s): %s", name, e)
            return None
