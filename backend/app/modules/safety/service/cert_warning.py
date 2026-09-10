"""持证到期预警引擎与服务（纯引擎 + 编排层）。

对齐 spec.md §预警引擎与 backend-design.md §5：6 档等级 + 特种作业证 vs
监护人 A/B 证节点判断。可被 API、定时任务、Agent 工具复用。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.repository import PersonCertificateRepository
from app.modules.safety.schemas.cert_warnings import (
    CertWarningDetail,
    CertWarningSummary,
    RenewRequest,
    WarningLevel,
)
from app.modules.safety.service._helpers import audit_log, json_safe


@dataclass
class WarningResult:
    """引擎输出（spec §测试主接缝）"""
    status: str            # normal/early_notice/to_schedule/key_warning/urgent/overdue
    remaining_days: int | None   # None = 无法计算（缺日期）
    current_node: str | None      # 节点描述（如 "复审" / "第一次复审" / "第二次复审" / "换证"）
    deadline: date | None         # 当前节点截止日期
    suggestion: str | None        # 建议措施文案


class CertWarningEngine:
    """持证到期预警引擎（纯函数，无 DB / 无 IO）。

    输入 record 用 duck typing（访问 record.cert_category 等），不依赖 ORM 模型。
    """

    # 6 档阈值（spec 需求文档：>90 / 61-90 / 31-60 / 8-30 / 0-7 / <0）
    # 逐档取第一个 ≥ threshold 的档位（90 < 91 阈值 → early_notice）
    LEVELS: list[tuple[int, str]] = [
        (91, "normal"),          # >90
        (61, "early_notice"),    # 61-90
        (31, "to_schedule"),     # 31-60
        (8, "key_warning"),      # 8-30
        (0, "urgent"),           # 0-7
        (-9999, "overdue"),      # <0
    ]

    # 监护人证复审/换证周期常量（待 Bitable 字段结构确认后校准，见 _guardian_node TODO）
    _GUARDIAN_PERIODS: dict[str, timedelta] = {
        "first_review": timedelta(days=365 * 3),   # 占位：3 年
        "second_review": timedelta(days=365 * 6),  # 占位：6 年
        "renew": timedelta(days=365 * 6),          # 占位：6 年
    }

    @staticmethod
    def _level(remaining: int) -> str:
        """按剩余天数返回 6 档等级（含边界：-1 → overdue）。"""
        for threshold, name in CertWarningEngine.LEVELS:
            if remaining >= threshold:
                return name
        return "overdue"

    @staticmethod
    def _suggestion(level: str, cert_category: str) -> str:
        """按等级 + 类别生成建议措施文案（纯文案，无副作用）。"""
        if level == "normal":
            return "证件状态正常，无需处理"
        if level == "early_notice":
            return "证件尚在有效期内，建议提前关注后续节点安排"
        if level == "to_schedule":
            return "证件临近节点，建议尽快安排复审/换证计划"
        if level == "key_warning":
            return "证件已进入重点预警窗口，请及时安排复审/换证"
        if level == "urgent":
            return "证件即将到期，请立即安排复审/换证"
        if level == "overdue":
            return "证件已逾期，请立即处理并完成有效手续"
        return "请核查证件状态"

    @staticmethod
    def calculate(record: Any, today: date | None = None) -> WarningResult:
        """核心算法（伪代码见 backend-design.md §5.1.1）。

        Args:
            record: 持证记录（duck typing，读 cert_category / review_frequency /
                    next_review_date / first_review_deadline / second_review_deadline /
                    should_renew_date / renewed_date / issue_date）。
            today: 基准日（默认取 date.today()）。

        Returns:
            WarningResult: 预警结果（status / remaining_days / current_node /
            deadline / suggestion）。
        """
        today = today or date.today()
        cat = record.cert_category
        node: str | None = None

        # ── 特种作业证：无需复审 → normal ──
        if cat == "special_op":
            if (record.review_frequency or "").strip() in ("无需复审", "无", "不需要"):
                return WarningResult(
                    "normal", None, "无需复审", None,
                    "证件无需复审，长期有效",
                )
            deadline = record.next_review_date
            node = "复审"
        else:  # guardian_a / guardian_b
            _g = CertWarningEngine._guardian_node(record, today)
            deadline = _g[0]
            node = _g[1]

        if deadline is None:
            return WarningResult(
                "normal", None, None, None,
                "缺少日期字段，无法计算预警",
            )
        remaining = (deadline - today).days
        level = CertWarningEngine._level(remaining)
        return WarningResult(
            status=level,
            remaining_days=remaining,
            current_node=node,
            deadline=deadline,
            suggestion=CertWarningEngine._suggestion(level, cat),
        )

    @staticmethod
    def _guardian_node(record: Any, today: date) -> tuple[date | None, str | None]:
        """监护人 A/B 证当前节点判断（backend-design.md §5.1）。

        算法：
          1. renewed_date 非空 → 已换证，以 renewed_date 为新 issue_date 重算下一周期
             （若 Bitable 只给 issue_date + 周期常量，用 _GUARDIAN_PERIODS 推导各节点；
               当前先直接读 Bitable 的 first/second/should_renew 字段）
          2. 依次判断 first_review_deadline → second_review_deadline → should_renew_date，
             取第一个 ≥ today（未过期且最近）的作为当前节点；
             若全部 < today（都已逾期）→ 取 should_renew_date（已逾期换证，最严重）。

        Returns:
            (deadline, node): 当前节点截止日期 + 节点描述。
        """
        # ── 回填重算：renewed_date 非空则以它为新 issue_date 推算下一周期 ──
        renewed = record.renewed_date
        if renewed is not None:
            # 以 renewed_date 为新 issue_date，按周期常量推导下一周期各节点
            c = CertWarningEngine._GUARDIAN_PERIODS
            return (
                renewed + c["first_review"],
                "第一次复审",
            )

        # 基线：issue_date（若字段全空）
        issue = record.issue_date
        if issue is not None:
            # TODO(字段确认后补)：若 Bitable 只给 issue_date + 周期常量，
            #   需在此用 _GUARDIAN_PERIODS 推导 first/second/renew
            #   （当前先直接读 Bitable 的 first/second/should_renew 字段）
            pass

        # 候选节点列表
        candidates: list[tuple[date | None, str]] = [
            (record.first_review_deadline, "第一次复审"),
            (record.second_review_deadline, "第二次复审"),
            (record.should_renew_date, "换证"),
        ]
        # 取第一个未过期且最近
        for d, node in candidates:
            if d is not None and d >= today:
                return d, node
        # 全部已逾期或缺失 → 取最后一个非空节点（最严重，已逾期换证）
        for d, node in reversed(candidates):
            if d is not None:
                return d, f"{node}（已逾期）"
        return None, None


class CertWarningService:
    """持证到期预警编排服务（API + 定时任务 + Agent 工具共用）。

    参考 oh_followup.py 的 _audit 模式（复用 _helpers.audit_log + json_safe）。
    预警等级由 CertWarningEngine.calculate() 在 Python 层派生，不落 SQL。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PersonCertificateRepository(session)

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

    @staticmethod
    def _event_key(cert_category: str, current_node: str | None) -> str:
        """把类别 + 节点描述归一为统计键（如 special_op_review / guardian_a_first_review）.

        节点描述可能含「（已逾期）」后缀，剥离后按前缀映射为规范键。
        """
        node = (current_node or "").strip()
        for suffix in ("（已逾期）", "已逾期", ")"):
            node = node.replace(suffix, "")
        node = node.replace("（", "").replace("）", "")
        return f"{cert_category}_{node or 'unknown'}"

    # ── 查询 ──

    async def get_warnings(
        self,
        *,
        skip: int = 0,
        limit: int = 20,
        status_level: str | None = None,
        department: str | None = None,
        cert_category: str | None = None,
        days_within: int | None = None,
    ) -> tuple[list[CertWarningDetail], int]:
        """到期明细列表（引擎派生 + 过滤 + 分页）。

        SQL 只做基础过滤（is_deleted/dept/category）；status_level / days_within
        在 Python 层用引擎派生结果过滤后切片。
        """
        rows, _ = await self.repo.get_warnings(
            department=department, cert_category=cert_category,
        )
        today = date.today()
        details: list[CertWarningDetail] = []
        for r in rows:
            res = CertWarningEngine.calculate(r, today)
            d = CertWarningDetail.model_validate(r)
            d.current_node = res.current_node
            d.deadline = res.deadline
            d.remaining_days = res.remaining_days
            d.status_level = WarningLevel(res.status)
            d.suggestion = res.suggestion
            details.append(d)
        # Python 层过滤（status_level / days_within）
        if status_level:
            details = [d for d in details if d.status_level == status_level]
        if days_within is not None:
            details = [
                d for d in details
                if d.remaining_days is not None and d.remaining_days <= days_within
            ]
        total = len(details)
        items = details[skip: skip + limit]
        return items, total

    async def get_summary(
        self, *, department: str | None = None, cert_category: str | None = None
    ) -> CertWarningSummary:
        """汇总：6 档人数 + by_category + by_event。"""
        rows, _ = await self.repo.get_warnings(
            department=department, cert_category=cert_category,
        )
        today = date.today()
        s = CertWarningSummary()
        for r in rows:
            res = CertWarningEngine.calculate(r, today)
            s.total += 1
            s.by_category[r.cert_category] = s.by_category.get(r.cert_category, 0) + 1
            event_key = self._event_key(r.cert_category, res.current_node)
            s.by_event[event_key] = s.by_event.get(event_key, 0) + 1
            match res.status:
                case "overdue":
                    s.overdue_count += 1
                case "urgent":
                    s.urgent_count += 1
                case "key_warning":
                    s.key_warning_count += 1
                case "to_schedule":
                    s.to_schedule_count += 1
                case "early_notice":
                    s.early_notice_count += 1
                case "normal":
                    s.normal_count += 1
        return s

    # ── 回填闭环 ──

    async def renew(
        self,
        cert_id: uuid.UUID,
        data: RenewRequest,
        *,
        user_id: uuid.UUID | None = None,
    ) -> CertWarningDetail | None:
        """回填复审/换证结果 → 进入下一周期 → 刷新预警。

        校验：
          - renewed_date / next_review_date 二选一（均空 → ValueError）
          - cert_category == special_op → 只接受 next_review_date
          - cert_category in (guardian_a, guardian_b) → 只接受 renewed_date
          - 回填日期不能晚于今天 +30（防误填远期，宽松校验）
        写：UPDATE（renewed_date 或 next_review_date + notes）→ re-fetch → 审计
        → 返回派生后 Detail。
        """
        row = await self.repo.get_by_id(cert_id)
        if not row:
            return None
        payload = data.model_dump(exclude_unset=True, mode="python")
        renewed = payload.get("renewed_date")
        next_review = payload.get("next_review_date")
        # 二选一校验：均空 → 拒绝
        if renewed is None and next_review is None:
            raise ValueError("renewed_date 与 next_review_date 须二选一")
        cat = row.cert_category
        if cat == "special_op" and renewed is not None:
            raise ValueError("特种作业证只接受 next_review_date（再复审时间）")
        if cat in ("guardian_a", "guardian_b") and next_review is not None:
            raise ValueError("监护人证只接受 renewed_date（已换证日期）")
        # 回填日期不能晚于今天 +30（宽松防误填）
        today = date.today()
        if renewed is not None and renewed > today + timedelta(days=30):
            raise ValueError("renewed_date 不能晚于今天 +30 天")
        if next_review is not None and next_review > today + timedelta(days=30):
            raise ValueError("next_review_date 不能晚于今天 +30 天")

        old = {
            "renewed_date": row.renewed_date,
            "next_review_date": row.next_review_date,
        }
        updated = await self.repo.renew(cert_id, payload)  # UPDATE re-fetch
        if updated is None:
            return None
        await self._audit(
            "renew", resource_type="person_certificate",
            resource_id=cert_id, user_id=user_id,
            old_value=old, new_value=payload,
            extra={"cert_category": cat},
        )
        # 返回刷新后的派生 Detail
        res = CertWarningEngine.calculate(updated)
        d = CertWarningDetail.model_validate(updated)
        d.current_node = res.current_node
        d.deadline = res.deadline
        d.remaining_days = res.remaining_days
        d.status_level = WarningLevel(res.status)
        d.suggestion = res.suggestion
        return d
