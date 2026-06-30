"""HazardReport service — CRUD + AI workflow + notifications."""
import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import delete_object
from app.core.storage import is_enabled as minio_enabled
from app.modules.safety.feishu.notification import send_user_card
from app.modules.safety.models import HazardReport
from app.modules.safety.repository import SafetyRepository
from app.modules.safety.schemas import HazardReportCreate, HazardReportUpdate
from app.modules.safety.service._helpers import audit_log
from app.platform.integrations.ai.client import AIOutputError, AIService

logger = logging.getLogger(__name__)

# ── 模块级辅助函数 ──

def _bitable_field_for_level(level: int) -> str:
    """复核级别 → Bitable 字段名映射。"""
    return {1: "部门负责人复核", 2: "分管领导复核", 3: "检查人员复核"}.get(level, f"level_{level}")

_LEVEL_TO_BITABLE_FIELD = {
    1: "部门负责人复核",
    2: "分管领导复核",
    3: "检查人员复核",
}

_STATUS_TO_BITABLE_LABEL: dict[str, str] = {
    "replied": "已回复",
    "level1_approved": "一级已审批",
    "level2_approved": "二级已审批",
    "level3_approved": "已关闭",       # Bitable 无「三级已审批」，三级通过=关闭
    "closed": "已关闭",
    "rejected": "整改中",              # Bitable 无「已驳回」，驳回后重新进入整改流程
    "pending": "整改中",               # Bitable 无「待整改」，待整改=整改进行中
    "in_progress": "整改中",
    "verifying": "复核中",             # 复核中 Bitable 选项
}


def _build_ai_review_summary(result: dict) -> str:
    """根据 AI 初审结果生成「AI初审说明」文本。

    通过：简述各维度结论
    不通过：逐条列出不通过原因 + 改进指导（对齐前端驳回指引区块）
    """
    conclusion = (result.get("review_conclusion") or "").strip()
    photo_level = result.get("photo_match_level", "")
    measure_level = result.get("measure_quality_level", "")
    compliance_level = result.get("standard_compliance_level", "")

    level_labels: dict[str, str] = {
        "matched": "匹配", "partial_match": "部分匹配",
        "unmatched": "不匹配", "no_photos": "无照片",
        "adequate": "合格", "basic": "基本合格", "inadequate": "不合格",
        "compliant": "合规", "basically_compliant": "基本合规", "non_compliant": "不合规",
    }

    if conclusion == "通过":
        parts = [
            f"图片比对：{level_labels.get(photo_level, photo_level)}",
            f"措施有效性：{level_labels.get(measure_level, measure_level)}",
            f"标准合规：{level_labels.get(compliance_level, compliance_level)}",
        ]
        summary = "AI初审通过。" + "，".join(parts) + "。"
        review_comments = (result.get("review_comments") or "").strip()
        if review_comments:
            summary += f"\n审核意见：{review_comments}"
        return summary

    # 不通过：逐条列出失败维度 + 改进指导
    items: list[str] = []
    if photo_level == "no_photos":
        items.append(
            "• 未提供整改后照片："
            "请拍摄整改后的现场照片（同一角度、同一位置），清晰展示缺陷已修复"
        )
    elif photo_level == "unmatched":
        items.append(
            "• 整改后图片与原始缺陷不符："
            "请确保照片拍摄角度与原始缺陷照片一致，完整覆盖整改区域"
        )
    if measure_level == "inadequate":
        items.append(
            "• 整改措施不合格（空泛/不可操作）："
            "请补充具体的整改措施，包含量化标准、时间节点、责任主体，"
            "避免使用「已整改」「已处理」等笼统描述"
        )
    if compliance_level == "non_compliant":
        items.append(
            "• 整改措施不符合标准要求："
            "请参照相关法规标准要求，确保整改措施符合规范"
        )
    if not items:
        review_comments = (result.get("review_comments") or "").strip()
        items.append(
            f"• 审核意见：{review_comments}"
            if review_comments
            else "• 整改回复未通过AI初审，请重新整改并提交"
        )
    header = "AI初审不通过，需重新整改。以下为不通过原因："
    return header + "\n" + "\n".join(items)


async def _sync_ai_review_to_bitable(hazard: HazardReport, result: dict) -> None:
    """将 AI 初审结果同步到 Bitable 的「AI初审结果」和「AI初审说明」字段。"""
    try:
        record_id = hazard.feishu_record_id
        if not record_id:
            return

        from app.modules.safety.feishu.bitable_client import SafetyBitableClient
        from app.modules.safety.feishu.bitable_handler import _set_sync_ignore

        conclusion = (result.get("review_conclusion") or "").strip()
        bitable_conclusion = "已通过" if conclusion == "通过" else "已驳回"
        summary = _build_ai_review_summary(result)

        bitable = SafetyBitableClient()
        await _set_sync_ignore(record_id, ttl=30)
        await bitable.update_record(
            record_id,
            {"AI初审结果": bitable_conclusion, "AI初审说明": summary},
        )
        logger.info(
            "AI初审结果已同步到 Bitable: hazard_no=%s conclusion=%s",
            hazard.hazard_no, bitable_conclusion,
        )
    except Exception:
        logger.exception(
            "同步 AI 初审结果到 Bitable 失败: hazard_no=%s", hazard.hazard_no,
        )


async def _sync_rectification_status_to_bitable(hazard: HazardReport, status: str) -> None:
    """将整改状态同步回写到 Bitable 多维表格。"""
    try:

        from app.modules.safety.feishu.bitable_client import SafetyBitableClient

        status_label = _STATUS_TO_BITABLE_LABEL.get(status, status)
        bitable = SafetyBitableClient()
        record_id = getattr(hazard, "feishu_record_id", None)
        if not record_id:
            logger.warning("_sync_rectification_status_to_bitable: 缺少 feishu_record_id, hazard_no=%s", hazard.hazard_no)
            return
        # 设置 ignore 标记防止回写触发 changed_v1 事件再同步回来
        from app.modules.safety.feishu.bitable_handler import _set_sync_ignore
        await _set_sync_ignore(record_id, ttl=30)
        await bitable.update_record(record_id, {"整改状态": status_label})
        logger.info(
            "整改状态已回写 Bitable: record_id=%s status=%s label=%s",
            record_id, status, status_label,
        )
    except Exception:
        logger.exception("整改状态回写 Bitable 失败: hazard_no=%s", hazard.hazard_no)


