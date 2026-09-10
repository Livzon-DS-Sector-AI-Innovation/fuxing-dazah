"""MSDS 智能提取入库 — Service 层。

管线（对标应急演练系统收录表模式）：
  供应商资料表（Bitable）→ msds_collection_records（采集）
    → _run_parse：下载附件 + AI 提取 28 字段【数组】（按化学品拆分）
    → _create_registry_entries：写回 MSDS 表（同 CAS UPDATE / 新建）+ 标准 PDF 挂「MSDS附件」
    → MSDS 表事件镜像 → msds_documents（1 采集 → N 台账）
"""

from __future__ import annotations

import logging
import mimetypes
import tempfile
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.ai_audit import ai_audit_scope
from app.modules.safety.attachment_store import (
    cleanup_temp,
    materialize,
    resolve_local_path,
    store_bytes,
)
from app.modules.safety.bitable_config.store import store
from app.modules.safety.feishu.msds_pdf import (
    build_standard_msds_pdf,
    standard_pdf_filename,
)
from app.modules.safety.knowledge.msds_indexer import sync_msds_document_to_knowledge
from app.modules.safety.models import MsdsCollectionRecord, MsdsDocument

logger = logging.getLogger(__name__)

# AI 提取 entry 字段 → MSDS 表 Bitable 中文字段名
# label_elements 不在 MSDS 表（无该字段），写回时丢弃，仅平台存档（spec 决策 Q5）
ENTRY_TO_BITABLE_FIELD: dict[str, str] = {
    "name": "物质名称",
    "cas_no": "CAS号",
    "molecular_formula": "分子式",
    "un_no": "UN编号",
    "hazard_statement": "危险性说明",
    "appearance": "外观与现状",
    "solubility": "溶解性",
    "melting_point": "熔点",
    "boiling_point": "沸点",
    "flash_point": "闪点",
    "relative_density": "相对密度",
    "explosion_upper_limit": "爆炸上限",
    "explosion_lower_limit": "爆炸下限",
    "autoignition_temperature": "自燃温度",
    "decomposition_temperature": "分解温度",
    "pc_twa": "PC-TWA",
    "pc_stel": "PC-STEL",
    "mac": "MAC",
    "health_hazard": "健康危害",
    "environmental_hazard": "环境危害",
    "first_aid": "急救措施",
    "fire_fighting": "消防措施",
    "leakage_response": "泄漏应急处理",
    "waste_disposal": "废弃处置",
    "exposure_controls": "接触控制与个体防护",
    "handling_storage": "操作处置与储存注意事项",
    "stability_reactivity": "稳定性和反应性",
}

# AI 提取 system prompt（稳定内容，遵守前缀缓存规则：system 固定、变量放 user 末尾）
MSDS_EXTRACT_SYSTEM_PROMPT = """你是化学品安全数据表（MSDS/SDS）结构化提取专家。

从用户提供的供应商 MSDS 文档全文中，识别每个独立化学品的安全数据段落，提取结构化字段。

## 字段定义（28 个，对应英文键）
基础标识：
- name（物质名称）
- cas_no（CAS号）
- molecular_formula（分子式）
- un_no（UN编号，无则填"非危险化学品"或 null）

危险性概述：
- hazard_statement（危险性说明/危险概述，如"高度易燃液体和蒸气"）
- label_elements（标签要素/象形图说明，如 GHS 警示语）

理化特性：
- appearance（外观与现状）
- solubility（溶解性）
- melting_point（熔点）
- boiling_point（沸点）
- flash_point（闪点）
- relative_density（相对密度，注意水=1；若原文为蒸气密度请加注"蒸气密度"）
- explosion_upper_limit（爆炸上限%）
- explosion_lower_limit（爆炸下限%）
- autoignition_temperature（自燃温度）
- decomposition_temperature（分解温度）

职业接触限值：
- pc_twa（时间加权平均容许浓度 PC-TWA）
- pc_stel（短时间接触容许浓度 PC-STEL）
- mac（最高容许浓度 MAC）

健康与环境危害：
- health_hazard（健康危害）
- environmental_hazard（环境危害）

应急响应：
- first_aid（急救措施，含皮肤/眼睛/吸入/食入/医生提示）
- fire_fighting（消防措施，含灭火剂/危险特性/灭火注意事项）
- leakage_response（泄漏应急处理）
- waste_disposal（废弃处置）

防护与控制：
- exposure_controls（接触控制与个体防护，含工程控制/呼吸/眼睛/身体/手防护）
- handling_storage（操作处置与储存注意事项）
- stability_reactivity（稳定性和反应性，含稳定性/禁配物/聚合危害）

## 提取规则
1. 一个文档可能包含多个化学品的 MSDS 段落，每个化学品有独立的名称/CAS号标识。按化学品拆分，每个化学品输出一个条目。
2. 每条完整输出上述全部 28 个字段；文档中未出现的字段输出 null，不要编造。
3. 数值字段保留原始单位字符串（如"12℃（CC）"、"232-249℃"、"350mg/m3"），不要换算。
4. 原文标注"无资料""/""无意义"时保留原文并输出（不要转成 null）。
5. 相对密度要区分水相对密度与蒸气密度：如原文是蒸气密度（明显 >1 且小于对应液体密度场景），在值后标注"（蒸气密度）"。
6. 物质名称含多个别名时保留原名（如"2-丙醇;异丙醇"）。

## 输出格式
只输出 JSON 对象：
{"entries": [ {28个字段对象}, ... ]}
禁止输出任何其他文字。"""


