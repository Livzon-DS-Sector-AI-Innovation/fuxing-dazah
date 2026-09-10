"""Safety business workflows."""

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import (
    EhsChange,
)
from app.modules.safety.repository import SafetyRepository
from app.modules.safety.schemas import (
    EhsChangeCreate,
    EhsChangeUpdate,
)
from app.modules.safety.service._helpers import audit_log

logger = logging.getLogger(__name__)


def _ai_overall_conclusion(ai_review_result: Any) -> str | None:
    """从 ai_review_result JSONB 计算总体 AI 审核结论（优先级 不通过 > 需补充 > 通过）。"""
    if not isinstance(ai_review_result, dict):
        return None
    dims = ["risk", "reason", "plan", "effect"]
    for key in ("审核不通过", "需补充完善", "审核通过"):
        for dim_key in dims:
            dim = ai_review_result.get(dim_key)
            if isinstance(dim, dict) and dim.get("conclusion") == key:
                return key
    return None


class EhsChangeService:
    """EHS变更管理业务服务（基于 T/CCSAS 007-2020）"""

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
            old_value=old_value,
            new_value=new_value,
            extra=extra,
        )

    # ── CRUD ──

    async def get_ehs_changes(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        change_type: str | None = None,
        change_grade: str | None = None,
        change_duration: str | None = None,
        department: str | None = None,
        keyword: str | None = None,
        source: str | None = None,
        feishu_table_id: str | None = None,
        sort_by: str | None = None,
        sort_order: str = "desc",
    ) -> tuple[list[EhsChange], int]:
        """获取EHS变更列表"""
        return await self.repo.get_ehs_changes(
            skip, limit, status, change_type, change_grade, change_duration,
            department, keyword, source, feishu_table_id, sort_by, sort_order,
        )

    async def get_ehs_change(self, change_id: uuid.UUID) -> EhsChange | None:
        """获取EHS变更详情"""
        return await self.repo.get_ehs_change_by_id(change_id)

    async def get_ehs_change_stats(
        self,
        feishu_table_id: str | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        """EHS 变更统计（KPI 卡）：按状态 + AI 总体结论分组计数。"""
        items = await self.repo.get_ehs_changes_for_stats(feishu_table_id, source)
        status: dict[str, int] = {}
        ai: dict[str, int] = {"审核通过": 0, "需补充完善": 0, "审核不通过": 0}
        for it in items:
            status[it.status] = status.get(it.status, 0) + 1
            conclusion = _ai_overall_conclusion(it.ai_review_result)
            if conclusion:
                ai[conclusion] = ai.get(conclusion, 0) + 1
        return {"total": len(items), "status": status, "ai": ai}

    async def create_ehs_change(self, data: EhsChangeCreate) -> EhsChange:
        """创建EHS变更"""
        create_data = data.model_dump()
        item = await self.repo.create_ehs_change(create_data)
        await self._audit("create", "ehs_change", resource_id=item.id)
        return item

    async def update_ehs_change(
        self, change_id: uuid.UUID, data: EhsChangeUpdate
    ) -> EhsChange | None:
        """更新EHS变更"""
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        item = await self.repo.update_ehs_change(change_id, update_data)
        if item:
            await self._audit("update", "ehs_change", resource_id=change_id)
        return item

    async def delete_ehs_change(self, change_id: uuid.UUID) -> bool:
        """删除EHS变更（软删除）"""
        result = await self.repo.delete_ehs_change(change_id)
        if result:
            await self._audit("delete", "ehs_change", resource_id=change_id)
        return result

    # ── 工作流状态机 ──

    async def submit_change(self, change_id: uuid.UUID) -> EhsChange | None:
        """提交变更（草稿→审核中；紧急变更自动批准）"""
        change = await self.repo.get_ehs_change_by_id(change_id)
        if not change or change.status != "draft":
            return None

        # 紧急变更：自动批准，保留审批链追溯
        if change.change_duration == "emergency":
            approval_chain = list(change.approval_chain or [])
            approval_chain.append({
                "level": 1,
                "approver_role": "系统自动批准（紧急变更）",
                "approver": "系统",
                "decision": "approved",
                "comments": "紧急变更，自动批准。需在48小时内补办审批手续。",
                "decided_at": datetime.now().isoformat(),
            })
            return await self.repo.update_ehs_change(
                change_id,
                {"status": "approved", "approval_chain": approval_chain},
            )

        return await self.repo.update_ehs_change(
            change_id, {"status": "under_review"}
        )

    async def approve_change(
        self, change_id: uuid.UUID, decision: str, comments: str | None = None
    ) -> EhsChange | None:
        """审批变更（审核中→已批准/已驳回）"""
        change = await self.repo.get_ehs_change_by_id(change_id)
        if not change or change.status != "under_review":
            return None

        if decision == "approved":
            return await self.repo.update_ehs_change(
                change_id, {"status": "approved"}
            )
        elif decision == "rejected":
            return await self.repo.update_ehs_change(
                change_id, {"status": "rejected"}
            )
        return None

    async def reject_change(
        self, change_id: uuid.UUID, comments: str | None = None
    ) -> EhsChange | None:
        """驳回变更（审核中→已驳回）"""
        change = await self.repo.get_ehs_change_by_id(change_id)
        if not change or change.status != "under_review":
            return None
        return await self.repo.update_ehs_change(
            change_id, {"status": "rejected"}
        )

    async def start_implementation(self, change_id: uuid.UUID) -> EhsChange | None:
        """开始实施（已批准→实施中）"""
        change = await self.repo.get_ehs_change_by_id(change_id)
        if not change or change.status != "approved":
            return None
        return await self.repo.update_ehs_change(
            change_id,
            {"status": "in_progress", "actual_start": datetime.now()},
        )

    async def commission_change(self, change_id: uuid.UUID) -> EhsChange | None:
        """投用（实施中→已投用）"""
        change = await self.repo.get_ehs_change_by_id(change_id)
        if not change or change.status != "in_progress":
            return None
        return await self.repo.update_ehs_change(
            change_id,
            {"status": "commissioned", "actual_completion": datetime.now()},
        )

    async def close_change(
        self,
        change_id: uuid.UUID,
        closed_by: str | None = None,
        temp_expiry_date: str | None = None,
        restored_date: str | None = None,
    ) -> EhsChange | None:
        """关闭变更（已投用→已关闭）"""
        change = await self.repo.get_ehs_change_by_id(change_id)
        if not change or change.status != "commissioned":
            return None

        closure_data = {
            "closed_by": closed_by,
            "closed_date": datetime.now().isoformat(),
        }
        if temp_expiry_date:
            closure_data["temp_expiry_date"] = temp_expiry_date
        if restored_date:
            closure_data["restored_date"] = restored_date

        return await self.repo.update_ehs_change(
            change_id,
            {"status": "closed", "closure": closure_data},
        )

    async def cancel_change(self, change_id: uuid.UUID) -> EhsChange | None:
        """取消变更（草稿→已关闭）"""
        change = await self.repo.get_ehs_change_by_id(change_id)
        if not change or change.status != "draft":
            return None
        closure_data = {
            "closed_by": None,
            "closed_date": datetime.now().isoformat(),
        }
        return await self.repo.update_ehs_change(
            change_id,
            {"status": "closed", "closure": closure_data},
        )

    # ── JSON 子记录操作 ──

    async def add_risk_assessment(
        self, change_id: uuid.UUID, item: dict
    ) -> EhsChange | None:
        """追加风险评估记录"""
        change = await self.repo.get_ehs_change_by_id(change_id)
        if not change:
            return None
        assessments = list(change.risk_assessments or [])
        assessments.append(item)
        return await self.repo.update_ehs_change(
            change_id, {"risk_assessments": assessments}
        )

    async def update_action_item(
        self, change_id: uuid.UUID, index: int, status: str
    ) -> EhsChange | None:
        """更新行动项状态"""
        change = await self.repo.get_ehs_change_by_id(change_id)
        if not change:
            return None
        items = list(change.action_items or [])
        if index < 0 or index >= len(items):
            return None
        items[index] = {**items[index], "status": status}
        if status == "completed":
            items[index]["completed_at"] = datetime.now().isoformat()
        return await self.repo.update_ehs_change(
            change_id, {"action_items": items}
        )

    async def update_pssr_checklist(
        self, change_id: uuid.UUID, items: list[dict]
    ) -> EhsChange | None:
        """更新PSSR检查清单"""
        change = await self.repo.get_ehs_change_by_id(change_id)
        if not change:
            return None
        return await self.repo.update_ehs_change(
            change_id, {"pssr_checklist": items}
        )

    async def submit_verification(
        self, change_id: uuid.UUID, data: dict
    ) -> EhsChange | None:
        """提交变更验证数据"""
        change = await self.repo.get_ehs_change_by_id(change_id)
        if not change:
            return None
        return await self.repo.update_ehs_change(
            change_id, {"verification": data}
        )

    # ── Bitable 同步（纯数据对齐，不触发通知/AI/状态流转）──

    async def upsert_from_bitable(
        self,
        data: dict,
        feishu_record_id: str,
        table_kind: str,
    ) -> EhsChange | None:
        """将 Bitable 记录 upsert 到 EhsChange（source='bitable'）。

        data 为映射后的字段 dict；change_no 作为唯一约束键，更新时保持稳定。
        """
        data["source"] = "bitable"
        data["feishu_record_id"] = feishu_record_id
        data["feishu_table_id"] = table_kind

        existing = await self.repo.get_ehs_change_by_feishu_id(feishu_record_id)
        if existing:
            for k, v in data.items():
                if k != "change_no" and v is not None:
                    # ai_review_result：合并 regulations（Bitable 无此字段，保留平台已有审核依据）
                    if k == "ai_review_result" and isinstance(v, dict):
                        cur = getattr(existing, "ai_review_result", None)
                        if isinstance(cur, dict) and cur.get("regulations"):
                            v = {**v, "regulations": cur["regulations"]}
                    setattr(existing, k, v)
            existing.updated_at = datetime.now()
            await self.session.commit()
            return existing

        item = EhsChange(**data)
        self.session.add(item)
        await self.session.commit()
        return item

    async def soft_delete_by_feishu_id(self, feishu_record_id: str) -> bool:
        """按 feishu_record_id 软删除 Bitable 来源记录。"""
        from sqlalchemy import update

        result = await self.session.execute(
            update(EhsChange)
            .where(
                EhsChange.feishu_record_id == feishu_record_id,
                EhsChange.source == "bitable",
            )
            .values(is_deleted=True)
        )
        await self.session.commit()
        return (result.rowcount or 0) > 0

    # ── AI 审核（平台侧生成 4 维度结论 + 回填 Bitable）──

    async def run_ehs_ai_review(
        self,
        change_id: uuid.UUID,
        channel: str = "system",
    ) -> EhsChange | None:
        """对单条 EHS 变更执行 AI 审核并回填 Bitable 审批表。

        - 仅支持 source='bitable' 且 feishu_table_id='approval' 的审批变更
        - 流程：RAG 检索法规 → DeepSeek 生成 4 维度结论/报告 + 预审意见 →
                回填 Bitable「-AI审核结论/报告」「AI预审意见」列 → 更新平台 ai_review_*
        - AI 失败 → ai_review_status='failed'（可重审），不抛异常
        """
        change = await self.repo.get_ehs_change_by_id(change_id)
        if (
            not change
            or change.source != "bitable"
            or change.feishu_table_id != "approval"
            or not change.feishu_record_id
        ):
            return None

        # ── 防重锁（Redis SET NX，重复触发直接返回）──
        from app.modules.safety.feishu import bitable_handler as bh

        try:
            if await bh._is_duplicate(
                "review", change.feishu_record_id, ttl=120, suffix=str(change.id)[:8]
            ):
                logger.info("EHS AI 审核: 重复触发跳过 change_id=%s", change_id)
                return change
        except Exception:
            pass  # Redis 不可用时降级，依赖 completed 状态判断

        from app.modules.safety.ai_audit import ai_audit_scope
        from app.modules.safety.ai_ehs_review import (
            EhsChangeReviewPlugin,
            EhsReviewInput,
        )
        from app.modules.safety.service.config import create_ai_service

        input_data = EhsReviewInput(
            change_no=change.bt_change_no or change.change_no,
            title=change.title or "",
            change_type=change.change_type,
            change_grade=change.change_grade,
            department=change.department,
            reason_text=change.description or "",
            plan_text=change.bt_plan_content or "",
            effect_text=change.expected_effect or "",
            risk_text=change.bt_risk_measures or "",
        )

        try:
            with ai_audit_scope(
                scenario="ehs_change_review",
                channel=channel,
                resource_type="ehs_change",
                resource_id=change.id,
                user_name=change.applicant_name,
            ):
                ai = create_ai_service("text")

                # RAG 法规检索（query 用变更完整内容；失败降级为空）
                knowledge_md = ""
                regulations: list[dict[str, str]] = []
                try:
                    from app.modules.safety.knowledge.query_service import (
                        _build_document_context,
                        _group_chunks_by_document,
                    )
                    from app.modules.safety.knowledge.retriever import (
                        SafetyKnowledgeRetriever,
                    )

                    # query 拼接变更核心内容（完整不截断，供实体提取/混合检索）
                    query = " ".join(filter(None, [
                        change.title,
                        change.description,
                        change.bt_risk_measures,
                    ])).strip() or (change.bt_change_no or change.change_no or "变更")
                    retriever = SafetyKnowledgeRetriever(self.session, ai_service=ai)
                    ctx = await retriever.retrieve(
                        description=query,
                        target_chunks=6,
                    )
                    # 按文档去重分组注入（复用知识库问答的成熟格式，避免重复文档）
                    doc_groups = _group_chunks_by_document(ctx.chunks)
                    knowledge_md = _build_document_context(doc_groups)
                    # 收集法规来源（供前端展示审核依据）
                    for doc in doc_groups.values():
                        refs: list[str] = []
                        seen: set[str] = set()
                        for c in doc["chunks"]:
                            ref = c.source_article or ""
                            if ref and ref not in seen:
                                seen.add(ref)
                                refs.append(ref)
                        regulations.append({
                            "doc_title": doc["title"],
                            "article_ref": "; ".join(refs),
                        })
                except Exception:
                    logger.warning(
                        "EHS AI 审核 RAG 检索失败，降级为无知识增强 change_id=%s", change_id,
                    )

                plugin = EhsChangeReviewPlugin(ai)
                output = await plugin.review(input_data, knowledge_md)
        except Exception as e:
            logger.exception("EHS AI 审核失败 change_id=%s", change_id)
            await self.repo.update_ehs_change(
                change_id,
                {"ai_review_status": "failed", "ai_error_message": str(e)[:2000]},
            )
            await self.session.commit()
            return await self.repo.get_ehs_change_by_id(change_id)

        # ── 回填 Bitable（防死循环：写前 _set_sync_ignore）──
        writeback_ok = await self._writeback_review(change, output)
        if not writeback_ok:
            logger.error("EHS AI 审核结果回填 Bitable 失败 change_id=%s", change_id)

        # ── 更新平台 ──
        ai_result = {
            "reason": output.reason.model_dump(),
            "plan": output.plan.model_dump(),
            "effect": output.effect.model_dump(),
            "risk": output.risk.model_dump(),
            "pre_review": output.pre_review,
            "regulations": regulations,
        }
        await self.repo.update_ehs_change(
            change_id,
            {
                "ai_review_status": "completed",
                "ai_review_result": ai_result,
                "ai_error_message": None,
            },
        )
        await self.session.commit()
        logger.info(
            "EHS AI 审核完成 change_id=%s writeback_ok=%s conclusions=%s/%s/%s/%s",
            change_id, writeback_ok,
            output.reason.conclusion, output.plan.conclusion,
            output.effect.conclusion, output.risk.conclusion,
        )
        return await self.repo.get_ehs_change_by_id(change_id)

    async def _writeback_review(self, change: EhsChange, output) -> bool:
        """回写 4 维度 AI 审核结论/报告 + AI 预审意见到 Bitable 审批表。"""
        from app.modules.safety.feishu import bitable_handler as bh
        from app.modules.safety.feishu.bitable_client import SafetyBitableClient
        from app.modules.safety.feishu.ehs_change_bitable import (
            ehs_app_token,
            ehs_tables,
        )

        writeback: dict[str, Any] = {}
        for label, key in (
            ("申请变更原因", "reason"),
            ("变更计划内容", "plan"),
            ("预计效果", "effect"),
            ("变更风险评估及建议措施", "risk"),
        ):
            dim = getattr(output, key)
            writeback[f"{label}-AI审核结论"] = bh._format_bitable_select_value(
                f"{label}-AI审核结论", dim.conclusion
            )
            writeback[f"{label}-AI审核报告"] = dim.report
        writeback["AI预审意见"] = output.pre_review

        bitable = SafetyBitableClient(
            app_token=ehs_app_token(), table_id=ehs_tables().get("approval")
        )
        try:
            await bh._set_sync_ignore(change.feishu_record_id, ttl=30)
        except Exception:
            logger.warning("EHS AI 审核 _set_sync_ignore 失败 record_id=%s", change.feishu_record_id)
        try:
            ok = await bitable.update_record(change.feishu_record_id, writeback)
            logger.info(
                "EHS AI 审核已回写 record_id=%s fields=%s ok=%s",
                change.feishu_record_id, list(writeback.keys()), ok,
            )
            return ok
        except Exception:
            logger.exception(
                "EHS AI 审核回写 Bitable 异常 record_id=%s", change.feishu_record_id
            )
            return False


# ==================== 职业危害因素监测 Service ====================