class HazardService:
    """HazardReport CRUD, AI identification, rectification review, notifications."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SafetyRepository(session)

    async def _audit(
        self, action: str, resource_type: str,
        resource_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None,
        old_value: dict[str, Any] | None = None, new_value: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        await audit_log(self.session, action=action, user_id=user_id,
                        resource_type=resource_type, resource_id=resource_id,
                        old_value=old_value, new_value=new_value, extra=extra)

    @staticmethod
    def _cleanup_file(file_path: str | None) -> None:
        if not file_path:
            return
        try:
            if minio_enabled():
                try:
                    delete_object("safety", file_path)
                except Exception:
                    pass
            else:
                abs_path = os.path.abspath(file_path)
                if os.path.exists(abs_path):
                    os.remove(abs_path)
        except OSError:
            pass

    @staticmethod
    def _cleanup_json_array_files(json_str: str | None) -> None:
        if not json_str:
            return
        try:
            paths = json.loads(json_str)
            if isinstance(paths, list):
                for p in paths:
                    if isinstance(p, str):
                        HazardService._cleanup_file(p)
        except (json.JSONDecodeError, TypeError):
            pass

    # ==================== HazardReport Operations ====================

    async def get_hazards(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        rectification_status: str | None = None,
        hazard_type: str | None = None,
        hazard_level: str | None = None,
        hazard_category: str | None = None,
        inspection_category: str | None = None,
        department: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[HazardReport], int]:
        """获取隐患列表"""
        return await self.repo.get_hazards(
            skip, limit, status, rectification_status, hazard_type, hazard_level,
            hazard_category, inspection_category, department, keyword,
        )

    async def get_hazard_stats(self) -> dict[str, int]:
        """获取隐患全局统计数据"""
        return await self.repo.get_hazard_stats()

    async def get_hazard(self, hazard_id: uuid.UUID) -> HazardReport | None:
        """获取隐患详情"""
        return await self.repo.get_hazard_by_id(hazard_id)

    async def create_hazard(
        self, data: HazardReportCreate, auto_run_ai: bool = False
    ) -> HazardReport:
        """创建隐患（hazard_no 留空时自动生成）。

        AI 识别不在此处执行——调用方应在图片上传完成后通过
        run_hazard_ai_script() 手动触发，与 Bitable 同步流程对齐。
        """
        hazard_data = data.model_dump(exclude_none=True)
        if not hazard_data.get("hazard_no"):
            # 自动生成：HZ-年月日-序号
            today = datetime.now().strftime("%Y%m%d")
            existing = await self.repo.count_hazards_today(today)
            hazard_data["hazard_no"] = f"HZ-{today}-{existing + 1:03d}"
        # 填充默认值以兼容DB NOT NULL约束
        hazard_data.setdefault("hazard_type", "unsafe_condition")
        hazard_data.setdefault("hazard_level", "general")
        hazard_data.setdefault("description", "待AI填写")
        hazard_data.setdefault("discovered_at", datetime.now())
        # 初始化 AI 状态
        hazard_data.setdefault("ai_node_progress", "pending_script1")
        hazard_data.setdefault("overall_status", "open")
        hazard_data.setdefault("ai_generated", False)

        item = await self.repo.create_hazard(hazard_data)

        # 记录审计日志
        await self._audit("create", "hazard_report", resource_id=item.id)

        # ── 自动执行 AI 隐患识别（插件：有照片走视觉模型，无照片走文本模型）──
        # 在 savepoint 内执行，避免 AI 流程中的 DB 错误污染外层事务
        if auto_run_ai:
            logger.info("触发 AI 隐患识别: hazard_id=%s hazard_no=%s", item.id, item.hazard_no)
            ai_savepoint = await self.session.begin_nested()
            try:
                item = await self.run_hazard_ai_script(item.id, 1)
                await ai_savepoint.commit()
                logger.info(
                    "AI 隐患识别完成: hazard_id=%s type=%s level=%s category=%s error=%s",
                    item.id, item.hazard_type, item.hazard_level,
                    item.hazard_category, item.ai_error_message,
                )
            except Exception as e:
                await ai_savepoint.rollback()
                logger.error(f"AI 隐患识别失败(hazard {item.id}): {e}")
                # 即使 AI 失败也返回记录，用户可在台账中手动重试

        # ── 自动计算整改期限（discovered_at + 60 天）──
        # 与 Bitable 同步流程 (_create_hazard_from_bitable) 保持一致
        if not item.deadline:
            from datetime import timedelta
            base_date = item.discovered_at or datetime.now()
            computed_deadline = base_date + timedelta(days=60)
            item = await self.repo.update_hazard(item.id, {"deadline": computed_deadline})
            logger.info("整改期限自动计算: hazard_id=%s deadline=%s", item.id, computed_deadline)

        # ── 自动判定整改责任人（根据责任部门查部门负责人）──
        # 与 Bitable 同步流程 (_create_hazard_from_bitable) 保持一致
        if item.department and not item.rectification_responsible_person_name:
            try:
                from app.modules.safety.feishu.identity_resolver import IdentityResolver
                resolver = IdentityResolver(self.session)
                person = await resolver.resolve_department_leader(item.department)
                if person and person.name:
                    item = await self.repo.update_hazard(item.id, {
                        "rectification_responsible_person": (
                            uuid.UUID(person.id) if person.id else None
                        ),
                        "rectification_responsible_person_name": person.name,
                    })
                    logger.info(
                        "责任人自动判定: dept=%s leader=%s uuid=%s",
                        item.department, person.name, person.id,
                    )
            except Exception:
                logger.exception("责任人自动判定失败: dept=%s", item.department)

        return item

    async def update_hazard(
        self, hazard_id: uuid.UUID, data: HazardReportUpdate
    ) -> HazardReport | None:
        """更新隐患"""
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        item = await self.repo.update_hazard(hazard_id, update_data)
        if item:
            await self._audit("update", "hazard_report", resource_id=hazard_id)
        return item

    async def upload_hazard_photo(
        self, hazard_id: uuid.UUID, file_name: str, file_path: str
    ) -> HazardReport | None:
        """保存隐患图片路径，追加到 defect_photos JSON 数组"""
        import json

        hazard = await self.repo.get_hazard_by_id(hazard_id)
        if not hazard:
            return None
        # 标准化为 / 分隔符：避免 Windows 反斜杠在 JSON 中被当作非法转义符
        safe_path = file_path.replace("\\", "/")
        try:
            photos = json.loads(hazard.defect_photos) if hazard.defect_photos else []
        except (json.JSONDecodeError, TypeError):
            # 兼容历史损坏数据：尝试替换反斜杠后解析，仍失败则视为空列表
            try:
                photos = json.loads(hazard.defect_photos.replace("\\", "/"))
            except Exception:
                photos = []
        if not isinstance(photos, list):
            photos = []
        photos.append(safe_path)
        return await self.repo.update_hazard(
            hazard_id, {"defect_photos": json.dumps(photos, ensure_ascii=False)}
        )

    async def upload_rectification_photo(
        self, hazard_id: uuid.UUID, file_path: str
    ) -> HazardReport | None:
        """保存整改后图片路径，追加到 rectification_photos JSON 数组"""
        import json

        hazard = await self.repo.get_hazard_by_id(hazard_id)
        if not hazard:
            return None
        safe_path = file_path.replace("\\", "/")
        try:
            photos = json.loads(hazard.rectification_photos) if hazard.rectification_photos else []
        except (json.JSONDecodeError, TypeError):
            try:
                photos = json.loads(hazard.rectification_photos.replace("\\", "/"))
            except Exception:
                photos = []
        if not isinstance(photos, list):
            photos = []
        photos.append(safe_path)
        return await self.repo.update_hazard(
            hazard_id, {"rectification_photos": json.dumps(photos, ensure_ascii=False)}
        )

    async def start_rectification(self, hazard_id: uuid.UUID) -> HazardReport | None:
        """开始整改"""
        hazard = await self.repo.get_hazard_by_id(hazard_id)
        if not hazard or hazard.rectification_status != "pending":
            return None
        return await self.repo.update_hazard(
            hazard_id, {"rectification_status": "in_progress"}
        )

    async def reply_rectification(
        self,
        hazard_id: uuid.UUID,
        reply_content: str,
        rectification_photos: str | None,
        corrective_preventive_measures: str | None = None,
        rectification_reply: str | None = None,
        actual_completion_date: datetime | None = None,
    ) -> HazardReport | None:
        """整改回复：in_progress → ai_reviewing（AI 初审作为复核阶段第一道关卡）。"""
        hazard = await self.repo.get_hazard_by_id(hazard_id)
        if not hazard or hazard.rectification_status not in ("pending", "in_progress"):
            return None
        update_data: dict[str, Any] = {
            "rectification_status": "ai_reviewing",
        }
        # 整改完成时间：优先用传入值，其次保留已有值，最后 fallback 当前时间
        if actual_completion_date:
            update_data["actual_completion_date"] = actual_completion_date
        elif not hazard.actual_completion_date:
            update_data["actual_completion_date"] = datetime.now()
        # 优先级：rectification_reply > corrective_preventive_measures > reply_content
        reply_value = rectification_reply or corrective_preventive_measures or reply_content
        if reply_value:
            update_data["rectification_reply"] = reply_value
        if rectification_photos is not None:
            update_data["rectification_photos"] = rectification_photos
        updated = await self.repo.update_hazard(hazard_id, update_data)

        # 记录审计日志
        if updated:
            await self._audit("reply_rectification", "hazard_report", resource_id=hazard_id)

        # 整改回复后，异步触发 AI 初审（非阻塞），AI 结果将决定后续通知路由
        if updated:
            asyncio.create_task(
                self.run_rectification_review(hazard_id)
            )

        return updated

    async def verify_level(
        self,
        hazard_id: uuid.UUID,
        level: int,
        action: str,
        opinion: str | None,
        user_id: uuid.UUID,
        user_name: str,
    ) -> HazardReport | None:
        """三级复核：按级别审批或驳回。

        复核流程因隐患等级而异：
        - 一般隐患：AI初审 → 部门负责人复核(1) → 检查人员复核(3)
          （L1 通过后 L2 自动设为「无需复核」，分管领导无需介入）
        - 较大/重大隐患：AI初审 → 部门负责人复核(1) → 分管领导复核(2) → 检查人员复核(3)

        一级复核（部门负责人）双重门禁：
        - rectification_status 必须为 replied（AI 已给出结论）
        - ai_review_status 必须为 completed（AI 审核已成功完成，不能是 failed/pending/processing）
        防止 AI 审核异常兜底时流程被错误路由到人工复核。
        """
        hazard = await self.repo.get_hazard_by_id(hazard_id)
        if not hazard:
            return None

        # 检查当前状态是否允许该级别复核（严格线性门禁）
        if level == 1:
            if hazard.rectification_status != "replied":
                return None
            # 防御性关卡：AI 审核必须已完成，防止 AI 异常/失败时流程被错误放行
            if hazard.ai_review_status != "completed":
                return None
        if level == 2 and hazard.verify_level_1_status != "approved":
            return None
        if level == 3 and hazard.verify_level_2_status not in ("approved", "no_review_needed"):
            return None

        if action == "rejected":
            update_data: dict[str, Any] = {
                "rectification_status": "rejected",
                f"verify_level_{level}_status": "rejected",
            }
            return await self.repo.update_hazard(hazard_id, update_data)

        # action == "approved"
        if level == 3:
            update_data: dict[str, Any] = {
                "rectification_status": "closed",
                "status": "closed",
                "verify_level_3_status": "approved",
            }
        else:
            next_status = f"level{level}_approved"
            update_data: dict[str, Any] = {
                "rectification_status": next_status,
                f"verify_level_{level}_status": "approved",
            }
        updated = await self.repo.update_hazard(hazard_id, update_data)

        # 记录审计日志
        if updated:
            await self._audit(
                "verify", "hazard_report",
                resource_id=hazard_id, user_id=user_id,
                extra={"level": level, "action": action},
            )

        # 审核通过后，异步通知下一级复核人
        # 一般隐患：L1 通过后 L2（分管领导）无需复核，自动跳过并通知 L3
        if updated and action == "approved" and level < 3:
            if level == 1 and getattr(updated, "hazard_level", None) == "general":
                # 自动将 L2 设为「无需复核」，跳至 L3
                await self.repo.update_hazard(
                    hazard_id,
                    {
                        "verify_level_2_status": "no_review_needed",
                        "rectification_status": "level2_approved",
                    },
                )
                # re-fetch 获取最新状态
                updated = await self.repo.get_hazard_by_id(hazard_id)
                if updated:
                    asyncio.create_task(_send_verify_notification(updated, 3))
            else:
                asyncio.create_task(_send_verify_notification(updated, level + 1))

        return updated

    async def rework_rectification(
        self,
        hazard_id: uuid.UUID,
        reply_content: str,
        rectification_photos: str | None,
        user_id: uuid.UUID,
        user_name: str,
    ) -> HazardReport | None:
        """重新整改：rejected → ai_reviewing，重置所有复核级别，AI 重新审查"""
        hazard = await self.repo.get_hazard_by_id(hazard_id)
        if not hazard or hazard.rectification_status != "rejected":
            return None
        update_data: dict[str, Any] = {
            "rectification_status": "ai_reviewing",
            "rectification_reply": reply_content,
            "verify_level_1_status": "pending",
            "verify_level_2_status": "pending",
            "verify_level_3_status": "pending",
            # 重置 AI 初审状态，重新审查
            "ai_review_status": "pending",
            "ai_review_result": None,
            "ai_review_completed_at": None,
        }
        if rectification_photos is not None:
            update_data["rectification_photos"] = rectification_photos
        updated = await self.repo.update_hazard(hazard_id, update_data)

        # 重新整改回复后，异步触发 AI 初审（非阻塞），AI 结果将决定后续通知路由
        if updated:
            asyncio.create_task(
                self.run_rectification_review(hazard_id)
            )

        return updated

    async def delete_hazard(self, hazard_id: uuid.UUID) -> bool:
        """删除隐患"""
        hazard = await self.repo.get_hazard_by_id(hazard_id)
        result = await self.repo.delete_hazard(hazard_id)
        if result:
            if hazard:
                self._cleanup_json_array_files(hazard.defect_photos)
                self._cleanup_json_array_files(hazard.rectification_photos)
            await self._audit("delete", "hazard_report", resource_id=hazard_id)
        return result

    # ── AI 工作流 ──

    async def _generate_hazard_ai_output(
        self, script_number: int, item: HazardReport
    ) -> dict:
        """调用 AI 服务为隐患模块生成工作流输出。失败时抛出 AIOutputError。

        script 1 → AIHazardIdentifier 插件（含 few-shot prompt、规则引擎、自动修正）
        script 2 → 无需额外 AI 调用（插件已在 script 1 中生成整改建议）
        """
        if script_number == 1:
            return await self._generate_hazard_identification(item)

        # Script 2: 整改建议已由插件在 script 1 中生成，无需额外调用
        logger.debug("Script 2 无需额外 AI 调用，整改建议已由插件生成")
        return {}

    async def _generate_hazard_identification(self, item: HazardReport) -> dict:
        """使用 AIHazardIdentifier 插件执行 AI 隐患识别（script 1）。

        插件负责：prompt 构建（含 few-shot）、视觉/文本路由、输出解析、规则验证、自动修正。
        返回 dict 供 _map_hazard_ai_output() 映射到 HazardReport 字段。
        """
        from app.modules.safety.ai_hazard_identification import (
            AIHazardIdentifier,
            HazardIdentificationInput,
            PluginConfig,
        )

        # 解析缺陷图片（本地路径 → data URI）
        image_urls = (
            self._parse_defect_photo_urls(item.defect_photos)
            if item.defect_photos else []
        )
        logger.info(
            "AI 隐患识别插件启动: hazard_id=%s desc=%s photos=%d",
            item.id, (item.description or "")[:80], len(image_urls),
        )

        # 构建插件输入（注意：HazardReport 模型没有 location 字段，传 None 即可）
        input_data = HazardIdentificationInput(
            hazard_no=item.hazard_no or str(item.id)[:8],
            description=item.description or "无描述",
            department=item.department or "",
            location=item.department or "",  # 隐患模型无独立 location，用 department 代替
            discovered_by_name=item.discovered_by_name or "",
            discovered_at=item.discovered_at,
            defect_photos=image_urls,
        )

        # 根据是否有图片选择 AI 服务（在知识加载前创建，供智能卡片选择使用）
        if image_urls:
            ai_service = await self._get_vision_ai_service()
        else:
            ai_service = await self._get_ai_service()

        # 加载法规知识库上下文（savepoint 隔离：知识库查询失败不能污染外层事务）
        try:
            from app.modules.safety.knowledge import KnowledgeInjector
            knowledge_sp = await self.session.begin_nested()
            try:
                injector = KnowledgeInjector(self.session)
                knowledge_context = await injector.build_knowledge_context(
                    hazard_description=item.description or "",
                    department=item.department or "",
                    ai_service=ai_service,
                    max_cards=5,
                )
                await knowledge_sp.commit()
                logger.info("法规知识库加载完成: len=%d chars", len(knowledge_context))
            except Exception as e:
                await knowledge_sp.rollback()
                logger.warning("法规知识库加载失败，继续不使用知识增强: %s", e)
                knowledge_context = None
        except Exception as e:
            logger.warning("法规知识库加载失败，继续不使用知识增强: %s", e)
            knowledge_context = None

        try:
            config = PluginConfig(
                temperature=0.05,
                strict_mode=False,   # 非严格模式：验证警告不阻塞流程
                enable_vision=bool(image_urls),
                enable_knowledge=bool(knowledge_context),
            )
            plugin = AIHazardIdentifier(
                ai_service, config,
                knowledge_context=knowledge_context,
            )
            output = await plugin.identify(input_data)

            # 转换为 dict 供 _map_hazard_ai_output() 使用
            return {
                "key_defect": output.key_defect,
                "hazard_type": output.hazard_type.value,
                "hazard_category": output.hazard_category.value,
                "hazard_level": output.hazard_level.value,
                "major_hazard_basis": output.major_hazard_basis,
                # 整改建议也返回，供后续 script 2 或人工参考
                "rectification_suggestion": {
                    "corrective": output.rectification_suggestion.corrective,
                    "preventive": output.rectification_suggestion.preventive,
                },
            }
        except Exception as e:
            logger.error("AI 隐患识别插件执行失败: %s", e)
            raise AIOutputError(f"AI 隐患识别失败: {e}") from e
        finally:
            await ai_service.close()

    def _parse_defect_photo_urls(self, defect_photos: str) -> list[str]:
        """从 defect_photos JSON 字段提取图片，本地路径转 base64 data URI。"""
        import base64
        import json as _json

        try:
            photos = _json.loads(defect_photos)
        except (_json.JSONDecodeError, TypeError):
            # Windows 反斜杠路径经 json.dumps 写入后，json.loads 会报 Invalid \escape
            # 尝试把反斜杠替换为正斜杠再解析
            try:
                photos = _json.loads(defect_photos.replace("\\", "/"))
            except (_json.JSONDecodeError, TypeError):
                logger.warning("defect_photos JSON 解析失败，返回空列表: raw=%s", defect_photos[:200])
                return []
        if isinstance(photos, str):
            photos = [photos] if photos else []
        elif not isinstance(photos, list):
            logger.warning("defect_photos 格式异常(非 list/str)，返回空列表: type=%s", type(photos).__name__)
            return []

        urls: list[str] = []
        for p in photos:
            p_str = str(p)
            # 已经是 http/data URL，直接使用
            if p_str.startswith("http://") or p_str.startswith("https://") or p_str.startswith("data:"):
                urls.append(p_str)
                continue
            # 本地路径 → base64 data URI
            # 兼容 Windows 反斜杠路径：同时检查原始路径和正斜杠版本
            check_paths = [p_str]
            if "\\" in p_str:
                check_paths.append(p_str.replace("\\", "/"))
            elif "/" in p_str:
                check_paths.append(p_str.replace("/", "\\"))
            # Also try with ./uploads/ prefix (for clean paths stored without prefix)
            uploads_base = os.path.abspath("./uploads")
            for orig in list(check_paths):
                candidate = os.path.normpath(os.path.join(uploads_base, orig))
                if candidate not in check_paths:
                    check_paths.append(candidate)
            found_path = None
            for cp in check_paths:
                if cp and os.path.exists(cp):
                    found_path = cp
                    break
            if found_path:
                try:
                    ext = os.path.splitext(found_path)[1].lower()
                    mime = {
                        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
                    }.get(ext, "image/png")
                    with open(found_path, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode()
                    urls.append(f"data:{mime};base64,{b64}")
                    logger.debug("转换本地图片为 data URI: %s (%s)", found_path, mime)
                except Exception as exc:
                    logger.warning("无法读取图片 %s: %s", found_path, exc)
            else:
                # 文件不存在，记录警告以便排查（AI 审查缺少图片时可根据此日志定位）
                logger.warning(
                    "defect_photos 本地文件不存在: path=%s (checked: %s)",
                    p_str, check_paths,
                )

        logger.info(
            "_parse_defect_photo_urls: input_count=%d output_count=%d",
            len(photos) if isinstance(photos, list) else 0, len(urls),
        )
        return urls

    async def _generate_rectification_review(self, item: HazardReport) -> dict:
        """使用 AIRectificationReviewer 插件执行整改回复 AI 初审。

        插件负责：before/after 图片对比、措施质量评估、完整性检查、标准合规、综合结论。
        返回 dict 供直接写入 ai_review_result JSONB 字段。
        """

        from app.modules.safety.ai_rectification_review import (
            AIRectificationReviewer,
            RectificationReviewInput,
        )
        from app.modules.safety.ai_rectification_review import (
            PluginConfig as ReviewPluginConfig,
        )

        # 解析原始缺陷图片
        defect_image_urls = (
            self._parse_defect_photo_urls(item.defect_photos)
            if item.defect_photos else []
        )

        # 解析整改后图片
        rectification_image_urls = (
            self._parse_defect_photo_urls(item.rectification_photos)
            if item.rectification_photos else []
        )

        logger.info(
            "AI 整改初审插件启动: hazard_id=%s defect_photos=%d rectification_photos=%d reply_len=%d",
            item.id, len(defect_image_urls), len(rectification_image_urls),
            len(item.rectification_reply or ""),
        )

        # 解析 AI 识别结果中的整改建议
        ai_suggestion = None
        if item.corrective_preventive_measures:
            # 尝试解析两层结构（格式：【整改措施】... 【预防措施】...）
            # 直接以原始文本形式传递，AI 会自行解析
            try:
                ai_suggestion = {"raw": item.corrective_preventive_measures}
            except Exception:
                ai_suggestion = None

        # 构建插件输入
        input_data = RectificationReviewInput(
            hazard_id=item.id,
            original_description=item.description or "",
            original_defect_photos=defect_image_urls,
            key_defect=item.key_defect or "",
            hazard_type=item.hazard_type or "",
            hazard_category=item.hazard_category or "",
            hazard_level=item.hazard_level or "",
            ai_rectification_suggestion=ai_suggestion,
            rectification_reply=item.rectification_reply or "",
            rectification_photos=rectification_image_urls,
            department=item.department or "",
        )

        # 根据是否有整改后图片选择 AI 服务（在知识加载前创建，供智能卡片选择使用）
        if rectification_image_urls:
            ai_service = await self._get_vision_ai_service()
        else:
            ai_service = await self._get_ai_service()

        # 加载法规知识库上下文（savepoint 隔离：知识库查询失败不能污染外层事务）
        knowledge_context = None
        try:
            from app.modules.safety.knowledge import KnowledgeInjector
            knowledge_sp = await self.session.begin_nested()
            try:
                injector = KnowledgeInjector(self.session)
                knowledge_context = await injector.build_knowledge_context(
                    hazard_description=item.description or "",
                    department=item.department or "",
                    ai_service=ai_service,
                    max_cards=5,
                )
                await knowledge_sp.commit()
                logger.info("法规知识库加载完成: len=%d chars", len(knowledge_context))
            except Exception as e:
                await knowledge_sp.rollback()
                logger.warning("法规知识库加载失败，继续不使用知识增强: %s", e)
        except Exception as e:
            logger.warning("法规知识库加载失败，继续不使用知识增强: %s", e)

        try:
            config = ReviewPluginConfig(
                temperature=0.05,
                strict_mode=False,   # 非严格模式：验证警告不阻塞流程
                enable_vision=bool(rectification_image_urls),
                enable_knowledge=bool(knowledge_context),
            )
            plugin = AIRectificationReviewer(
                ai_service, config,
                knowledge_context=knowledge_context,
            )
            output = await plugin.review(input_data)

            # 转换为 dict（3 审核维度：图片比对 / 措施有效性 / 标准合规）
            return {
                "photo_match_analysis": output.photo_match_analysis,
                "photo_match_level": output.photo_match_level.value,
                "measure_quality_assessment": output.measure_quality_assessment,
                "measure_quality_level": output.measure_quality_level.value,
                "standard_compliance": output.standard_compliance,
                "standard_compliance_level": output.standard_compliance_level.value,
                "review_conclusion": output.review_conclusion.value,
                "review_comments": output.review_comments,
                "confidence": output.confidence,
                "reasoning": output.reasoning,
            }
        except Exception as e:
            logger.error("AI 整改初审插件执行失败: %s", e)
            raise AIOutputError(f"AI 整改初审失败: {e}") from e
        finally:
            await ai_service.close()

    async def run_rectification_review(
        self, hazard_id: uuid.UUID
    ) -> HazardReport | None:
        """执行整改回复 AI 初审（公开方法，供 API 和 Bitable handler 调用）。

        使用独立的数据库 session：此方法通过 asyncio.create_task 在后台执行，
        请求作用域的 session 可能在 AI 调用完成前就已关闭。
        独立 session 确保 AI 调用期间数据库连接始终有效。

        Args:
            hazard_id: 隐患记录 ID

        Returns:
            更新后的 HazardReport，失败时返回 None
        """
        from app.core.database import async_session_factory

        async with async_session_factory() as bg_session:
            bg_service = HazardService(bg_session)

            item = await bg_service.repo.get_hazard_by_id(hazard_id)
            if not item:
                logger.warning("run_rectification_review: hazard not found id=%s", hazard_id)
                return None

            # 设置处理中状态
            await bg_service.repo.update_hazard(
                hazard_id, {"ai_review_status": "processing"}
            )
            await bg_session.commit()

            try:
                result = await bg_service._generate_rectification_review(item)
                update_data: dict[str, Any] = {
                    "ai_review_result": result,
                    "ai_review_status": "completed",
                    "ai_review_completed_at": datetime.now(),
                }
                await bg_service.repo.update_hazard(hazard_id, update_data)
                await bg_session.commit()

                # Re-fetch for notification (needs fresh state after update)
                updated = await bg_service.repo.get_hazard_by_id(hazard_id)

                logger.info(
                    "AI 整改初审完成: hazard_id=%s conclusion=%s",
                    hazard_id, result.get("review_conclusion"),
                )
                # ── 根据 AI 评审判定路由后续通知 ──
                # 对结论字符串做 strip 处理，防止 AI 模型附加空白字符导致比较失败
                conclusion = (result.get("review_conclusion") or "").strip()
                if conclusion == "通过":
                    # AI 判定通过 → 开放人工复核入口 + 通知一级复核人
                    await bg_service.repo.update_hazard(
                        hazard_id, {"rectification_status": "replied"}
                    )
                    await bg_session.commit()
                    passed = await bg_service.repo.get_hazard_by_id(hazard_id)
                    if passed:
                        asyncio.create_task(_send_verify_notification(passed, 1))
                        # 同步「已回复」状态到 Bitable
                        asyncio.create_task(
                            _sync_rectification_status_to_bitable(passed, "replied")
                        )
                        # 同步 AI 初审结果到 Bitable
                        asyncio.create_task(
                            _sync_ai_review_to_bitable(passed, result)
                        )
                    logger.info(
                        "AI 初审通过 → 通知一级复核人: hazard_id=%s", hazard_id
                    )
                elif conclusion == "不通过":
                    # AI 判定不通过 → 自动驳回，通知责任人重新整改
                    await bg_service.repo.update_hazard(
                        hazard_id, {"rectification_status": "rejected"}
                    )
                    await bg_session.commit()
                    rejected = await bg_service.repo.get_hazard_by_id(hazard_id)
                    if rejected:
                        asyncio.create_task(
                            _send_rectification_notification(rejected)
                        )
                        # 同步「已驳回」状态到 Bitable，防止 Bitable 仍显示「已回复」
                        # 导致部门负责人误认为仍需复核
                        asyncio.create_task(
                            _sync_rectification_status_to_bitable(rejected, "rejected")
                        )
                        # 同步 AI 初审结果到 Bitable
                        asyncio.create_task(
                            _sync_ai_review_to_bitable(rejected, result)
                        )
                    logger.info(
                        "AI 初审不通过 → 自动驳回，通知责任人: hazard_id=%s",
                        hazard_id,
                    )
                else:
                    # 未知结论类型，安全兜底：保守处理为不通过，通知责任人重新整改
                    # 不能放行到人工复核（避免 AI 未真正审核时跳过关键检查）
                    logger.warning(
                        "AI 初审返回未知结论: hazard_id=%s conclusion=%r → 保守处理为不通过",
                        hazard_id, conclusion,
                    )
                    await bg_service.repo.update_hazard(
                        hazard_id, {"rectification_status": "rejected"}
                    )
                    await bg_session.commit()
                    unknown = await bg_service.repo.get_hazard_by_id(hazard_id)
                    if unknown:
                        asyncio.create_task(
                            _send_rectification_notification(unknown)
                        )
                        # 同步 AI 初审结果到 Bitable
                        asyncio.create_task(
                            _sync_ai_review_to_bitable(unknown, result)
                        )
                return updated
            except AIOutputError as e:
                logger.error("AI 整改初审失败(hazard %s): %s", hazard_id, e)
                await bg_service.repo.update_hazard(
                    hazard_id,
                    {
                        "ai_review_status": "failed",
                        "ai_error_message": str(e),
                        "rectification_status": "replied",
                    },
                )
                await bg_session.commit()
                # AI 失败兜底：开放复核 + 通知一级复核人进行人工审核，避免流程卡死
                asyncio.create_task(_send_verify_notification(item, 1))
                return None
            except Exception as e:
                logger.error("AI 整改初审异常(hazard %s): %s", hazard_id, e)
                await bg_service.repo.update_hazard(
                    hazard_id,
                    {
                        "ai_review_status": "failed",
                        "ai_error_message": f"AI 初审异常：{e}",
                        "rectification_status": "replied",
                    },
                )
                await bg_session.commit()
                # AI 异常兜底：开放复核 + 通知一级复核人进行人工审核，避免流程卡死
                asyncio.create_task(_send_verify_notification(item, 1))
                return None

    # ── AI 服务工厂 ──

    async def _get_ai_service(self) -> "AIService":
        """获取文本模型 AIService（硬编码配置）"""
        from app.modules.safety.service.config import create_ai_service
        return create_ai_service("text")

    async def _get_vision_ai_service(self) -> "AIService":
        """获取视觉模型 AIService（硬编码配置）"""
        from app.modules.safety.service.config import create_ai_service
        return create_ai_service("vision")

    async def run_hazard_ai_script(
        self, hazard_id: uuid.UUID, script_number: int
    ) -> HazardReport | None:
        """执行隐患AI工作流脚本（1=AI隐患识别）。

        script 1: AIHazardIdentifier 插件（含 few-shot + 规则引擎 + 整改建议）
        script 2: 已废弃，插件在 script 1 中已生成整改建议
        """
        item = await self.repo.get_hazard_by_id(hazard_id)
        if not item:
            return None

        update_data: dict[str, Any] = {}

        try:
            generated = await self._generate_hazard_ai_output(script_number, item)
            self._map_hazard_ai_output(script_number, generated, update_data)
            update_data["ai_node_progress"] = "completed"
            update_data["ai_error_message"] = None
            update_data["ai_generated"] = True
        except AIOutputError as e:
            logger.error(f"Hazard script {script_number} AI 输出错误: {e}")
            update_data["ai_error_message"] = str(e)
        except Exception as e:
            logger.error(f"Hazard script {script_number} 执行异常: {e}")
            update_data["ai_error_message"] = f"AI 服务调用失败：{e}"

        return await self.repo.update_hazard(hazard_id, update_data)

    # ── AI 输出字段约束（DB Enum 限制）──
    _VALID_HAZARD_TYPES = {"unsafe_condition", "unsafe_action", "management_defect", "environmental"}
    _VALID_HAZARD_LEVELS = {"general", "serious", "major"}
    _VALID_HAZARD_CATEGORIES = {
        "equipment", "hazardous_storage", "emergency_mgmt", "instrument_electrical",
        "lightning_antistatic", "occupational_health", "violation_operation", "six_s",
        "label_signage", "process_mgmt", "contractor_defect", "documentation", "special_operation",
    }

    def _map_hazard_ai_output(
        self, script_number: int, output: dict, update_data: dict[str, Any]
    ) -> None:
        """将 AI JSON 输出映射到 HazardReport 字段（校验枚举值）。"""
        if script_number == 1:
            for json_key, db_field in [
                ("hazard_type", "hazard_type"),
                ("hazard_level", "hazard_level"),
                ("hazard_category", "hazard_category"),
                ("key_defect", "key_defect"),
                ("major_hazard_basis", "major_hazard_basis"),
            ]:
                if json_key in output and output[json_key]:
                    val = output[json_key]
                    if db_field == "hazard_type" and val not in self._VALID_HAZARD_TYPES:
                        logger.debug("AI 输出非法 hazard_type=%s，跳过", val)
                        continue
                    if db_field == "hazard_level" and val not in self._VALID_HAZARD_LEVELS:
                        logger.debug("AI 输出非法 hazard_level=%s，跳过", val)
                        continue
                    if db_field == "hazard_category" and val not in self._VALID_HAZARD_CATEGORIES:
                        logger.debug("AI 输出非法 hazard_category=%s，跳过", val)
                        continue
                    update_data[db_field] = val

            # 插件生成的整改建议（两层结构）→ 格式化为可读中文文本
            rs = output.get("rectification_suggestion")
            if rs and isinstance(rs, dict):
                parts: list[str] = []
                if rs.get("corrective"):
                    parts.append(f"【整改措施】{rs['corrective']}")
                if rs.get("preventive"):
                    parts.append(f"【预防措施】{rs['preventive']}")
                if parts:
                    update_data["corrective_preventive_measures"] = "\n\n".join(parts)



async def _build_verify_card_content(
    hazard: HazardReport,
    level: int,
    button_state: str | None = None,
    skip_photos: bool = False,
) -> tuple[str, str, list[dict]]:
    """构建复核通知卡片内容（header + markdown + 照片 + 操作按钮）。

    Args:
        hazard: 隐患记录
        level: 复核级别 (1/2/3)
        button_state: None=活跃审批按钮, "approved"=已同意(禁用), "rejected"=已驳回(禁用)
        skip_photos: True=跳过照片上传（卡片按钮就地更新时使用，避免超时）

    Returns:
        (title, content, elements) 三元组 — 由调用方负责发送或作为卡片更新返回
    """
    level_labels = {1: "（部门负责人）", 2: "（分管领导）", 3: "（检查人员）"}
    level_text = level_labels.get(level, f"{level}级")

    bitable_file_token = os.getenv("SAFETY_FEISHU_BITABLE_APP_TOKEN", "")
    bitable_table_id = os.getenv("SAFETY_FEISHU_BITABLE_HAZARD_TABLE_ID", "")
    bitable_url = (
        f"https://www.feishu.cn/base/{bitable_file_token}"
        f"?table={bitable_table_id}&record={hazard.feishu_record_id}"
    ) if hazard.feishu_record_id else ""

    reply_text = hazard.rectification_reply or "-"
    level_emoji = {"general": "🟢", "serious": "🟠", "major": "🔴"}.get(hazard.hazard_level, "⚪")
    level_label = {"general": "一般隐患", "serious": "较大隐患", "major": "重大隐患"}.get(
        hazard.hazard_level, hazard.hazard_level or "-"
    )

    content = (
        f"**检查日期：** {hazard.discovered_at.strftime('%Y-%m-%d') if hazard.discovered_at else '-'}\n"
        f"**隐患描述：** {hazard.description or '-'}\n"
        f"**判定依据：** {hazard.major_hazard_basis or '-'}\n"
        f"**隐患级别：** {level_emoji} {level_label}\n"
        f"**责任部门：** {hazard.department or '-'}\n"
        f"**整改回复：** {reply_text}\n"
        + ("\n⬇ 请到在下方点击「同意」或「驳回」操作" if button_state is None else "")
    )

    elements: list[dict] = []

    # ── 照片（卡片就地更新时跳过上传，避免超时）──
    if not skip_photos:
        async def _upload_photos(photo_field: str | None, label: str) -> list[str]:
            if not photo_field:
                return []
            try:
                photos = json.loads(photo_field)
                if not photos or not isinstance(photos, list):
                    return []
                clean = [p for p in photos if isinstance(p, str)]
                if not clean:
                    return []
                from app.modules.safety.feishu.notification import upload_images_batch
                logger.info("复核通知照片上传: hazard_no=%s label=%s count=%d", hazard.hazard_no, label, len(clean))
                return await upload_images_batch(clean)
            except Exception:
                logger.exception("复核通知照片处理异常: hazard_no=%s label=%s", hazard.hazard_no, label)
                return []

        defect_keys = await _upload_photos(hazard.defect_photos, "缺陷照片")
        rectification_keys = await _upload_photos(hazard.rectification_photos, "整改后照片")

        # 诊断日志：整改照片为空时记录 warning，便于排查 level 1 通知缺图问题
        if not rectification_keys:
            logger.warning(
                "复核通知无整改照片: hazard_no=%s level=%s rectification_photos_raw=%s",
                hazard.hazard_no, level, repr(hazard.rectification_photos)[:200],
            )
    else:
        defect_keys = []
        rectification_keys = []

    if defect_keys or rectification_keys:
        columns: list[dict] = []
        if defect_keys:
            defect_col: dict = {
                "tag": "column", "width": "weighted", "weight": 1,
                "elements": [{"tag": "markdown", "content": "📷 **缺陷照片**"}],
            }
            for key in defect_keys:
                defect_col["elements"].append({
                    "tag": "img", "img_key": key,
                    "alt": {"tag": "plain_text", "content": "缺陷照片"},
                })
            columns.append(defect_col)

        if rectification_keys:
            rect_col: dict = {
                "tag": "column", "width": "weighted", "weight": 1,
                "elements": [{"tag": "markdown", "content": "✅ **整改后照片**"}],
            }
            for key in rectification_keys:
                rect_col["elements"].append({
                    "tag": "img", "img_key": key,
                    "alt": {"tag": "plain_text", "content": "整改后照片"},
                })
            columns.append(rect_col)

        if columns:
            elements.append({"tag": "hr"})
            if len(columns) == 1:
                elements.extend(columns[0]["elements"])
            else:
                elements.append({
                    "tag": "column_set", "flex_mode": "bisect",
                    "background_style": "default", "columns": columns,
                })
            logger.info(
                "复核通知照片已添加: hazard_no=%s defect=%d rect=%d",
                hazard.hazard_no, len(defect_keys), len(rectification_keys),
            )

    # ── 操作按钮 ──
    if button_state is None:
        # 活跃状态：同意 + 驳回 + 查看表格
        elements.append({
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "✅ 同意"},
                    "type": "primary",
                    "value": {
                        "action": "approve_rectification",
                        "record_id": hazard.feishu_record_id,
                        "level": level,
                    },
                    "confirm": {
                        "title": {"tag": "plain_text", "content": f"确认{level_text}审核通过"},
                        "text": {"tag": "plain_text", "content": f"将在多维表格中将「{_bitable_field_for_level(level)}」设为「已同意」"},
                    },
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "❌ 驳回"},
                    "type": "danger",
                    "value": {
                        "action": "reject_rectification",
                        "record_id": hazard.feishu_record_id,
                        "level": level,
                    },
                    "confirm": {
                        "title": {"tag": "plain_text", "content": "确认驳回整改"},
                        "text": {"tag": "plain_text", "content": f"将在多维表格中将「{_bitable_field_for_level(level)}」设为「未同意」，隐患退回整改阶段"},
                    },
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "📋 查看飞书表格记录"},
                    "type": "default",
                    "url": bitable_url,
                },
            ],
        })
    else:
        # 已处理状态：显示结果 + 查看表格
        result_text = "✅ 已同意" if button_state == "approved" else "❌ 已驳回"
        elements.append({
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": result_text},
                    "type": "default",
                    "disabled": True,
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "📋 查看飞书表格记录"},
                    "type": "default",
                    "url": bitable_url,
                },
            ],
        })

    title = f"🔔 隐患复核通知{level_text}" if button_state is None else f"🔔 隐患复核通知{level_text} — 已处理"
    return title, content, elements


async def _send_verify_notification(hazard: HazardReport, level: int) -> None:
    """异步发送复核通知到飞书。

    根据复核级别动态解析通知目标：
      - Level 1 → 部门负责人 (hazard.department → 部门 leader)
      - Level 2 → 分管领导   (hazard.department → 父部门 leader)
      - Level 3 → 检查人员   (hazard.discovered_by_name → open_id)

    解析失败时记录 warning 并跳过，不发送通知。
    """
    from app.core.database import async_session_factory
    from app.modules.safety.feishu.identity_resolver import IdentityResolver

    try:
        logger.debug(f"VERIFY_START: hazard_no={hazard.hazard_no} level={level} dept={hazard.department}")
        async with async_session_factory() as session:
            resolver = IdentityResolver(session)

            # 防御性检查：一般隐患不应走到 L2 通知分支
            if level == 2 and getattr(hazard, "hazard_level", None) == "general":
                logger.warning(
                    "一般隐患不应通知分管领导(L2)，已跳过: hazard_no=%s", hazard.hazard_no,
                )
                return

            if level == 1:
                person = await resolver.resolve_hazard_department_leader(hazard)
            elif level == 2:
                person = await resolver.resolve_hazard_supervising_leader(hazard)
            elif level == 3:
                person = await resolver.resolve_discoverer(hazard)
            else:
                logger.debug(f"VERIFY_FAIL: hazard_no={hazard.hazard_no} 未知复核级别 level={level}")
                logger.warning("未知复核级别: level=%s hazard_no=%s", level, hazard.hazard_no)
                return

            if not person:
                logger.debug(f"VERIFY_FAIL: hazard_no={hazard.hazard_no} level={level} 身份解析失败 dept={hazard.department}")
                logger.warning(
                    "复核通知: 身份解析失败 hazard_no=%s level=%s",
                    hazard.hazard_no, level,
                )
                return

            logger.debug(
                f"VERIFY_RESOLVED: hazard_no={hazard.hazard_no} level={level} "
                f"target={person.name} user_id={person.user_id} open_id={person.open_id}"
            )

            logger.info(
                "复核通知: hazard_no=%s level=%s target=%s user_id=%s open_id=%s",
                hazard.hazard_no, level, person.name, person.user_id, person.open_id,
            )

            title, content, elements = await _build_verify_card_content(
                hazard, level, button_state=None,
            )

            # 使用 user_id 而非 open_id（open_id 是应用专属的，跨应用不通用）
            receive_id = person.user_id or person.open_id
            id_type = "user_id" if person.user_id else "open_id"

            success = await send_user_card(
                open_id=receive_id,
                title=title,
                content=content,
                elements=elements,
                id_type=id_type,
            )
            if success:
                logger.debug(
                    f"VERIFY_SENT: hazard_no={hazard.hazard_no} level={level} "
                    f"to={person.name} receive_id={receive_id} id_type={id_type}"
                )
                logger.info(
                    "复核通知已发送: hazard_no=%s level=%s to=%s receive_id=%s id_type=%s",
                    hazard.hazard_no, level, person.name, receive_id, id_type,
                )
            else:
                logger.debug(
                    f"VERIFY_SEND_FAIL: hazard_no={hazard.hazard_no} level={level} "
                    f"to={person.name} receive_id={receive_id} id_type={id_type} — send_user_card returned False"
                )
                logger.warning(
                    "复核通知发送失败: hazard_no=%s level=%s to=%s receive_id=%s id_type=%s",
                    hazard.hazard_no, level, person.name, receive_id, id_type,
                )

            # 记录通知结果到数据库（使用独立 session，原 identity session 已关闭）
            try:
                async with async_session_factory() as rec_session:
                    await rec_session.execute(
                        update(HazardReport)
                        .where(HazardReport.id == hazard.id)
                        .values(
                            review_notified_at=datetime.now(),
                            review_notified_level=level,
                            review_notify_status="success" if success else "failed",
                            review_notify_error=None if success else "send_user_card returned False",
                        )
                    )
                    await rec_session.commit()
            except Exception:
                logger.exception("记录复核通知结果失败: hazard_no=%s", hazard.hazard_no)
    except Exception as e:
        logger.debug(f"VERIFY_EXCEPTION: hazard_no={hazard.hazard_no} level={level} error={e}")
        logger.warning("复核通知异常: hazard_no=%s level=%s error=%s", hazard.hazard_no, level, e)
        # 记录异常到数据库
        try:
            async with async_session_factory() as session2:
                await session2.execute(
                    update(HazardReport)
                    .where(HazardReport.id == hazard.id)
                    .values(
                        review_notified_at=datetime.now(),
                        review_notified_level=level,
                        review_notify_status="failed",
                        review_notify_error=str(e)[:500],
                    )
                )
                await session2.commit()
        except Exception:
            logger.exception("记录复核通知异常失败: hazard_no=%s", hazard.hazard_no)


async def _send_rectification_notification(hazard: HazardReport) -> None:
    """隐患登记成功后，异步通知责任人整改。

    动态解析 rectification_responsible_person_name → open_id，
    解析失败时记录 warning 并跳过。

    卡片包含隐患信息 + 缺陷照片 + 跳转多维表格填写整改回复按钮。
    """
    from app.core.database import async_session_factory
    from app.modules.safety.feishu.identity_resolver import IdentityResolver

    try:
        logger.debug(
            f"RECTIFY_START: hazard_no={hazard.hazard_no} "
            f"resp_name={hazard.rectification_responsible_person_name} dept={hazard.department}"
        )
        async with async_session_factory() as session:
            resolver = IdentityResolver(session)
            person = await resolver.resolve_responsible_person(hazard)

            if not person:
                logger.debug(
                    f"RECTIFY_FAIL: hazard_no={hazard.hazard_no} "
                    f"无法解析责任人 name={hazard.rectification_responsible_person_name}"
                )
                logger.warning(
                    "整改通知: 无法解析责任人 hazard_no=%s name=%s",
                    hazard.hazard_no, hazard.rectification_responsible_person_name,
                )
                return

            logger.debug(
                f"RECTIFY_RESOLVED: hazard_no={hazard.hazard_no} "
                f"target={person.name} user_id={person.user_id} open_id={person.open_id}"
            )

            logger.info(
                "整改通知: hazard_no=%s target=%s user_id=%s open_id=%s",
                hazard.hazard_no, person.name, person.user_id, person.open_id,
            )

        bitable_file_token = os.getenv("SAFETY_FEISHU_BITABLE_APP_TOKEN", "")
        bitable_table_id = os.getenv("SAFETY_FEISHU_BITABLE_HAZARD_TABLE_ID", "")
        bitable_url = (
            f"https://www.feishu.cn/base/{bitable_file_token}"
            f"?table={bitable_table_id}&record={hazard.feishu_record_id}"
        ) if hazard.feishu_record_id else ""

        level_emoji = {"general": "\U0001f7e2", "serious": "\U0001f7e0", "major": "\U0001f534"}.get(hazard.hazard_level, "⚪")
        level_label = {"general": "一般隐患", "serious": "较大隐患", "major": "重大隐患"}.get(
            hazard.hazard_level, hazard.hazard_level or "-"
        )
        responsible = hazard.rectification_responsible_person_name or "-"
        deadline = hazard.deadline.strftime("%Y-%m-%d") if hazard.deadline else "待指定"

        # ── 检测是否为 AI 驳回重新整改通知 ──
        # 当整改状态为 rejected 且存在 AI 初审结果时，说明是 AI 驳回了整改回复，
        # 需要在卡片中展示 AI 初审意见以区分于首次整改通知，避免责任人误认为重复消息
        is_rejection = (
            hazard.rectification_status == "rejected"
            and hazard.ai_review_result is not None
        )
        ai_review_text = ""
        rejected_reply = ""
        if is_rejection:
            ai_review_text = _build_ai_review_summary(hazard.ai_review_result)
            reply = (hazard.rectification_reply or "").strip()
            if reply:
                max_len = 200
                rejected_reply = reply[:max_len] + "..." if len(reply) > max_len else reply

        if is_rejection:
            content = (
                f"**检查日期：** {hazard.discovered_at.strftime('%Y-%m-%d') if hazard.discovered_at else '-'}\n"
                f"**隐患描述：** {hazard.description or '-'}\n"
                f"**隐患级别：** {level_emoji} {level_label}\n"
                f"**责任部门：** {hazard.department or '-'}\n"
                f"**责任人员：** {responsible}\n"
                f"**整改期限：** {deadline}\n"
                f"\n---\n"
                f"### ⚠️ AI 初审结果：不通过\n\n"
                f"{ai_review_text}\n"
            )
            if rejected_reply:
                content += (
                    f"\n---\n"
                    f"### 📝 您提交的整改回复（已驳回）\n\n"
                    f"{rejected_reply}\n"
                )
            content += (
                "\n⬇ 请根据以上审核意见重新整改，"
                "在表格中更新「纠正预防措施」并上传整改后照片"
            )
        else:
            content = (
                f"**检查日期：** {hazard.discovered_at.strftime('%Y-%m-%d') if hazard.discovered_at else '-'}\n"
                f"**隐患描述：** {hazard.description or '-'}\n"
                f"**判定依据：** {hazard.major_hazard_basis or '-'}\n"
                f"**隐患级别：** {level_emoji} {level_label}\n"
                f"**责任部门：** {hazard.department or '-'}\n"
                f"**责任人员：** {responsible}\n"
                f"**整改期限：** {deadline}\n"
                f"\n⬇ 请在多维表格中填写「纠正预防措施」并上传整改照片，该记录可转发"
            )

        elements: list[dict] = []

        # ── 照片（参照复核卡片：缺陷照片和整改照片并列展示，一左一右）──
        async def _upload_photos(photo_field, label):
            if not photo_field:
                return []
            try:
                photos = json.loads(photo_field)
                if not photos or not isinstance(photos, list):
                    return []
                clean = [p for p in photos if isinstance(p, str)]
                if not clean:
                    return []
                from app.modules.safety.feishu.notification import upload_images_batch
                return await upload_images_batch(clean)
            except Exception:
                logger.exception(
                    "整改通知照片处理异常: hazard_no=%s label=%s", hazard.hazard_no, label,
                )
                return []

        defect_keys = await _upload_photos(hazard.defect_photos, "缺陷照片")
        rectification_keys = await _upload_photos(hazard.rectification_photos, "整改后照片")

        if defect_keys or rectification_keys:
            columns: list[dict] = []
            if defect_keys:
                defect_col: dict = {
                    "tag": "column", "width": "weighted", "weight": 1,
                    "elements": [{"tag": "markdown", "content": "\U0001f4f7 **缺陷照片**"}],
                }
                for key in defect_keys:
                    defect_col["elements"].append({
                        "tag": "img", "img_key": key,
                        "alt": {"tag": "plain_text", "content": "缺陷照片"},
                    })
                columns.append(defect_col)

            if rectification_keys:
                rect_label = "✅ **已提交的整改照片**" if is_rejection else "✅ **整改后照片**"
                rect_col: dict = {
                    "tag": "column", "width": "weighted", "weight": 1,
                    "elements": [{"tag": "markdown", "content": rect_label}],
                }
                for key in rectification_keys:
                    rect_col["elements"].append({
                        "tag": "img", "img_key": key,
                        "alt": {"tag": "plain_text", "content": "整改后照片"},
                    })
                columns.append(rect_col)

            if columns:
                elements.append({"tag": "hr"})
                if len(columns) == 1:
                    # 只有一组照片 → 直接平铺
                    elements.extend(columns[0]["elements"])
                else:
                    # 两组照片 → 左右并列
                    elements.append({
                        "tag": "column_set", "flex_mode": "bisect",
                        "background_style": "default", "columns": columns,
                    })
        else:
            logger.info(
                "整改通知无照片: hazard_no=%s", hazard.hazard_no,
            )

        # ── 操作按钮 ──
        button_actions: list[dict] = []
        if bitable_url:
            button_actions.append({
                "tag": "button",
                "text": {
                    "tag": "plain_text",
                    "content": "\U0001f4cb 重新填写整改回复" if is_rejection else "\U0001f4cb 填写整改回复"
                },
                "type": "primary",
                "url": bitable_url,
            })
        elements.append({
            "tag": "action",
            "actions": button_actions,
        })

        receive_id = person.user_id or person.open_id
        id_type = "user_id" if person.user_id else "open_id"

        success = await send_user_card(
            open_id=receive_id,
            title="❌ 整改回复未通过，请重新整改" if is_rejection else "\U0001f514 隐患整改通知",
            content=content,
            elements=elements,
            id_type=id_type,
        )
        if success:
            logger.debug(
                "RECTIFY_SENT: hazard_no=%s to=%s receive_id=%s id_type=%s",
                hazard.hazard_no, person.name, receive_id, id_type,
            )
            logger.info(
                "整改通知已发送: hazard_no=%s to=%s receive_id=%s id_type=%s",
                hazard.hazard_no, person.name, receive_id, id_type,
            )
        else:
            logger.debug(
                "RECTIFY_SEND_FAIL: hazard_no=%s to=%s receive_id=%s id_type=%s",
                hazard.hazard_no, person.name, receive_id, id_type,
            )
            logger.warning(
                "整改通知发送失败: hazard_no=%s to=%s receive_id=%s id_type=%s",
                hazard.hazard_no, person.name, receive_id, id_type,
            )

        # ── 同时通知分管安全员 ──
        try:
            async with async_session_factory() as so_session:
                resolver2 = IdentityResolver(so_session)
                safety_officer = await resolver2.resolve_hazard_safety_officer(hazard)
                if safety_officer:
                    so_receive_id = safety_officer.user_id or safety_officer.open_id
                    so_id_type = "user_id" if safety_officer.user_id else "open_id"
                    so_success = await send_user_card(
                        open_id=so_receive_id,
                        title="❌ 整改回复未通过，请重新整改" if is_rejection else "\U0001f514 隐患整改通知",
                        content=content,
                        elements=elements,
                        id_type=so_id_type,
                    )
                    if so_success:
                        logger.info(
                            "整改通知已发送安全员: hazard_no=%s to=%s receive_id=%s",
                            hazard.hazard_no, safety_officer.name, so_receive_id,
                        )
                    else:
                        logger.warning(
                            "整改通知发送安全员失败: hazard_no=%s to=%s",
                            hazard.hazard_no, safety_officer.name,
                        )
                else:
                    logger.info(
                        "整改通知: 部门 %s 未配置安全员，跳过安全员通知 hazard_no=%s",
                        hazard.department, hazard.hazard_no,
                    )
        except Exception:
            logger.exception("整改通知安全员异常: hazard_no=%s", hazard.hazard_no)

        # 记录通知结果到数据库（使用独立 session，原 identity session 已关闭）
        try:
            async with async_session_factory() as rec_session:
                await rec_session.execute(
                    update(HazardReport)
                    .where(HazardReport.id == hazard.id)
                    .values(
                        rectification_notified_at=datetime.now(),
                        rectification_notify_status="success" if success else "failed",
                        rectification_notify_error=None if success else "send_user_card returned False",
                    )
                )
                await rec_session.commit()
        except Exception:
            logger.exception("记录整改通知结果失败: hazard_no=%s", hazard.hazard_no)

    except Exception as e:
        logger.debug("RECTIFY_EXCEPTION: hazard_no=%s error=%s", hazard.hazard_no, e)
        logger.warning("整改通知异常: error=%s hazard_no=%s", e, hazard.hazard_no)
        # 记录异常到数据库
        try:
            async with async_session_factory() as session2:
                await session2.execute(
                    update(HazardReport)
                    .where(HazardReport.id == hazard.id)
                    .values(
                        rectification_notified_at=datetime.now(),
                        rectification_notify_status="failed",
                        rectification_notify_error=str(e)[:500],
                    )
                )
                await session2.commit()
        except Exception:
            logger.exception("记录整改通知异常失败: hazard_no=%s", hazard.hazard_no)
