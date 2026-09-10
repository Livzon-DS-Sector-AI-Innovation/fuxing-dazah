"""职业健康转岗/离岗危害差异分析 Service（AI 工作流②）。

对齐 backend-design.md §4.3：
- OhTransferDiffOutput 输出 schema（Pydantic v2）；
- analyze_transfer_diff：old/new 危害集合运算（标准名 42 项字典）+ AI 语义补充判断
  （scenario=oh_transfer_hazard_diff，system 稳定 prompt + user 变量末尾，前缀缓存友好）；
- new_ppe_required 从 oh_hazard_factors 表取（get_ppe_map），user 消息内嵌因子→PPE 对照表，
  落库前以代码结果覆盖，禁止 AI 编造 PPE 型号；
- needs_exam=True → OhHealthExamService.ensure_exam_for_application
  （D7：申请表 created 已由 create_from_source 建登记，此处更新已建登记（needs_exam 标记）
  不重复新建；手工申请/兜底才新建，流程状态=未体检，体检类型=转岗体检/离岗体检）；
- 回写 Bitable 申请表「差异分析结论」「是否需体检」「建议」三字段（_set_sync_ignore 防循环）。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import OhExamApplication, OhHealthExam, OhPerson
from app.modules.safety.service._helpers import audit_log, json_safe

logger = logging.getLogger(__name__)

# ── 差异分析输出 schema ──


class OhTransferDiffOutput(BaseModel):
    """转岗/离岗危害差异分析输出（对齐 backend-design.md §4.1）"""

    added_hazards: list[str] = Field(..., description="新增危害（标准名，新有旧无）")
    removed_hazards: list[str] = Field(..., description="移除危害（标准名，旧有新无）")
    new_ppe_required: list[dict[str, str]] = Field(..., description="新危害对应 PPE [{factor, ppe}]（从 oh_hazard_factors 取）")
    key_followup_items: list[str] = Field(..., description="重点复查项")
    needs_exam: bool = Field(..., description="是否需体检")
    exam_type_suggestion: str = Field(..., description="pre_employment/periodic/transfer/post_employment")
    health_advice: str = Field(..., description="健康建议")
    summary: str = Field(..., description="差异分析摘要（回写 Bitable「差异分析结论」）")


# ── system prompt（稳定，遵守前缀缓存铁律：system 固定、变量放 user 末尾）──

OH_TRANSFER_DIFF_SYSTEM_PROMPT = """你是职业健康评估师，依据《GBZ 188 职业健康监护技术规范》对转岗/离岗人员的危害因素变化进行差异分析与健康风险评估。

## 输入说明
用户会提供：
- 员工基本信息（姓名/原部门岗位/新部门岗位/接害工龄/最近体检类型）；
- 原岗位危害因素列表（标准名）；
- 新岗位危害因素列表（标准名）；
- 代码已完成的集合运算结果：新增危害（新有旧无）、移除危害（旧有新无）；
- 最近一次体检的 AI 结论与职业禁忌证因素（无 AI 结论则为检查结论原文）；
- 危害因素→防护用品（PPE）对照表（来自企业 PPE 台账，仅此表为 PPE 取值来源）。

## 输出字段（只输出 JSON 对象）
- added_hazards: list[str] 新增危害标准名。沿用输入中的集合运算结果，不得增删改。
- removed_hazards: list[str] 移除危害标准名。沿用输入中的集合运算结果，不得增删改。
- new_ppe_required: list[{factor, ppe}] 新增危害对应的防护用品。只能从输入的对照表中取值；
  对照表无该因子或 PPE 为空时，该项输出 {"factor": "因子名", "ppe": ""}，禁止编造 PPE 型号。
- key_followup_items: list[str] 重点复查项。结合最近体检异常指标/职业禁忌证因素与新增危害的
  叠加风险给出，如「听力异常+新增噪声接触，建议复查纯音听阈」「肝功能异常+新增甲醇接触，
  建议复查肝功能」；无异常风险时可为空数组。
- needs_exam: bool 是否需体检。以下任一情形应判定 true：
  1) 新增危害（added_hazards 非空）；
  2) 最近体检存在职业禁忌证或异常指标，且与新岗位危害相关；
  3) 离岗人员（post_employment）从未做过离岗体检；
  4) 接害工龄较长（≥10 年）且近期无体检记录。
