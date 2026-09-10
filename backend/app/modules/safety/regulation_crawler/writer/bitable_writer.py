"""Bitable 写入适配器：爬取结果 → 飞书多维表格中文字段。

写入目标：飞书多维表格「法规标准清单」（knowledge_bitable_handler.py 监听的同一张表）。
写入后由 knowledge_bitable_handler 自动同步到 PostgreSQL，无需本模块处理。

去重策略（三层匹配）：
  L1 精确标题 → duplicate，跳过
  L2 标准号/文号 → 同年份=duplicate，不同年份=update（删旧写新）
  L3 归一化标题 → 标题包含+日期更新=update，否则=duplicate
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from app.modules.safety.bitable_config.store import store
from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.regulation_crawler.schemas import CrawledRegulation

logger = logging.getLogger(__name__)

# ── 字段映射：CrawledRegulation 属性 → Bitable 中文字段名 ──

CRAWLED_TO_BITABLE_MAP: dict[str, str] = {
    "title": "法律法规及标准名称",
    "issuing_authority": "颁布机关",
    "publish_date": "颁布修订日期",
    "implementation_date": "实施日期",
    "status": "法规状态",
    "core_summary": "核心要点总结",
}

# ── 法规层级 → Bitable 法规类别（选择字段） ──

LEVEL_TO_CATEGORY: dict[str, str] = {
    "法律": "安全类",
    "行政法规": "安全类",
    "部门规章": "安全类",
    "地方性法规": "安全类",
    "标准规范": "特种设备",
    "国家标准": "特种设备",
    "行业标准": "特种设备",
}

# ── 业务领域 → Bitable 法规类别 ──

DOMAIN_TO_CATEGORY: dict[str, str] = {
    "安全生产": "安全类",
    "消防安全": "建筑防火与消防",
    "特种设备": "特种设备",
    "特殊作业": "特殊作业",
    "职业健康": "职业健康",
    "环境保护": "环境类",
    "危化品管理": "化学品管理",
    "药品GMP": "安全类",
    "通用": "其他相关法规",
}

# ── 类别 → 知识库分家表（2026-09-01 法规标准拆为安全/环保两表） ──
_ENV_CATEGORY = "环境类"

# ── 已废止状态标识 ──
_STATUS_REPEALED = "已废止"


class BitableWriter:
    """将爬取的法规写入飞书多维表格。

    2026-09-01 法规标准分家：knowledge 域两张表——
    collection（安全法规标准）/ collection_env（环保法规标准）。
    按「法规类别」路由：环境类 → 环保表，其余 → 安全表。
    """

    def __init__(self) -> None:
        # 凭证延迟读 store（knowledge/collection + collection_env 连接）：
        # 改表 ID 后写入立即指向新表。
        self.safety_conn = store.get_connection("knowledge", "collection")
        self.env_conn = store.get_connection("knowledge", "collection_env")
        self.safety_bitable = self._build_client(self.safety_conn)
        self.env_bitable = self._build_client(self.env_conn)

    @staticmethod
    def _build_client(conn) -> SafetyBitableClient:
        if conn is None or conn.status == "disabled":
            return SafetyBitableClient()
        return SafetyBitableClient(app_token=conn.app_token, table_id=conn.table_id)

    def _client_for(self, category: str) -> SafetyBitableClient:
        """按 Bitable 法规类别路由到安全/环保表 client。"""
        return self.env_bitable if category == _ENV_CATEGORY else self.safety_bitable

    # ── 公共接口 ──

    async def preflight_check(self, item: CrawledRegulation) -> str:
        """写入前预检（只读，不写入）：判断条目最终是否会入库。

        返回:
          - "repealed":   已废止/失效条目（将触发旧记录删除，无需下载附件）
          - "duplicate":  与 Bitable 已有记录重复（跳过，无需下载附件）
          - "update":     同法规新版本（将删旧写新，需要附件）
          - "new":        全新法规（需要附件）
          - "error":      去重判断失败（调用方应保守处理）
        """
        bitable = self._client_for(self._map_category(item))
        bitable_fields = self._map_fields(item)
        title = bitable_fields.get("法律法规及标准名称", "")
        if item.status and _STATUS_REPEALED in item.status:
            return "repealed"
        decision, _ = await self._classify(bitable, title, item)
        return decision

    async def write_regulation(self, item: CrawledRegulation) -> dict | None:
        """将一条法规写入 Bitable。返回 {"record_id": ..., "shared_url": ...}，重复时返回 None。

        处理流程：
        - 状态为「已废止」→ 查找并删除 Bitable 中已有记录，返回 None
        - 三层去重分类 → duplicate(跳过) / update(删旧写新) / new(直接写入)
        """
        bitable = self._client_for(self._map_category(item))
        bitable_fields = self._map_fields(item)
        title = bitable_fields.get("法律法规及标准名称", "")

        # ── 已废止：删除已有记录 ──
        if item.status and _STATUS_REPEALED in item.status:
            deleted_any = await self._handle_repealed(bitable, title)
            # 只在真正删除了 Bitable 记录时返回 deleted（供 service 层计数废止）；
            # 无匹配记录可删说明该废止项此前已处理过，返回 None 走重复跳过
            if deleted_any:
                return {"action": "deleted"}
            return None

        # ── 三层去重分类 ──
        decision, matched_record = await self._classify(bitable, title, item)

        if decision == "duplicate":
            logger.info("重复法规，跳过: %s", title[:80])
            return None

        if decision == "error":
            logger.warning("去重异常，跳过写入: %s", title[:80])
            return None

        if decision == "update":
            # 删除旧版记录（Bitable DELETE 事件会触发 knowledge_bitable_handler
            # 自动软删除 knowledge_articles + 图谱重建）
            await self._handle_update(bitable, matched_record, item)
            # 在备注中记录替代关系
            old_title = (matched_record.get("fields", {}) or {}).get("法律法规及标准名称", "")
            if old_title:
                existing_notes = bitable_fields.get("备注", "")
                replacement_note = f"替代《{old_title}》"
                if existing_notes:
                    bitable_fields["备注"] = f"{existing_notes} | {replacement_note}"
                else:
                    bitable_fields["备注"] = replacement_note

        # ── 写入前二次 L1 检查（防并发竞态） ──
        if decision == "new":
            import asyncio as _asyncio
            import random as _random

            # 随机延迟 0.1-1.0 秒，错开并发写入时序
            await _asyncio.sleep(_random.uniform(0.1, 1.0))
            recheck = await bitable.search_records(
                filter_info={
                    "conjunction": "and",
                    "conditions": [
                        {"field_name": "法律法规及标准名称", "operator": "is", "value": [title]},
                    ],
                },
                page_size=3,
            )
            if recheck.get("items"):
                logger.info("TOCTOU 保护：写入前二次检查命中，跳过: %s", title[:80])
                return None

        # ── 创建记录 ──
        result = await bitable.create_record(bitable_fields)
        if result is None:
            logger.error("Bitable 创建记录失败: %s", title)
            return None

        record_id = result.get("record_id", "")
        if not record_id:
            return None

        # 优先使用 create_record 返回的 shared_url（飞书 API 返回 /record/ 格式）
        shared_url = result.get("shared_url", "")
        if not shared_url:
            shared_url = await bitable.get_record_shared_url(record_id)
        action = "updated" if decision == "update" else "created"
        logger.info("Bitable %s成功: title=%s record_id=%s shared_url=%s", action, title, record_id, shared_url[:80])
        return {"record_id": record_id, "shared_url": shared_url, "action": action}

    # ── 已废止处理 ──

    async def _handle_repealed(self, bitable: SafetyBitableClient, title: str) -> bool:
        """查找并删除 Bitable 中匹配的已废止法规记录。

        返回 True = 本次实际删除了至少一条记录（真实废止变更）；
        返回 False = 无匹配记录可删（该废止项此前已处理过，视为重复）。
        """
        if not title:
            return False
        try:
            # 先精确匹配
            result = await bitable.search_records(
                filter_info={
                    "conjunction": "and",
                    "conditions": [{"field_name": "法律法规及标准名称", "operator": "is", "value": [title]}],
                },
                page_size=5,
            )
            items = result.get("items", [])
            if items:
                deleted_any = False
                for item in items:
                    rid = item.get("record_id", "")
                    if rid:
                        deleted = await bitable.delete_record(rid)
                        if deleted:
                            deleted_any = True
                            logger.info("已删除废止法规: title=%s record_id=%s", title, rid)
                return deleted_any

            # 精确未匹配，尝试归一化标题模糊匹配后删除
            norm = _normalize_title(title)
            if len(norm) >= 4:
                all_records = await bitable.list_all_records(page_size=500)
                for record in all_records:
                    existing_title = (record.get("fields", {}) or {}).get("法律法规及标准名称", "")
                    existing_norm = _normalize_title(existing_title)
                    if len(existing_norm) >= 4 and (norm == existing_norm or norm in existing_norm or existing_norm in norm):
                        rid = record.get("record_id", "")
                        if rid:
                            deleted = await bitable.delete_record(rid)
                            if deleted:
                                logger.info(
                                    "已删除废止法规(模糊匹配): title=%s → %s record_id=%s",
                                    title, existing_title, rid,
                                )
                                return True
                        break
            return False
        except Exception:
            logger.exception("处理废止法规失败: title=%s", title)
            return False

    # ── 字段映射 ──

    def _map_fields(self, item: CrawledRegulation) -> dict[str, Any]:
        """将 CrawledRegulation 映射为 Bitable 中文字段 dict。"""
        fields: dict[str, Any] = {}

        # 标题（必填，剥离末尾日期后缀避免破坏去重）
        if item.title:
            clean = _TRAILING_DATE_RE.sub("", item.title.strip()).strip()
            if len(clean) >= 3:
                fields["法律法规及标准名称"] = clean
            else:
                fields["法律法规及标准名称"] = item.title.strip()

        # 颁布机关
        if item.issuing_authority:
            fields["颁布机关"] = item.issuing_authority.strip()

        # 日期 → Bitable 毫秒时间戳
        if item.publish_date:
            ts = self._parse_date_millis(item.publish_date)
            if ts:
                fields["颁布修订日期"] = ts

        if item.implementation_date:
            ts = self._parse_date_millis(item.implementation_date)
            if ts:
                fields["实施日期"] = ts

        # 时效状态（非废止），默认现行有效
        if item.status and _STATUS_REPEALED not in item.status:
            fields["法规状态"] = self._normalize_status(item.status)
        elif not item.status:
            fields["法规状态"] = "现行有效"

        # 法规类别：优先用 AI 判定的业务领域，其次用法规层级
        fields["法规类别"] = self._map_category(item)

        # 核心要点总结：AI 摘要 + 应对建议合并
        summary_parts: list[str] = []
        if item.core_summary:
            summary_parts.append(item.core_summary.strip())
        if item.action_recommendations:
            summary_parts.append(f"\n\n【应对建议】\n{item.action_recommendations.strip()}")
        if summary_parts:
            fields["核心要点总结"] = "".join(summary_parts)

        # 备注：文号 + 来源URL + 来源类型 + 影响等级 + 替代法规 + 对比摘要 + 原文待补
        notes_parts: list[str] = []
        if item.document_number:
            notes_parts.append(f"文号: {item.document_number}")
        if item.source_url:
            notes_parts.append(f"来源链接: {item.source_url}")
        if item.source_type:
            notes_parts.append(f"来源: {item.source_type}")
        if item.impact_level:
            notes_parts.append(f"影响等级: {item.impact_level}")
        if item.related_old_title:
            notes_parts.append(f"替代: {item.related_old_title}")
        if item.comparison_summary:
            notes_parts.append(f"主要变化: {item.comparison_summary}")
        if item.attachment_pending_reason:
            notes_parts.append(item.attachment_pending_reason)
        if notes_parts:
            fields["备注"] = " | ".join(notes_parts)

        # 更新状态
        if item.update_status:
            fields["更新状态"] = item.update_status

        # 法规原件（附件字段，需 file_token + name）——主附件 + 额外附件
        attachment_tokens: list[dict[str, str]] = []
        if item.attachment_file_token and item.attachment_name:
            attachment_tokens.append(
                {"file_token": item.attachment_file_token, "name": item.attachment_name},
            )
        for extra in item.extra_attachments:
            if extra.get("file_token"):
                attachment_tokens.append(
                    {"file_token": extra["file_token"], "name": extra.get("name") or "附件"},
                )
        if attachment_tokens:
            fields["法规原件"] = attachment_tokens

        return fields

    @staticmethod
    def _map_category(item: CrawledRegulation) -> str:
        """综合 AI 业务领域和法规层级确定 Bitable 法规类别。"""
        # 优先使用 AI 判定的业务领域
        if item.business_domains:
            for domain in item.business_domains:
                cat = DOMAIN_TO_CATEGORY.get(domain)
                if cat:
                    return cat
        # 回退到法规层级映射
        if item.regulation_level:
            return LEVEL_TO_CATEGORY.get(item.regulation_level, "其他相关法规")
        return "其他相关法规"

    # ── 去重（三层匹配：精确 → 标准号/文号 → 归一化标题） ──

    async def _classify(
        self, bitable: SafetyBitableClient, title: str, item: CrawledRegulation,
    ) -> tuple[str, dict[str, Any] | None]:
        """将待写入法规与 Bitable 已有记录比对，返回 (decision, matched_record)。

        ``bitable`` 为按类别路由后的表 client（安全或环保表），去重在对应表内进行。

        decision:
          - "duplicate": 完全相同，跳过写入
          - "update":    同一法规的新版本，删除旧记录后写入新记录
          - "new":       全新法规，正常写入
        """
        if not title:
            return ("new", None)

        try:
            # ── L1: 精确标题匹配 ──
            result = await bitable.search_records(
                filter_info={
                    "conjunction": "and",
                    "conditions": [
                        {"field_name": "法律法规及标准名称", "operator": "is", "value": [title]},
                    ],
                },
                page_size=3,
            )
            if result.get("items"):
                logger.info("L1 精确匹配 → duplicate: %s", title[:80])
                return ("duplicate", result["items"][0])

            # ── L2: 标准号/文号匹配 ──
            std_num, std_year = _extract_standard_identifier(title)
            if std_num:
                std_result = await bitable.search_records(
                    filter_info={
                        "conjunction": "and",
                        "conditions": [
                            {"field_name": "法律法规及标准名称", "operator": "contains", "value": [std_num]},
                        ],
                    },
                    page_size=10,
                )
                for record in std_result.get("items", []):
                    existing_title = record.get("fields", {}).get("法律法规及标准名称", "")
                    existing_num, existing_year = _extract_standard_identifier(existing_title)
                    if existing_num == std_num:
                        if std_year and existing_year and std_year != existing_year:
                            logger.info(
                                "L2 标准号匹配 → update: new=%s(%s) old=%s(%s)",
                                title[:80], std_year, existing_title[:80], existing_year,
                            )
                            return ("update", record)
                        else:
                            logger.info(
                                "L2 标准号匹配 → duplicate: new=%s old=%s",
                                title[:80], existing_title[:80],
                            )
                            return ("duplicate", record)

            # 文号匹配（国务院令、部委令等）
            doc_num = _extract_document_number(title)
            if doc_num:
                doc_result = await bitable.search_records(
                    filter_info={
                        "conjunction": "and",
                        "conditions": [
                            {"field_name": "法律法规及标准名称", "operator": "contains", "value": [doc_num]},
                        ],
                    },
                    page_size=10,
                )
                for record in doc_result.get("items", []):
                    existing_title = record.get("fields", {}).get("法律法规及标准名称", "")
                    existing_doc = _extract_document_number(existing_title)
                    if existing_doc == doc_num and existing_title != title:
                        logger.info(
                            "L2 文号匹配 → update: new=%s old=%s",
                            title[:80], existing_title[:80],
                        )
                        return ("update", record)

            # ── L3: 归一化标题模糊匹配（全量扫描） ──
            norm = _normalize_title(title)
            if len(norm) >= 4:
                all_records = await bitable.list_all_records(page_size=500)
                for record in all_records:
                    fields = record.get("fields", {})
                    existing_title = fields.get("法律法规及标准名称", "")
                    if not existing_title or existing_title == title:
                        continue
                    existing_norm = _normalize_title(existing_title)
                    if len(existing_norm) < 4:
                        continue
                    # 子串匹配 OR bigram 相似度 ≥ 0.5
                    is_substr = norm == existing_norm or norm in existing_norm or existing_norm in norm
                    sim = _bigram_similarity(norm, existing_norm) if not is_substr else 1.0
                    if is_substr or sim >= 0.5:
                        # 进一步判断：日期更新 → update，否则 → duplicate
                        new_date = item.publish_date or ""
                        old_date = _extract_date_from_record(record)
                        match_type = "substr" if is_substr else f"bigram({sim:.2f})"
                        if new_date and old_date and new_date > old_date:
                            logger.info(
                                "L3 归一化匹配(%s) → update: new=%s(%s) old=%s(%s)",
                                match_type, title[:80], new_date, existing_title[:80], old_date,
                            )
                            return ("update", record)
                        logger.info(
                            "L3 归一化匹配(%s) → duplicate: new=%s old=%s",
                            match_type, title[:80], existing_title[:80],
                        )
                        return ("duplicate", record)

            # 三层均未匹配 → 新法规，正常写入
            return ("new", None)

        except Exception:
            logger.exception("去重分类失败: title=%s", title)
            # API 异常时保守处理：标记为 error 跳过写入，避免产生重复记录
            # 宁可漏抓一次（下个周期重试）也不产生重复数据
            return ("error", None)

    async def _handle_update(
        self, bitable: SafetyBitableClient, old_record: dict[str, Any], item: CrawledRegulation,
    ) -> bool:
        """删除 Bitable 中的旧版记录（新版本将随后创建）。

        返回 True 表示删除成功，False 表示删除失败（但不会阻塞新记录写入）。
        """
        old_record_id = old_record.get("record_id", "")
        old_title = old_record.get("fields", {}).get("法律法规及标准名称", "")
        if not old_record_id:
            logger.warning("旧记录无 record_id，无法删除: %s", old_title)
            return False

        try:
            deleted = await bitable.delete_record(old_record_id)
            if deleted:
                logger.info(
                    "旧版法规已删除: record_id=%s title=%s → 将被 %s 替代",
                    old_record_id, old_title[:80], (item.title or "")[:80],
                )
                return True
            else:
                logger.error("删除旧记录失败: record_id=%s title=%s", old_record_id, old_title[:80])
                return False
        except Exception:
            logger.exception("删除旧记录异常: record_id=%s", old_record_id)
            return False

    # ── 日期转换 ──

    @staticmethod
    def _parse_date_millis(date_str: str) -> int | None:
        """将日期字符串（YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS）转为 Bitable 毫秒时间戳。"""
        if not date_str:
            return None
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y年%m月%d日"):
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
                return int(dt.replace(tzinfo=UTC).timestamp() * 1000)
            except ValueError:
                continue
        return None

    # ── 值规范化 ──

    @staticmethod
    def _normalize_status(status: str) -> str:
        """规范化时效状态为 Bitable 选择字段接受的格式。

        注意：「已废止」不会到达此方法——在 write_regulation() 中已被拦截并触发删除。
        """
        status_clean = status.strip()
        if "现行有效" in status_clean or "有效" in status_clean:
            return "现行有效"
        if "即将实施" in status_clean or "尚未施行" in status_clean or "未生效" in status_clean:
            return "即将实施"
        if "征求意见" in status_clean or "草案" in status_clean:
            return "征求意见中"
        return "现行有效"


# ── 标题归一化（模块级工具函数） ──

# 用于清除 HTML 标签（gov.cn 标题含 <em>keyword</em>）
_HTML_TAG_RE = re.compile(r"<[^>]+>")
# 用于清除的标点/空格/特殊字符
_NORMALIZE_RE = re.compile(r"[〔〕【】《》「」『』"r"''（）\(\)\[\]{}（）\s]+")
# 用于清除括号内年份/版本/标准号信息
# 匹配 (2025)、（C 0210-2021）、（GB 18466-2005）、（AQ/T 3033—2022）等
_PAREN_NUMBER_RE = re.compile(r"[（(][^）)]*\d+[^）)]*[）)]")
# 用于剥离标题末尾的日期后缀（如 "安全生产法2024-07-15"）
_TRAILING_DATE_RE = re.compile(r"[\s-]*\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?[\s-]*$")


def _bigram_similarity(a: str, b: str) -> float:
    """计算两个归一化字符串的 bigram Jaccard 相似度（0.0~1.0）。

    用于 L3 去重时识别「特种作业操作证电子证照标准」和
    「全国一体化政务服务平台电子证照特种作业操作证」这类共享核心关键词
    但无法通过子串匹配识别的语义重复。
    """
    if not a or not b:
        return 0.0
    if len(a) < 3 or len(b) < 3:
        return 1.0 if a == b else 0.0
    bigrams_a = {a[i:i+2] for i in range(len(a) - 1)}
    bigrams_b = {b[i:i+2] for i in range(len(b) - 1)}
    intersection = bigrams_a & bigrams_b
    union = bigrams_a | bigrams_b
    if not union:
        return 0.0
    return len(intersection) / len(union)


def _normalize_title(title: str | list | None) -> str:
    """归一化标题以进行模糊比较。

    处理步骤：
    1. 去除 HTML 标签（<em>、<br/> 等）
    2. 去除括号内的年份（如 "(2025)"）
    3. 去除所有标点、空格
    4. 统一小写（处理英文标准号如 GB/T → gb/t）

    兼容 Bitable 字段可能返回富文本格式 [{"text":"...","type":"text"}] 的情况。
    """
    title = _extract_plain_text(title)
    if not title:
        return ""
    t = _HTML_TAG_RE.sub("", str(title))        # 先去 HTML 标签
    t = _PAREN_NUMBER_RE.sub("", t)             # 再去括号标准号/年份
    t = _TRAILING_DATE_RE.sub("", t)            # 再去末尾日期后缀
    t = _NORMALIZE_RE.sub("", t)               # 再去标点空格
    return t.lower().strip()


def _extract_plain_text(value: str | list | dict | None) -> str:
    """从 Bitable 字段值中提取纯文本字符串。

    Bitable 文本字段可能返回多种格式：
    - 纯字符串: "中华人民共和国药品管理法"
    - 富文本数组: [{"text": "中华人民共和国药品管理法", "type": "text"}]
    - 嵌套: [[{"text": "...", "type": "text"}]]
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return str(first.get("text", first))
        if isinstance(first, str):
            return first
        if isinstance(first, list) and first:
            # 嵌套列表 [[{...}]]
            inner = first[0]
            if isinstance(inner, dict):
                return str(inner.get("text", inner))
            return str(inner)
        return str(first)
    if isinstance(value, dict):
        return str(value.get("text", value))
    return str(value)


