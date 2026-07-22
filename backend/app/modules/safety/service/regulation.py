"""Safety business workflows."""

import logging
import os
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import delete_object
from app.core.storage import is_enabled as minio_enabled
from app.modules.safety.repository import SafetyRepository
from app.modules.safety.service._helpers import audit_log
from app.platform.integrations.ai.client import AIOutputError, AIService

logger = logging.getLogger(__name__)


class RegulationService:
    """安全操规修订业务服务

    两大核心能力：
    1. 安全操规修订 — 人工修订 / AI修订
    2. 危险源辨识修订 — 工艺变更自动触发
    """

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

    @staticmethod
    def _cleanup_file(file_path: str | None) -> None:
        """Delete a single file from MinIO or local disk."""
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

    # ==================== 安全操作规程 CRUD ====================

    async def get_regulations(
        self,
        skip: int = 0,
        limit: int = 20,
        position: str | None = None,
        keyword: str | None = None,
        status: str | None = None,
    ) -> tuple[list, int]:
        """获取操规列表"""
        return await self.repo.get_regulations(skip, limit, position, keyword, status)

    async def get_regulation(self, regulation_id: uuid.UUID):
        """获取操规详情"""
        return await self.repo.get_regulation_by_id(regulation_id)

    async def create_regulation(self, data) -> Any:
        """创建安全操作规程"""

        create_data = data.model_dump() if not isinstance(data, dict) else data
        item = await self.repo.create_regulation(create_data)
        await self._audit("create", "regulation", resource_id=item.id)
        return item

    async def update_regulation(self, regulation_id: uuid.UUID, data) -> Any | None:
        """更新安全操作规程"""
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        item = await self.repo.update_regulation(regulation_id, update_data)
        if item:
            await self._audit("update", "regulation", resource_id=regulation_id)
        return item

    async def delete_regulation(self, regulation_id: uuid.UUID) -> bool:
        """删除安全操作规程"""
        regulation = await self.repo.get_regulation_by_id(regulation_id)
        result = await self.repo.delete_regulation(regulation_id)
        if result:
            if regulation:
                self._cleanup_file(regulation.document_path)
                self._cleanup_file(regulation.source_document_path)
            await self._audit("delete", "regulation", resource_id=regulation_id)
        return result

    # ==================== 修订记录 CRUD ====================

    async def get_revisions(
        self,
        skip: int = 0,
        limit: int = 20,
        regulation_id: uuid.UUID | None = None,
        revision_type: str | None = None,
        review_opinion: str | None = None,
        revision_scope: str | None = None,
    ) -> tuple[list, int]:
        """获取修订记录列表"""
        return await self.repo.get_revisions(
            skip, limit, regulation_id, revision_type, review_opinion, revision_scope
        )

    async def get_revision(self, revision_id: uuid.UUID):
        """获取修订记录详情"""
        return await self.repo.get_revision_by_id(revision_id)

    async def create_revision(self, data) -> Any:
        """创建修订记录

        自动从安全操作规程表获取当前文档链接填入旧文档链接。
        """
        reg = await self.repo.get_regulation_by_id(data.regulation_id)
        if not reg:
            return None

        revision_data = {
            "revision_no": data.revision_no,
            "regulation_id": data.regulation_id,
            "regulation_name": reg.regulation_name,
            "old_document_path": reg.document_path,
            "revision_type": data.revision_type.value if hasattr(data.revision_type, 'value') else data.revision_type,
            "revision_opinion": data.revision_opinion,
            "reviser": data.reviser,
            "reviser_name": data.reviser_name,
            "revision_time": datetime.now(),
            "notes": data.notes,
        }
        item = await self.repo.create_revision(revision_data)
        await self._audit("create", "regulation_revision", resource_id=item.id)
        return item

    async def update_revision(self, revision_id: uuid.UUID, data) -> Any | None:
        """更新修订记录"""
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        item = await self.repo.update_revision(revision_id, update_data)
        if item:
            await self._audit("update", "regulation_revision", resource_id=revision_id)
        return item

    async def delete_revision(self, revision_id: uuid.UUID) -> bool:
        """删除修订记录"""
        revision = await self.repo.get_revision_by_id(revision_id)
        result = await self.repo.delete_revision(revision_id)
        if result:
            if revision:
                self._cleanup_file(revision.old_document_path)
                self._cleanup_file(revision.new_document_path)
            await self._audit("delete", "regulation_revision", resource_id=revision_id)
        return result

    # ==================== 人工修订流程 ====================

    async def manual_revision_complete(
        self,
        revision_id: uuid.UUID,
        new_document_path: str,
        new_document_name: str | None = None,
    ) -> Any | None:
        """完成人工修订：

        1. 将新文档路径填入修订记录
        2. 更新操规表的文档链接和更新日期
        3. 审核意见直接填"已审核"（人工修订无需额外审核）
        4. 触发修订范围识别
        """
        revision = await self.repo.get_revision_by_id(revision_id)
        if not revision or revision.revision_type != "manual":
            return None

        # 更新修订记录：新文档链接 + 审核通过
        await self.repo.update_revision(
            revision_id,
            {
                "new_document_path": new_document_path,
                "review_opinion": "approved",
            },
        )

        # 同步更新操规表：最新文档链接 + 更新时间
        await self.repo.update_regulation(
            revision.regulation_id,
            {
                "document_path": new_document_path,
                "document_original_name": new_document_name,
            },
        )

        # 刷新修订记录以获取最新数据
        await self.session.flush()
        return await self.repo.get_revision_by_id(revision_id)

    # ==================== AI 修订流程 ====================

    async def ai_revision_generate(
        self,
        revision_id: uuid.UUID,
    ) -> dict | None:
        """AI 根据修订意见生成修订版本（不持久化，返回给用户确认）

        返回 {"generated_content": str} 供前端展示对比。
        """
        revision = await self.repo.get_revision_by_id(revision_id)
        if not revision or revision.revision_type != "ai":
            return None

        reg = await self.repo.get_regulation_by_id(revision.regulation_id)
        if not reg:
            return None

        # 读取当前操规文档内容
        current_content = ""
        if reg.document_path:
            try:
                current_content = self._read_document(reg.document_path)
            except Exception as e:
                logger.warning(f"读取文档失败: {e}")
                current_content = "（无法读取当前文档）"

        # 调用 AI 生成修订版本
        generated = await self._ai_generate_revision(
            regulation_name=reg.regulation_name,
            current_content=current_content,
            revision_opinion=revision.revision_opinion or "",
        )

        return {"generated_content": generated}

    async def ai_revision_confirm(
        self,
        revision_id: uuid.UUID,
        generated_content: str,
        document_name: str | None = None,
    ) -> Any | None:
        """用户确认 AI 修订内容后：

        1. 保存新文档到 uploads/
        2. 更新修订记录的 new_document_path
        3. 同步更新操规表
        4. 审核意见填"已审核"
        """
        import os

        revision = await self.repo.get_revision_by_id(revision_id)
        if not revision or revision.revision_type != "ai":
            return None

        # 保存生成的文档
        upload_dir = os.path.join("uploads", "safety", "regulations")
        os.makedirs(upload_dir, exist_ok=True)

        safe_name = f"revision_{revision_id}_{int(datetime.now().timestamp())}.md"
        file_path = os.path.join(upload_dir, safe_name)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(generated_content)

        doc_name = document_name or f"{revision.regulation_name}_修订版_{int(datetime.now().timestamp())}.md"

        # 更新修订记录
        await self.repo.update_revision(
            revision_id,
            {
                "new_document_path": file_path,
                "review_opinion": "approved",
            },
        )

        # 同步更新操规表
        await self.repo.update_regulation(
            revision.regulation_id,
            {
                "document_path": file_path,
                "document_original_name": doc_name,
            },
        )

        await self.session.flush()
        return await self.repo.get_revision_by_id(revision_id)

    # ==================== 修订范围识别（AI） ====================

    async def identify_revision_scope(self, revision_id: uuid.UUID) -> Any | None:
        """AI 识别修订范围（工艺/安全要求）

        在修订完成后（新文档链接已填充）调用。
        分析修订意见内容，识别属于工艺变更还是安全要求变更。
        """
        revision = await self.repo.get_revision_by_id(revision_id)
        if not revision:
            return None

        if not revision.revision_opinion:
            # 无修订意见，默认仅安全要求
            await self.repo.update_revision(revision_id, {"revision_scope": "safety_requirement"})
            await self.session.flush()
            return await self.repo.get_revision_by_id(revision_id)

        # 调用 AI 识别修订范围
        scope_result = await self._ai_identify_scope(
            revision_opinion=revision.revision_opinion,
            revision_type=revision.revision_type,
            regulation_name=revision.regulation_name,
        )

        await self.repo.update_revision(revision_id, {"revision_scope": scope_result})
        await self.session.flush()

        updated = await self.repo.get_revision_by_id(revision_id)

        return updated

    # ==================== AI 辅助方法 ====================

    async def _get_ai_client(self) -> AIService:
        """获取文本模型 AIService（硬编码配置）"""
        from app.modules.safety.service.config import create_ai_service
        return create_ai_service("text")

    async def _ai_identify_scope(
        self,
        revision_opinion: str,
        revision_type: str,
        regulation_name: str,
    ) -> str:
        """AI 识别修订范围

        Returns:
            逗号分隔的范围字符串，如 "process,safety_requirement"
        """
        prompt = f"""你是一个专业的安全生产管理专家。请分析以下操规修订意见，判断修订范围属于"工艺"还是"安全要求"。

操规名称：{regulation_name}
修订类型：{"人工修订" if revision_type == "manual" else "AI修订"}
修订意见：
{revision_opinion}

判断标准：
- 工艺（process）：涉及工艺参数调整、操作步骤变更、工艺条件修改、设备参数调整等
- 安全要求（safety_requirement）：涉及安全措施、防护要求、警示标识、联锁装置、应急措施等

请返回 JSON 格式：
{{"scope": "process" 或 "safety_requirement" 或 "process,safety_requirement"（两者都有时逗号分隔）, "reasoning": "识别依据说明"}}"""

        try:
            ai = await self._get_ai_client()
            result = await ai.chat_parsed(
                messages=[
                    {"role": "system", "content": "你是一个专业的安全生产管理专家，擅长识别操规修订的影响范围。"},
                    {"role": "user", "content": prompt},
                ],
                expected_keys=["scope", "reasoning"],
            )
            await ai.close()
            return result.get("scope", "safety_requirement")
        except AIOutputError:
            logger.warning("AI 识别修订范围失败，默认标记为安全要求")
            return "safety_requirement"
        except Exception as e:
            logger.error(f"AI 识别修订范围异常: {e}")
            return "safety_requirement"

    async def _ai_generate_revision(
        self,
        regulation_name: str,
        current_content: str,
        revision_opinion: str,
    ) -> str:
        """AI 根据修订意见生成新版本的操规文档"""
        prompt = f"""请根据以下修订意见，对安全操作规程进行修订，生成完整的修订后文档。

操规名称：{regulation_name}

当前操规内容：
{current_content if current_content else "（无当前内容，请根据操规名称和修订意见生成完整文档）"}

修订意见：
{revision_opinion}

要求：
1. 生成完整的修订后文档，而非仅修改部分
2. 保持文档的结构和格式
3. 用注释标注修改过的部分，格式为：【修订】原内容 → 新内容
4. 在文档末尾添加修订说明

请直接输出修订后的完整文档内容。"""

        try:
            ai = await self._get_ai_client()
            messages = [
                {"role": "system", "content": "你是一个专业的安全操作规程编写专家，服务于原料药生产企业。"},
                {"role": "user", "content": prompt},
            ]
            # 自由文本生成，使用 chat 方法
            result = await ai.chat(
                messages=messages,
                response_format="text",
                max_tokens=16384,
            )
            await ai.close()
            return result if result else ""
        except Exception as e:
            logger.error(f"AI 生成修订版本失败: {e}")
            raise AIOutputError(f"AI 生成修订版本失败: {e}")

    async def _ai_diff_analysis(
        self,
        old_content: str,
        new_content: str,
        regulation_name: str,
    ) -> dict:
        """AI 识别新旧文档差异（人工修订时使用）"""
        prompt = f"""请对比以下安全操作规程的新旧版本，识别具体差异。

操规名称：{regulation_name}

【旧版本】
{old_content}

【新版本】
{new_content}

请输出 JSON 格式：
{{"has_changes": true/false, "changes": [{{"section": "章节/条款号", "old_text": "旧内容摘要", "new_text": "新内容摘要", "change_type": "新增/修改/删除"}}], "summary": "差异摘要说明"}}"""

        try:
            ai = await self._get_ai_client()
            result = await ai.chat_parsed(
                messages=[
                    {"role": "system", "content": "你是一个专业的文档对比分析专家。"},
                    {"role": "user", "content": prompt},
                ],
                expected_keys=["has_changes", "changes", "summary"],
            )
            await ai.close()
            return result
        except Exception as e:
            logger.error(f"AI 差异分析失败: {e}")
            raise AIOutputError(f"AI 差异分析失败: {e}")

    @staticmethod
    def _read_document(path: str, max_chars: int = 50000) -> str:
        """读取文档内容"""
        import os

        if not os.path.exists(path):
            raise FileNotFoundError(f"文档不存在: {path}")

        with open(path, encoding="utf-8") as f:
            content = f.read(max_chars)
        return content

    # ==================== 文档上传处理 ====================

    async def upload_regulation_document(
        self, regulation_id: uuid.UUID, file_name: str, file_path: str
    ) -> Any | None:
        """上传操规文档并更新操规记录"""
        return await self.repo.update_regulation(
            regulation_id,
            {
                "document_path": file_path,
                "document_original_name": file_name,
            },
        )

    # ==================== 在线修订流程 ====================

    async def revise_regulation(
        self,
        regulation_id: uuid.UUID,
        content: str,
        revision_opinion: str | None = None,
        reviser_name: str | None = None,
    ) -> dict | None:
        """在线修订操规：保存内容并自动生成修订记录。

        1. 获取当前操规，保存旧文档路径
        2. 更新操规内容 + 状态为 reviewed
        3. 自动生成修订编号并创建修订记录
        4. 返回 regulation_id + revision_id + revision_no
        """
        regulation = await self.repo.get_regulation_by_id(regulation_id)
        if not regulation:
            return None

        # 保存旧文档路径（用于修订记录）
        old_doc_path = regulation.document_path

        # 更新操规内容和状态
        await self.repo.update_regulation(
            regulation_id,
            {
                "content": content,
                "status": "reviewed",
            },
        )

        # 自动生成修订编号：REV-{操规编号}-{时间戳}
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        revision_no = f"REV-{regulation.regulation_no}-{ts}"

        # 创建修订记录
        revision_data = {
            "revision_no": revision_no,
            "regulation_id": regulation_id,
            "regulation_name": regulation.regulation_name,
            "old_document_path": old_doc_path,
            "revision_type": "manual",
            "revision_opinion": revision_opinion,
            "reviser_name": reviser_name,
            "revision_time": datetime.now(),
            "review_opinion": "approved",  # 直接编辑即审核通过
        }
        revision = await self.repo.create_revision(revision_data)

        await self._audit(
            "revise",
            "regulation",
            resource_id=regulation_id,
            extra={
                "revision_id": str(revision.id),
                "revision_no": revision_no,
                "reviser_name": reviser_name,
            },
        )

        await self.session.flush()

        return {
            "regulation_id": regulation_id,
            "revision_id": revision.id,
            "revision_no": revision_no,
            "regulation_name": regulation.regulation_name,
            "status": "reviewed",
        }


# ==================== AI 配置 Service ====================