- exam_type_suggestion: str 建议体检类型：pre_employment（岗前）/ periodic（在岗期间）/
  transfer（转岗）/ post_employment（离岗）。转岗接触新增危害建议 transfer；离岗建议
  post_employment；无新增危害仅常规监测可建议 periodic。
- health_advice: str 健康建议。结合新增危害防护与体检异常给出可执行建议文本（防护佩戴、
  作业前中后注意事项、复查安排等）。
- summary: str 差异分析结论摘要（80~200 字，面向管理人员的中文结论性描述），说明新增/移除
  危害、叠加风险判断、是否需体检及建议类型，回写 Bitable「差异分析结论」。

## 判定规则
1. 危害因素标准名以输入列表为准（42 项标准字典），不得自创名称；
2. new_ppe_required 必须严格从对照表取值，禁止编造 PPE 型号；
3. 已异常指标与新增危害存在叠加风险时 needs_exam=true；
4. 转岗申请（transfer）通常建议 transfer 体检，离岗申请（post_employment）通常建议
   post_employment 体检；
5. summary 用中文，只输出 JSON 对象，禁止输出任何其他文字。"""


# ── 建议体检类型 → Bitable「建议」中文标签 ──

_EXAM_SUGGESTION_LABELS = {
    "pre_employment": "岗前体检",
    "periodic": "在岗期间体检",
    "transfer": "转岗体检",
    "post_employment": "离岗体检",
}


def _build_transfer_user_prompt(
    *,
    name: str,
    department: str | None,
    position: str | None,
    new_department: str | None,
    new_position: str | None,
    hazard_exposure_years: float | None,
    last_exam_type: str | None,
    old_hazards: list[str],
    new_hazards: list[str],
    added_hazards: list[str],
    removed_hazards: list[str],
    recent_exam_conclusion: str,
    ppe_map: dict[str, str],
) -> str:
    """组装 user 消息（变量全部放末尾，system 前缀保持稳定以命中 KV 前缀缓存）。"""
    ppe_lines = (
        "\n".join(f"- {f}：{ppe}" for f, ppe in ppe_map.items() if ppe)
        if ppe_map
        else "- （PPE 台账未配置）"
    )
    return f"""员工信息：
- 姓名：{name}
- 原部门/岗位：{department or "未填写"} / {position or "未填写"}
- 新部门/岗位：{new_department or "未填写"} / {new_position or "未填写"}
- 接害工龄：{hazard_exposure_years if hazard_exposure_years is not None else "未知"} 年
- 最近体检类型：{last_exam_type or "未知"}

原岗位危害因素（标准名）：{old_hazards if old_hazards else "（无登记）"}
新岗位危害因素（标准名）：{new_hazards if new_hazards else "（无登记）"}
集合运算结果：
- 新增危害（新有旧无）：{added_hazards if added_hazards else "（无）"}
- 移除危害（旧有新无）：{removed_hazards if removed_hazards else "（无）"}

最近体检结论：
{recent_exam_conclusion}