# ═══════════════════════════════════════════════════════════════
# 标准号 / 文号提取（模块级工具函数）
# ═══════════════════════════════════════════════════════════════

# 标准号模式：GB/T 12345-2020, GB 12345-2025, TSG Z0001-2020, HJ 1234-2020 等
_STANDARD_NUM_RE = re.compile(
    r'(GB[ /T]{0,3}\s*\d{4,7})'           # GB, GB/T, GB/T 等
    r'|(TSG\s*[A-Z]?\d{4,6})'             # TSG 特种设备规范
    r'|(AQ\s*\d{4,7})'                     # AQ 安全生产
    r'|(HJ\s*\d{4,7})'                     # HJ 环境保护
    r'|(YY\s*\d{4,7})'                     # YY 医药
    r'|(JB\s*\d{4,7})'                     # JB 机械
    r'|(HG\s*\d{4,7})'                     # HG 化工
    r'|(SH\s*\d{4,7})'                     # SH 石油化工
    r'|(SY\s*\d{4,7})'                     # SY 石油天然气
    r'|(DB\d{2}[ /T]{0,3}\s*\d{4,7})'     # DB 地方标准
    r'|([A-Z]{2,5}[ /T]{0,3}\s*\d{4,7})'  # 其他行业标准（大写字母+空格+数字）
)