class MsdsService:
    """MSDS 服务 — 采集 / 解析 / 写回 / 台账查询。"""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ═══════════════════════════════════════════════════════════════
    # 解析管线
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    async def extract_entries(document_text: str) -> list[dict]:
        """AI 从文档全文提取 28 字段【数组】（一个化学品一条）。

        返回 [] 表示提取失败（无 entries 或空）。
        """
        from app.modules.safety.service.config import create_ai_service

        with ai_audit_scope(
            scenario="msds_extraction",
            channel="system",
            resource_type="msds_collection",
        ):
            ai = create_ai_service("text")
            try:
                result = await ai.chat_parsed(
                    messages=[
                        {"role": "system", "content": MSDS_EXTRACT_SYSTEM_PROMPT},
                        # 变量数据放 user 末尾（前缀缓存友好）
                        {"role": "user", "content": f"以下是供应商 MSDS 文档全文：\n\n{document_text}"},
                    ],
                    expected_keys=["entries"],
                    temperature=0.1,
                )
            finally:
                await ai.close()
        entries = result.get("entries") or []
        if not isinstance(entries, list):
            return []
        return [e for e in entries if isinstance(e, dict)]

    async def run_parse(self, collection_id: uuid.UUID) -> MsdsCollectionRecord | None:
        """执行采集记录解析：下载附件 → 解析全文 → AI 提取 → 落库。

        必填缺失不判失败（允许空值建档，见 spec 决策 Q4）；
        整份文档无法解析（无附件/无文本/AI 返回空）→ parse_status=failed。
        """
        rec = await self.db.get(MsdsCollectionRecord, collection_id)
        if not rec or rec.is_deleted:
            return None

        try:
            attachment_path, file_name = await self._download_attachment(rec)
            if not attachment_path:
                raise RuntimeError("附件下载失败")

            document_text = self._parse_document_to_text(attachment_path, file_name)
            if not document_text:
                raise RuntimeError("文档解析无有效文本")

            entries = await self.extract_entries(document_text)
            if not entries:
                raise RuntimeError("AI 提取无结果")

            rec.parse_result = entries
            rec.attachment_path = str(attachment_path)
            rec.parse_status = "parsed"
            rec.parse_error = None
        except Exception as e:
            logger.exception("MSDS 解析失败: collection=%s", collection_id)
            rec.parse_status = "failed"
            rec.parse_error = str(e)[:2000]

        await self.db.commit()
        return rec

    async def _download_attachment(self, rec: MsdsCollectionRecord) -> tuple[str | None, str]:
        """下载采集记录第一个附件入桶（预签名 URL 优先，file_token 兜底）。

        Returns:
            (存储标识, 文件名)：MinIO 模式为 object key（如 ``msds/xxx.pdf``），
            本地模式为相对路径（如 ``safety/msds/xxx.pdf``）。
        """
        from app.modules.safety.feishu.bitable_client import SafetyBitableClient

        attachments = rec.attachment or []
        if not attachments or not isinstance(attachments, list):
            return None, ""
        first = attachments[0]
        if not isinstance(first, dict):
            return None, ""
        file_name = first.get("name", "msds")
        file_token = first.get("file_token", "")
        download_url = first.get("url", "") or first.get("tmp_url", "")

        client = SafetyBitableClient()
        safe_name = file_name.replace("/", "_").replace("\\", "_")

        data: bytes | None = None
        if download_url:
            try:
                data = await client.download_attachment_from_url(download_url)
            except Exception:
                logger.warning("预签名 URL 下载失败, 回退 file_token: %s", file_name)
        if not data and file_token:
            try:
                data = await client.download_attachment(file_token)
            except Exception:
                logger.exception("file_token 下载失败: %s", file_name)

        if not data:
            return None, file_name

        key = store_bytes(
            "msds",
            f"msds_{rec.feishu_record_id or rec.id}_{safe_name}",
            data,
            content_type=mimetypes.guess_type(safe_name)[0]
            or "application/octet-stream",
        )
        logger.info("MSDS 附件下载完成: %s (%d bytes)", key, len(data))
        return key, file_name

    @staticmethod
    def _parse_document_to_text(file_path: str, file_name: str) -> str:
        """解析文档为纯文本（SafetyDocumentParser + 平台 fallback）。

        回读适配：``file_path`` 可能是 MinIO object key——本地未命中时经
        attachment_store 物化到临时文件解析，解析后清理临时文件。
        """
        local = resolve_local_path(file_path)
        is_temp = False
        if local is None:
            tmp = materialize(file_path)
            if tmp is None:
                logger.warning("MSDS 附件回读失败（本地与 MinIO 均未命中）: %s", file_path)
                return ""
            local = tmp
            is_temp = True
        try:
            try:
                from app.modules.safety.knowledge.document_parser import (
                    SafetyDocumentParser,
                )

                text = SafetyDocumentParser.extract_text(str(local), max_chars=100000)
                if text and len(text.strip()) > 20:
                    logger.info("MSDS 文档解析: %s → %d chars", file_name, len(text))
                    return text
            except Exception:
                logger.warning("SafetyDocumentParser failed", exc_info=True)
            try:
                from app.platform.integrations.ai.document_parser import DocumentParser

                text = DocumentParser().parse(local)
                if text and len(text.strip()) > 20:
                    logger.info("MSDS 文档解析(fallback): %s → %d chars", file_name, len(text))
                    return text
            except Exception:
                logger.exception("All document parsers failed")
            return ""
        finally:
            if is_temp:
                cleanup_temp(local)

    # ═══════════════════════════════════════════════════════════════
    # 写回管线（解析 → 标准 PDF → MSDS 表记录）
    # ═══════════════════════════════════════════════════════════════

    async def process_collection(self, collection_id: uuid.UUID) -> MsdsCollectionRecord | None:
        """采集记录完整处理：解析 + 自动写回 MSDS 表（同演练系统管线，无人工按钮）。"""
        rec = await self.run_parse(collection_id)
        if rec and rec.parse_status == "parsed":
            await self._create_registry_entries(collection_id)
        return rec

    async def _create_registry_entries(self, collection_id: uuid.UUID) -> list[str]:
        """遍历 parse_result，为每个化学品生成标准 PDF 并在 MSDS 表创建/更新记录。

        同 CAS 已存在 → UPDATE（刷新 29 字段 + 替换「MSDS附件」，spec 决策 Q3）；
        否则 create_record。单条失败重试不阻塞其他化学品。
        返回写回的 MSDS 表 feishu_record_id 列表。
        """
        from app.modules.safety.feishu.bitable_client import SafetyBitableClient

        rec = await self.db.get(MsdsCollectionRecord, collection_id)
        if not rec or rec.is_deleted:
            return []
        entries = rec.parse_result or []
        if not entries:
            return []

        conn = store.get_connection("msds", "registry")
        if conn is None or conn.status == "disabled":
            logger.warning("MSDS 表未配置, 跳过写回: collection=%s", collection_id)
            return []

        msds_client = SafetyBitableClient(app_token=conn.app_token, table_id=conn.table_id)
        created_ids: list[str] = []
        # record_id → msds_documents 列值（含本地标准 PDF 路径）
        registry_rows: dict[str, dict] = {}

        for idx, entry in enumerate(entries):
            try:
                # ① 生成标准 PDF → 临时文件 → store_bytes 入桶（MinIO key / 本地相对路径）
                filename = standard_pdf_filename(entry, str(rec.id), idx)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp_path = tmp.name
                try:
                    build_standard_msds_pdf(entry, tmp_path)
                    with open(tmp_path, "rb") as f:
                        pdf_bytes = f.read()
                finally:
                    cleanup_temp(tmp_path)
                std_pdf_path = store_bytes(
                    "msds", filename, pdf_bytes, content_type="application/pdf",
                )

                # ② 上传到飞书 Drive（upload_media 兼容 MinIO key / 本地路径）
                upload = await msds_client.upload_media(std_pdf_path, filename)
                if not upload:
                    logger.warning("标准 PDF 上传失败, 跳过: %s", filename)
                    continue

                # ③ 构造 MSDS 表字段（label_elements 丢弃）
                fields: dict = {
                    bitable_field: entry[entry_key]
                    for entry_key, bitable_field in ENTRY_TO_BITABLE_FIELD.items()
                    if entry.get(entry_key)
                }
                fields["MSDS附件"] = [upload]
                if rec.source_date:
                    fields["日期"] = int(
                        datetime.combine(rec.source_date, datetime.min.time(), tzinfo=UTC).timestamp() * 1000
                    )

                # ④ 同 CAS 查重 → UPDATE / CREATE
                existing = await self._find_msds_by_cas(msds_client, entry.get("cas_no"))
                target_id = existing
                if existing:
                    ok = await msds_client.update_record(record_id=existing, fields=fields)
                    if ok:
                        created_ids.append(existing)
                        logger.info("MSDS 写回 UPDATE: %s cas=%s", existing, entry.get("cas_no"))
                else:
                    result = await msds_client.create_record(fields=fields)
                    if result:
                        target_id = result["record_id"]
                        created_ids.append(target_id)
                        logger.info(
                            "MSDS 写回 CREATE: %s name=%s", result["record_id"], entry.get("name")
                        )

                if target_id:
                    # 记录镜像行数据（含标准 PDF 存储标识，供前端 files proxy 下载）
                    row_values: dict = {
                        key: entry.get(key)
                        for key in ENTRY_TO_BITABLE_FIELD
                        if entry.get(key)
                    }
                    row_values.update({
                        "feishu_record_id": target_id,
                        "collection_record_id": collection_id,
                        "msds_attachment": [upload],
                        "msds_attachment_path": std_pdf_path,
                    })
                    registry_rows[target_id] = row_values
            except Exception:
                logger.exception("MSDS 写回条目失败: collection=%s idx=%d", collection_id, idx)

        # ⑤ 同步/创建 msds_documents 镜像行（UPSERT：行不存在则创建，存在则补路径）
        #    确保标准 PDF 存储标识可用，不依赖 WS 事件镜像的时序
        if registry_rows:
            try:
                for record_id, row_values in registry_rows.items():
                    existing_row = await self.db.scalar(
                        select(MsdsDocument).where(MsdsDocument.feishu_record_id == record_id)
                    )
                    if existing_row:
                        existing_row.msds_attachment_path = row_values["msds_attachment_path"]
                        if row_values.get("collection_record_id"):
                            existing_row.collection_record_id = row_values["collection_record_id"]
                        if row_values.get("msds_attachment"):
                            existing_row.msds_attachment = row_values["msds_attachment"]
                    else:
                        self.db.add(MsdsDocument(**row_values))
                await self.db.commit()
            except Exception:
                logger.exception("MSDS 标准 PDF 路径同步失败")

        rec.msds_table_record_ids = created_ids
        rec.synced_at = datetime.now(UTC)
        await self.db.commit()

        # ⑥ 同步知识库索引（MSDS → knowledge_articles + chunks，幂等）
        #    让新写回/更新的台账可被知识库检索；失败仅记日志不阻塞写回。
        if registry_rows:
            for record_id in registry_rows:
                try:
                    row = await self.db.scalar(
                        select(MsdsDocument).where(
                            MsdsDocument.feishu_record_id == record_id,
                            MsdsDocument.is_deleted == False,  # noqa: E712
                        )
                    )
                    if row:
                        await sync_msds_document_to_knowledge(row.id, session=self.db)
                except Exception:
                    logger.exception("MSDS 知识索引同步失败: record_id=%s", record_id)
            await self.db.commit()

        logger.info(
            "MSDS 写回完成: collection=%s → %d 条", collection_id, len(created_ids)
        )
        return created_ids

    async def _find_msds_by_cas(self, client, cas_no: str | None) -> str | None:
        """按 CAS号 在 MSDS 表查找已有记录，返回 record_id 或 None。"""
        if not cas_no:
            return None
        try:
            result = await client.search_records(
                filter_info={
                    "conjunction": "and",
                    "conditions": [{"field_name": "CAS号", "operator": "is", "value": [cas_no]}],
                }
            )
            items = result.get("items") or []
            if items:
                return items[0].get("record_id") or items[0].get("id")
        except Exception:
            logger.exception("MSDS CAS 查重失败: %s", cas_no)
        return None

    # ═══════════════════════════════════════════════════════════════
    # 查询
    # ═══════════════════════════════════════════════════════════════


    async def list_collections(
        self,
        skip: int,
        limit: int,
        *,
        parse_status: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[MsdsCollectionRecord], int]:
        """供应商资料采集列表（分页 + 解析状态/关键词筛选）。"""
        filters = [MsdsCollectionRecord.is_deleted == False]  # noqa: E712
        if parse_status:
            filters.append(MsdsCollectionRecord.parse_status == parse_status)
        if keyword:
            filters.append(MsdsCollectionRecord.feishu_record_id.ilike(f"%{keyword}%"))

        total = await self.db.scalar(
            select(func.count()).select_from(MsdsCollectionRecord).where(*filters)
        )
        stmt = (
            select(MsdsCollectionRecord)
            .where(*filters)
            .order_by(MsdsCollectionRecord.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        items = (await self.db.scalars(stmt)).all()
        return list(items), int(total or 0)

    async def get_collection(self, collection_id) -> MsdsCollectionRecord | None:
        """采集记录详情。"""
        return await self.db.get(MsdsCollectionRecord, collection_id)

    async def list_documents(
        self,
        skip: int,
        limit: int,
        *,
        name: str | None = None,
        cas_no: str | None = None,
        review_status: str | None = None,
        archive_status: str | None = None,
    ) -> tuple[list[MsdsDocument], int]:
        """MSDS 台账列表（分页 + 筛选）。"""
        filters = [MsdsDocument.is_deleted == False]  # noqa: E712
        if name:
            filters.append(MsdsDocument.name.ilike(f"%{name}%"))
        if cas_no:
            filters.append(MsdsDocument.cas_no.ilike(f"%{cas_no}%"))
        if review_status:
            filters.append(MsdsDocument.review_status == review_status)
        if archive_status:
            filters.append(MsdsDocument.archive_status == archive_status)

        total = await self.db.scalar(
            select(func.count()).select_from(MsdsDocument).where(*filters)
        )
        stmt = (
            select(MsdsDocument)
            .where(*filters)
            .order_by(MsdsDocument.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        items = (await self.db.scalars(stmt)).all()
        return list(items), int(total or 0)

    async def get_document(self, document_id) -> MsdsDocument | None:
        """台账详情。"""
        return await self.db.get(MsdsDocument, document_id)

    async def get_stats(self) -> dict:
        """统计仪表盘（采集/台账分组计数）。"""
        collections_total = await self.db.scalar(
            select(func.count()).select_from(MsdsCollectionRecord).where(
                MsdsCollectionRecord.is_deleted == False  # noqa: E712
            )
        )
        docs_total = await self.db.scalar(
            select(func.count()).select_from(MsdsDocument).where(
                MsdsDocument.is_deleted == False  # noqa: E712
            )
        )
        docs_archived = await self.db.scalar(
            select(func.count()).select_from(MsdsDocument).where(
                MsdsDocument.is_deleted == False,  # noqa: E712
                MsdsDocument.archive_status == "archived",
            )
        )

        # 按解析状态分组
        parse_rows = (
            await self.db.execute(
                select(MsdsCollectionRecord.parse_status, func.count())
                .where(MsdsCollectionRecord.is_deleted == False)  # noqa: E712
                .group_by(MsdsCollectionRecord.parse_status)
            )
        ).all()
        by_parse_status = {status: count for status, count in parse_rows}

        # 按复核状态分组
        review_rows = (
            await self.db.execute(
                select(MsdsDocument.review_status, func.count())
                .where(MsdsDocument.is_deleted == False)  # noqa: E712
                .group_by(MsdsDocument.review_status)
            )
        ).all()
        by_review_status = {status: count for status, count in review_rows}

        return {
            "total_collections": int(collections_total or 0),
            "parsed_collections": by_parse_status.get("parsed", 0),
            "failed_collections": by_parse_status.get("failed", 0),
            "total_documents": int(docs_total or 0),
            "archived_documents": int(docs_archived or 0),
            "by_parse_status": by_parse_status,
            "by_review_status": by_review_status,
        }