危害因素→防护用品对照表（PPE 仅可从此表取值，禁止编造）：
{ppe_lines}"""


class OhTransferService:
    """转岗/离岗危害差异分析服务"""

    def __init__(self, session: AsyncSession):
        self.session = session

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

    # ── 查询 ──

    async def get_applications(
        self,
        *,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        transfer_type: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[OhExamApplication], int]:
        """转岗/离岗申请列表（状态/类型筛选 + keyword + 分页）"""
        filters = [OhExamApplication.is_deleted == False]  # noqa: E712
        if status:
            filters.append(OhExamApplication.apply_status == status)
        if transfer_type:
            filters.append(OhExamApplication.transfer_type == transfer_type)
        if keyword:
            like = f"%{keyword}%"
            filters.append(
                or_(
                    OhExamApplication.application_no.ilike(like),
                    OhExamApplication.employee_name.ilike(like),
                    OhExamApplication.department.ilike(like),
                    OhExamApplication.new_department.ilike(like),
                )
            )
        total = await self.session.scalar(select(func.count(OhExamApplication.id)).where(*filters))
        query = (
            select(OhExamApplication)
            .where(*filters)
            .order_by(OhExamApplication.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all()), int(total or 0)

    async def get_application(self, application_id: uuid.UUID) -> OhExamApplication | None:
        """申请详情（含差异分析结果）。

        UPDATE 后必须 select re-fetch（CLAUDE.md async 铁律）：flush/commit 后
        onupdate 列（updated_at）处于 expired 状态，响应序列化阶段同步访问会触发
        MissingGreenlet；显式 select 重新查询保证返回对象属性全部 loaded。
        """
        result = await self.session.execute(
            select(OhExamApplication).where(
                OhExamApplication.id == application_id,
                OhExamApplication.is_deleted == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def get_stats(self) -> dict[str, Any]:
        """申请统计：total + 按申请状态分组 + 已分析中需体检数"""
        filters = [OhExamApplication.is_deleted == False]  # noqa: E712
        total = await self.session.scalar(
            select(func.count()).select_from(OhExamApplication).where(*filters)
        )
        status_rows = (
            await self.session.execute(
                select(OhExamApplication.apply_status, func.count())
                .where(*filters)
                .group_by(OhExamApplication.apply_status)
            )
        ).all()
        needs_exam = await self.session.scalar(
            select(func.count())
            .select_from(OhExamApplication)
            .where(
                OhExamApplication.is_deleted == False,  # noqa: E712
                OhExamApplication.needs_exam == True,  # noqa: E712
            )
        )
        return {
            "total": int(total or 0),
            "by_status": {k: int(v) for k, v in status_rows},
            "needs_exam": int(needs_exam or 0),
        }

    # ── AI 工作流②：转岗危害差异分析 ──

    async def analyze_transfer_diff(
        self,
        application_id: uuid.UUID,
        *,
        channel: str = "system",
        user_id: uuid.UUID | None = None,
        user_name: str | None = None,
    ) -> OhExamApplication | None:
        """转岗/离岗危害差异分析（scenario=oh_transfer_hazard_diff）。

        流程：输入组装（old/new hazards + 最近体检结论 + PPE 对照表）
          → 集合运算（代码完成，标准名）→ AI 语义补充判断
          → 落库 diff_* + 回写 Bitable 三字段（_set_sync_ignore 防循环）
          → needs_exam=True → ensure_exam_for_application（D7：更新已建体检登记，不重复新建）。
        """
        application = await self.get_application(application_id)
        if not application or application.is_deleted:
            return None

        # 防重：parsing 中跳过；system 自动触发不重跑已分析（手动 web 重试允许覆盖）
        if application.diff_analyze_status == "parsing":
            return application
        if channel == "system" and application.diff_analyze_status == "analyzed":
            return application

        # ── 1. 输入组装 ──
        old_hazards, new_hazards, recent_exam_conclusion, ppe_map, exposure_years, last_exam_type = (
            await self._collect_inputs(application)
        )

        # ── 2. 集合运算（代码权威：标准名 42 项字典，added = new - old, removed = old - new）──
        old_set = set(old_hazards)
        new_set = set(new_hazards)
        added_hazards = [f for f in new_hazards if f not in old_set]  # 保持 new 原序
        removed_hazards = [f for f in old_hazards if f not in new_set]  # 保持 old 原序

        # ── 3. parsing 状态落库（异步任务崩溃恢复可见）──
        application.diff_analyze_status = "parsing"
        application.diff_analyze_error = None
        await self.session.commit()
        application = await self.get_application(application_id)
        if not application:
            return None

        # ── 4. AI 调用（scenario 审计 + system 稳定 + user 变量末尾）──
        try:
            from app.modules.safety.ai_audit import ai_audit_scope
            from app.modules.safety.service.config import create_ai_service

            with ai_audit_scope(
                scenario="oh_transfer_hazard_diff",
                channel=channel,
                resource_type="oh_exam_application",
                resource_id=application_id,
                user_id=user_id,
                user_name=user_name,
            ):
                ai = create_ai_service("text")
                try:
                    result = await ai.chat_parsed(
                        messages=[
                            {"role": "system", "content": OH_TRANSFER_DIFF_SYSTEM_PROMPT},
                            {"role": "user", "content": _build_transfer_user_prompt(
                                name=application.employee_name or "未填写",
                                department=application.department,
                                position=application.position,
                                new_department=application.new_department,
                                new_position=application.new_position,
                                hazard_exposure_years=exposure_years,
                                last_exam_type=last_exam_type,
                                old_hazards=old_hazards,
                                new_hazards=new_hazards,
                                added_hazards=added_hazards,
                                removed_hazards=removed_hazards,
                                recent_exam_conclusion=recent_exam_conclusion,
                                ppe_map=ppe_map,
                            )},
                        ],
                        expected_keys=[
                            "added_hazards", "removed_hazards", "new_ppe_required",
                            "key_followup_items", "needs_exam", "exam_type_suggestion",
                            "health_advice", "summary",
                        ],
                        temperature=0.1,
                    )
                finally:
                    await ai.close()
            diff = OhTransferDiffOutput.model_validate(result)

            # 权威字段以代码结果覆盖（AI 不得改集合运算结果 / 不得编造 PPE）
            diff.added_hazards = added_hazards
            diff.removed_hazards = removed_hazards
            diff.new_ppe_required = [
                {"factor": f, "ppe": ppe_map.get(f, "")} for f in added_hazards
            ]
        except Exception as e:
            logger.exception("转岗差异分析 AI 调用失败: application=%s", application_id)
            application.diff_analyze_status = "failed"
            application.diff_analyze_error = str(e)[:2000]
            await self.session.commit()
            return await self.get_application(application_id)

        # ── 5. 落库 diff_* ──
        application.diff_analyze_result = diff.model_dump(mode="json")
        application.diff_summary = diff.summary
        application.needs_exam = diff.needs_exam
        application.exam_suggestion = diff.exam_type_suggestion

        # ── 6. needs_exam=True → 确保体检登记存在（D7：申请表 created 已建登记，
        #        此处仅更新已建登记（needs_exam 标记），不重复新建；失败不阻塞分析完成）──
        if diff.needs_exam:
            try:
                from app.modules.safety.service.oh_health_exam import (
                    OhHealthExamService,
                )

                exam = await OhHealthExamService(self.session).ensure_exam_for_application(
                    application_id
                )
                if exam is not None and application.created_exam_id != exam.id:
                    application.created_exam_id = exam.id
                    logger.info(
                        "转岗差异分析体检登记就绪: application=%s exam=%s（已建则更新，不新建）",
                        application_id, exam.id,
                    )
            except Exception:
                logger.exception(
                    "转岗差异分析体检登记联动失败: application=%s", application_id
                )

        application.diff_analyze_status = "analyzed"
        application.diff_analyze_error = None
        await self.session.commit()

        # ── 7. 回写 Bitable 三字段（独立事务 + _set_sync_ignore 防循环，失败仅告警）──
        await self._sync_bitable_application(application)

        await self._audit(
            "analyze", "oh_exam_application", resource_id=application_id,
            user_id=user_id,
            extra={"channel": channel, "needs_exam": diff.needs_exam},
        )
        return await self.get_application(application_id)

    async def _collect_inputs(
        self, application: OhExamApplication
    ) -> tuple[list[str], list[str], str, dict[str, str], float | None, str | None]:
        """工作流②输入组装：

        old_hazards：按原部门+原岗位查 oh_positions，缺省取人员冗余 hazard_factors；
        new_hazards：按新部门+新岗位查 oh_positions；
        recent_exam_conclusion：最新体检 ai_conclusion + ai_contraindication_factors，无则原文；
        ppe_map：oh_hazard_factors 因子→PPE 对照表（禁止 AI 编造 PPE 型号）。
        """
        from app.modules.safety.service.oh_hazard_factor import OhHazardFactorService
        from app.modules.safety.service.oh_health_exam import OhHealthExamService
        from app.modules.safety.service.oh_position import OhPositionService

        old_hazards = await OhPositionService(self.session).get_hazards_by_position(
            application.department, application.position
        )

        person: OhPerson | None = None
        if application.employee_name:
            person = await self.session.scalar(
                select(OhPerson).where(
                    OhPerson.name == application.employee_name,
                    OhPerson.is_deleted == False,  # noqa: E712
                ).order_by(OhPerson.created_at.desc()).limit(1)
            )
            if person is not None and application.id_card_no:
                person = await self.session.scalar(
                    select(OhPerson).where(
                        OhPerson.name == application.employee_name,
                        OhPerson.id_card_no == application.id_card_no,
                        OhPerson.is_deleted == False,  # noqa: E712
                    ).order_by(OhPerson.created_at.desc()).limit(1)
                )

        # 缺省：oh_positions 未登记 → 取人员冗余 hazard_factors
        if not old_hazards and person is not None and person.hazard_factors:
            old_hazards = list(person.hazard_factors)

        new_hazards = await OhPositionService(self.session).get_hazards_by_position(
            application.new_department, application.new_position
        )

        recent_exam: OhHealthExam | None = None
        if application.employee_name:
            recent_exam = await OhHealthExamService(self.session).get_latest_by_person(
                application.employee_name, application.id_card_no
            )
        recent_exam_conclusion = self._format_exam_conclusion(recent_exam)

        ppe_map = await OhHazardFactorService(self.session).get_ppe_map()

        exposure_years: float | None = None
        last_exam_type: str | None = None
        if person is not None:
            exposure_years = person.hazard_exposure_years
        if recent_exam is not None:
            last_exam_type = recent_exam.exam_type
        elif person is not None:
            last_exam_type = person.last_exam_type

        return (
            old_hazards, new_hazards, recent_exam_conclusion, ppe_map,
            exposure_years, last_exam_type,
        )

    @staticmethod
    def _format_exam_conclusion(exam: OhHealthExam | None) -> str:
        """最近体检结论文本：AI 结论 + 禁忌证因素；无 AI 结论用原文。"""
        if exam is None:
            return "无近期体检记录"
        parts: list[str] = []
        if exam.ai_conclusion:
            parts.append(f"AI结论: {exam.ai_conclusion}")
            factors = exam.ai_contraindication_factors or []
            if factors:
                parts.append("职业禁忌证因素: " + "、".join(factors))
            if exam.exam_conclusion:
                parts.append("检查结论原文: " + exam.exam_conclusion[:500])
            if exam.treatment_advice_raw:
                parts.append("处理意见原文: " + exam.treatment_advice_raw[:300])
        else:
            if exam.exam_conclusion:
                parts.append("检查结论原文: " + exam.exam_conclusion[:500])
            if exam.treatment_advice_raw:
                parts.append("处理意见原文: " + exam.treatment_advice_raw[:300])
        if not parts:
            parts.append("有体检记录但无结论文本")
        if exam.exam_date:
            parts.append(f"体检日期: {exam.exam_date.date()}")
        return "；".join(parts)

    # ── Bitable 回写（防循环）──

    async def _sync_bitable_application(self, application: OhExamApplication) -> None:
        """回写 Bitable 申请表「差异分析结论」「是否需体检」「建议」三字段。

        写回前 _set_sync_ignore(record_id, ttl=30) 防平台回写循环；
        Bitable 配置未配置或调用失败仅告警，不阻塞主流程。
        """
        if not application.feishu_record_id:
            return
        from app.modules.safety.bitable_config.store import store

        conn = store.get_connection("oh", "exam_application")
        if conn is None or conn.status == "disabled":
            return
        app_token, table_id = conn.app_token, conn.table_id
        try:
            from app.modules.safety.feishu.bitable_client import SafetyBitableClient
            from app.modules.safety.feishu.bitable_handler import _set_sync_ignore

            fields: dict[str, Any] = {}
            if application.diff_summary:
                fields["差异分析结论"] = application.diff_summary
            if application.needs_exam is not None:
                fields["是否需体检"] = "是" if application.needs_exam else "否"
            if application.exam_suggestion:
                label = _EXAM_SUGGESTION_LABELS.get(application.exam_suggestion)
                if label:
                    fields["建议"] = label
            if not fields:
                return
            await _set_sync_ignore(application.feishu_record_id, ttl=30)
            client = SafetyBitableClient(app_token=app_token, table_id=table_id)
            await client.update_record(record_id=application.feishu_record_id, fields=fields)
        except Exception:
            logger.exception("Bitable 申请表回写失败: application=%s", application.id)

    # ── Bitable 同步（ticket 03 handler 复用）──

    async def upsert_from_bitable(
        self, data: dict[str, Any], feishu_record_id: str
    ) -> OhExamApplication:
        existing = await self.session.scalar(
            select(OhExamApplication).where(
                OhExamApplication.feishu_record_id == feishu_record_id,
                OhExamApplication.is_deleted == False,  # noqa: E712
            )
        )
        if existing:
            data.pop("feishu_record_id", None)
            for key, val in data.items():
                if val is not None:
                    setattr(existing, key, val)
            await self.session.commit()
            return existing
        item = OhExamApplication(**{**data, "feishu_record_id": feishu_record_id})
        self.session.add(item)
        await self.session.flush()
        return item

    async def soft_delete_by_feishu_id(self, feishu_record_id: str) -> bool:
        existing = await self.session.scalar(
            select(OhExamApplication).where(
                OhExamApplication.feishu_record_id == feishu_record_id,
                OhExamApplication.is_deleted == False,  # noqa: E712
            )
        )
        if not existing:
            return False
        existing.is_deleted = True
        existing.feishu_record_id = None
        existing.application_no = None
        await self.session.commit()
        await self._audit("delete", "oh_exam_application", resource_id=existing.id)
        return True
