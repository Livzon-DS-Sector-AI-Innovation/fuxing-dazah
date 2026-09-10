"""职业健康异常随访 Service — CRUD / 到期派生 / 关闭闭环 / AI 自动生成 / 手动补录。

对齐 backend-design.md §5.3：
- 状态机 open → followed → closed；expired 为列表查询时派生的只读展示状态（不落库）；
- 到期派生：status=open 且 followup_date < today → 展示为 expired（列表查询时计算）；
- 关闭闭环：close_followup 写 closed_at + action_taken，仅 followed → closed；
- 处置流转：update_followup 填 action_taken 或显式 status=followed 时 open → followed；
- AI 联动：create_from_exam(exam_id) / create_followup_from_ai(indicators, exam)，
  由 ticket 04（OhAIService.parse_exam_report 落库后）调用，source='ai_parse'；
- 手动补录：create_followup（API 创建），source='manual'，exam_id 或 person_id 必填其一；
- 唯一键 exam_id+indicator_name 去重（软删时清空，见 repository.delete_oh_followup）。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.modules.safety.models import OhFollowup, OhHealthExam
from app.modules.safety.repository import SafetyRepository
from app.modules.safety.schemas.oh_followups import OhFollowupCreate, OhFollowupUpdate
from app.modules.safety.service._helpers import audit_log, json_safe

logger = logging.getLogger(__name__)

# followup_suggestion 关键字 → followup_type 标准枚举
_FOLLOWUP_TYPE_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("复查", "复检", "re_exam", "recheck", "re-check"), "re_examination"),
    (("转诊", "专科", "referral", "specialist"), "specialist_referral"),
    (("调离", "转岗", "脱离", "transfer"), "transfer_post"),
    (("监护", "监测", "随访", "monitor"), "health_monitor"),
]

# followup_type → 建议处置日期偏移（相对体检日期）
_FOLLOWUP_DATE_OFFSET_DAYS: dict[str, int] = {
    "re_examination": 30,
    "specialist_referral": 7,
}


class OhFollowupService:
    """职业健康异常随访服务"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SafetyRepository(session)

    async def _audit(
        self,
        action: str,
        resource_type: str,
        resource_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        old_value: dict[str, Any] | None = None,
        new_value: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        await audit_log(
            self.session,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            old_value=json_safe(old_value),
            new_value=json_safe(new_value),
            extra=json_safe(extra),
        )

    async def _get_followup(self, followup_id: uuid.UUID) -> OhFollowup | None:
        """取活随访记录（排除软删）"""
        row = await self.session.get(OhFollowup, followup_id)
        if row is None or row.is_deleted:
            return None
        return row

    # ── 查询 ──

    async def get_followups(
        self,
        *,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        category: str | None = None,
        person_id: uuid.UUID | None = None,
        due_order: bool = True,
    ) -> tuple[list[OhFollowup], int]:
        """随访列表（筛选 + 到期排序 + expired 派生展示）"""
        items, total = await self.repo.get_oh_followups(
            skip=skip,
            limit=limit,
            status=status,
            category=category,
            person_id=person_id,
            due_order=due_order,
        )
        self._derive_expired(items)
        return items, total

    async def get_followup(self, followup_id: uuid.UUID) -> OhFollowup | None:
        """随访详情"""
        return await self._get_followup(followup_id)

    @staticmethod
    def _derive_expired(items: list[OhFollowup]) -> None:
        """到期派生：status=open 且 followup_date < today → 展示为 expired。

        仅内存改写（set_committed_value 不标记 dirty，避免 GET 请求误触发 autoflush 落库）。
        """
        today = date.today()
        for item in items:
            if item.status == "open" and item.followup_date and item.followup_date < today:
                set_committed_value(item, "status", "expired")

    # ── 手动补录 ──

    async def create_followup(
        self, data: OhFollowupCreate, *, user_id: uuid.UUID | None = None
    ) -> OhFollowup:
        """手动补录随访（source='manual'，status='open'，exam_id 或 person_id 必填其一）"""
        payload = data.model_dump(mode="python")
        if not payload.get("exam_id") and not payload.get("person_id"):
            raise ValueError("exam_id 与 person_id 至少填其一")
        if not payload.get("indicator_name"):
            raise ValueError("indicator_name（异常指标名）必填")

        if payload.get("exam_id"):
            exam = await self.session.get(OhHealthExam, payload["exam_id"])
            if exam and not exam.is_deleted:
                if not payload.get("person_id"):
                    payload["person_id"] = exam.person_id
                if not payload.get("person_name"):
                    payload["person_name"] = exam.employee_name
        if payload.get("person_id") and not payload.get("person_name"):
            person = await self.repo.get_oh_person_by_id(payload["person_id"])
            if person:
                payload["person_name"] = person.name

        # 唯一键去重（同一体检同一异常指标只允许一条活记录）
        if payload.get("exam_id") and payload.get("indicator_name"):
            dup = await self.repo.get_oh_followup_by_exam_indicator(
                payload["exam_id"], payload["indicator_name"]
            )
            if dup:
                raise ValueError("该体检的此异常指标已存在随访记录")

        payload["source"] = "manual"
        payload["status"] = "open"
        payload["closed_at"] = None
        item = await self.repo.create_oh_followup(payload)
        await self._audit(
            "create", "oh_followup", resource_id=item.id,
            user_id=user_id, new_value=payload,
        )
        return item

    # ── 处置更新（open → followed）──

    async def update_followup(
        self,
        followup_id: uuid.UUID,
        data: OhFollowupUpdate,
        *,
        user_id: uuid.UUID | None = None,
    ) -> OhFollowup | None:
        """更新随访（处置记录 action_taken 或显式 status=followed → open 流转 followed）。

        状态机校验：closed 为终态不可再改；expired 为派生状态不可写入；
        followed 不可回退 open；open 不可直接 closed（须走关闭接口）。
        """
        row = await self._get_followup(followup_id)
        if not row:
            return None
        update_data = {
            k: v for k, v in data.model_dump(exclude_unset=True, mode="python").items()
            if v is not None
        }
        if not update_data:
            return row

        new_status = update_data.pop("status", None)
        if new_status == "expired":
            raise ValueError("expired 为到期派生状态，不可手动设置")
        if update_data.pop("closed_at", None) is not None:
            raise ValueError("closed_at 由关闭接口写入，不可直接修改")

        current = row.status
        if current == "closed":
            raise ValueError("已关闭的随访不可再更新")
        if new_status is None and update_data.get("action_taken") and current == "open":
            new_status = "followed"  # 填写处置记录 → 自动流转 followed
        if new_status and new_status != current:
            if current == "open" and new_status not in ("open", "followed"):
                raise ValueError(f"非法状态流转: {current} → {new_status}（仅 open→followed）")
            if current == "followed" and new_status != "followed":
                raise ValueError(f"非法状态流转: {current} → {new_status}（请使用关闭接口）")
            update_data["status"] = new_status
        if not update_data:
            return row

        item = await self.repo.update_oh_followup(followup_id, update_data)
        if item:
            await self._audit(
                "update", "oh_followup", resource_id=followup_id, user_id=user_id,
                old_value={"status": current},
                new_value={**update_data, "status": item.status},
            )
        return item

    # ── 关闭闭环（followed → closed）──

    async def close_followup(
        self,
        followup_id: uuid.UUID,
        *,
        action_taken: str,
        user_id: uuid.UUID | None = None,
    ) -> OhFollowup | None:
        """关闭随访：followed → closed，写 closed_at + action_taken。"""
        row = await self._get_followup(followup_id)
        if not row:
            return None
        if not action_taken or not action_taken.strip():
            raise ValueError("action_taken（处置记录）必填")
        if row.status == "closed":
            raise ValueError("随访已关闭，不可重复关闭")
        if row.status != "followed":
            raise ValueError(f"非法状态流转: {row.status} → closed（须先处置 open→followed）")

        item = await self.repo.update_oh_followup(followup_id, {
            "status": "closed",
            "action_taken": action_taken,
            "closed_at": datetime.now(UTC),
        })
        if item:
            await self._audit(
                "close", "oh_followup", resource_id=followup_id, user_id=user_id,
                old_value={"status": "followed"},
                new_value={"status": "closed", "action_taken": action_taken},
            )
        return item

    # ── AI 联动（ticket 04 调用）──

    async def create_from_exam(self, exam_id: uuid.UUID) -> list[OhFollowup]:
        """按体检记录自动生成异常随访（source='ai_parse'）。

        设计 §4.2 工作流① step 10：AI 解析落库（ai_parse_result.abnormal_indicators）后调用；
        幂等：唯一键 exam_id+indicator_name 已存在的活记录跳过。
        """
        exam = await self.session.get(OhHealthExam, exam_id)
        if not exam or exam.is_deleted:
            return []
        parse_result = exam.ai_parse_result or {}
        indicators = parse_result.get("abnormal_indicators") or []
        return await self.create_followup_from_ai(indicators, exam)

    async def create_followup_from_ai(
        self, indicators: list[Any], exam: OhHealthExam
    ) -> list[OhFollowup]:
        """从 AI 解析出的异常指标生成随访（status='open'，source='ai_parse'）。

        indicators 兼容 Pydantic 模型（OhAbnormalIndicator）或 dict：
        name/value/reference_range/category/severity/followup_suggestion。
        followup_type 由 followup_suggestion 关键字映射；
        followup_date 派生：re_examination → 体检日+30 天；specialist_referral → +7 天。
        """
        if not indicators or not exam.id:
            return []
        created: list[OhFollowup] = []
        for raw in indicators:
            indicator = self._normalize_indicator(raw)
            name = indicator.get("name") or ""
            if not name:
                continue
            if await self.repo.get_oh_followup_by_exam_indicator(exam.id, name):
                continue  # 唯一键去重（重复解析不叠加）
            followup_type = self._map_followup_type(indicator.get("followup_suggestion"))
            item = await self.repo.create_oh_followup({
                "exam_id": exam.id,
                "person_id": exam.person_id,
                "person_name": exam.employee_name,
                "indicator_name": name[:100],
                "indicator_value": (indicator.get("value") or "")[:100],
                "reference_range": (indicator.get("reference_range") or "")[:100],
                "abnormal_level": indicator.get("severity"),
                "category": indicator.get("category"),
                "followup_type": followup_type,
                "followup_date": self._derive_followup_date(exam, followup_type),
                "status": "open",
                "source": "ai_parse",
            })
            created.append(item)
        if created:
            await self._audit(
                "create", "oh_followup", resource_id=exam.id,
                extra={"source": "ai_parse", "exam_id": str(exam.id), "count": len(created)},
            )
        return created

    @staticmethod
    def _normalize_indicator(raw: Any) -> dict[str, Any]:
        """归一 AI 异常指标（Pydantic 模型或 dict 均可）"""
        if isinstance(raw, dict):
            return raw
        return {
            key: getattr(raw, key, None)
            for key in (
                "name", "value", "reference_range", "category",
                "severity", "followup_suggestion",
            )
        }

    @classmethod
    def _map_followup_type(cls, suggestion: str | None) -> str:
        """followup_suggestion 关键字 → followup_type 标准枚举（兜底 re_examination 复查）"""
        text_ = (suggestion or "").lower()
        for keywords, followup_type in _FOLLOWUP_TYPE_KEYWORDS:
            if any(k in text_ for k in keywords):
                return followup_type
        return "re_examination"

    @staticmethod
    def _derive_followup_date(exam: OhHealthExam, followup_type: str) -> date | None:
        """派生建议处置日期：re_examination → 体检日+30 天；specialist_referral → +7 天。"""
        days = _FOLLOWUP_DATE_OFFSET_DAYS.get(followup_type)
        if days is None:
            return None
        base = exam.exam_date or exam.report_date or exam.scheduled_date
        if base is None:
            return None
        return base.date() + timedelta(days=days)

    # ── 到期派生（二期占位，本期列表查询时派生，不落库）──
    # async def mark_expired(self) -> int: ...