# 年份后缀模式：标准号后面的 -YYYY
_STANDARD_YEAR_RE = re.compile(r'[ -](\d{4})(?:年|版)?')

# 文号模式：国务院令第X号、XX部令第X号、XX公告第X号 等
_DOC_NUM_RE = re.compile(
    r'(国务院令\s*第\d+号)'
    r'|(.{2,8}[部委局署院办]令\s*第\d+号)'
    r'|(.{2,8}[部委局署院办]公告\s*\d{4}年第\d+号)'
    r'|(.{2,8}[部委局署院办]公告\s*\d{4}年第\d+号)'
)


def _extract_standard_identifier(title: str | list | dict | None) -> tuple[str, str]:
    """从标题中提取标准号和年份。返回 (standard_number, year)。

    例如:
      "GB/T 12345-2020 压力容器..." → ("GB/T 12345", "2020")
      "TSG Z0001-2019 特种设备..." → ("TSG Z0001", "2019")
      "安全生产法" → ("", "")
    """
    plain = _extract_plain_text(title)
    if not plain:
        return ("", "")
    t = _HTML_TAG_RE.sub("", plain)
    m = _STANDARD_NUM_RE.search(t)
    if not m:
        return ("", "")
    std_num = m.group(0).strip()
    # 在标准号后面找年份
    rest = t[m.end():]
    ym = _STANDARD_YEAR_RE.search(rest)
    year = ym.group(1) if ym else ""
    return (std_num, year)


def _extract_document_number(title: str | None) -> str:
    """从标题中提取文号（国务院令/部委令）。返回文号字符串或空串。

    例如:
      "国务院令第123号" → "国务院令第123号"
      "应急管理部令第5号" → "应急管理部令第5号"
    """
    plain = _extract_plain_text(title)
    if not plain:
        return ""
    t = _HTML_TAG_RE.sub("", plain)
    m = _DOC_NUM_RE.search(t)
    return m.group(0).strip() if m else ""


def _extract_date_from_record(record: dict[str, Any]) -> str:
    """从 Bitable 记录的「颁布修订日期」字段提取日期字符串 (YYYY-MM-DD)。

    Bitable 日期字段值为毫秒时间戳。
    """
    fields = record.get("fields", {}) or {}
    ts = fields.get("颁布修订日期")
    if isinstance(ts, (int, float)) and ts > 0:
        try:
            dt = datetime.fromtimestamp(ts / 1000, tz=UTC)
            return dt.strftime("%Y-%m-%d")
        except (OSError, ValueError):
            pass
    if isinstance(ts, str):
        try:
            num = int(ts)
            dt = datetime.fromtimestamp(num / 1000, tz=UTC)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, OSError):
            pass
    return ""
