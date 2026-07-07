"""安全模块 — 知识库 Bitable 事件处理器（单向同步：Bitable → 平台）。

监听飞书多维表格「法规标准清单」的 record.created_v1 / record.changed_v1 / record.deleted_v1 事件，
实现 Bitable → SafetyKnowledgeArticle 单向同步。

与隐患模块的关键差异：
- 不触发 AI 识别
- 不发送飞书通知
- 不需要身份解析
- 单附件（法规原件）
- 回写仅 article_no
"""

import json
import logging
import os
from datetime import UTC, date, datetime
from typing import Any

from app.core.redis import redis_client
from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.feishu.event_client import on_event

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 表格标识
# ═══════════════════════════════════════════════════════════════

_KNOWLEDGE_APP_TOKEN = os.getenv("SAFETY_FEISHU_BITABLE_KNOWLEDGE_APP_TOKEN", "")
_KNOWLEDGE_TABLE_ID = os.getenv("SAFETY_FEISHU_BITABLE_KNOWLEDGE_TABLE_ID", "")

# ═══════════════════════════════════════════════════════════════
# 字段映射：Bitable 中文字段名 → SafetyKnowledgeArticle 英文字段名
# ═══════════════════════════════════════════════════════════════

KNOWLEDGE_BITABLE_TO_MODEL: dict[str, str] = {
    "法律法规及标准名称": "title",
    "法规类别":            "category",
    "颁布机关":            "source",
    "颁布修订日期":         "publish_date",
    "实施日期":            "implementation_date",
    "法规状态":            "status",
    "核心要点总结":         "summary",
    "备注":               "notes",
}

# 法规类别 → platform category
CATEGORY_CN_TO_EN: dict[str, str] = {
    "安全类":       "laws_regulations",
    "建筑防火与消防": "laws_regulations",
    "特种设备":      "standards",
    "特殊作业":      "standards",
    "职业健康":      "laws_regulations",
    "环境类":        "laws_regulations",
    "化学品管理":    "laws_regulations",
    "其他相关法规":   "other",
    # 脏数据（照原样映射，不做容错）
    "二职业健康类":   "laws_regulations",
    "三环境保护类":   "laws_regulations",
}

# 法规状态 → platform status
STATUS_CN_TO_EN: dict[str, str] = {
    "现行有效":    "published",
    "现行有效(新)": "published",
    "征求意见中":   "draft",
    "即将实施":    "published",
}

# 类别 → 编号前缀映射
CATEGORY_PREFIX_MAP: dict[str, str] = {
    "laws_regulations": "LAW",
    "standards": "STD",
    "management_systems": "MGT",
    "accident_cases": "CASE",
    "emergency_plans": "ERP",
    "sds": "SDS",
    "training_materials": "TRN",
    "other": "GEN",
}

# 飞书知识库文档上传目录
UPLOAD_DIR = os.path.join("uploads", "safety", "knowledge")


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _ms_to_date(value: Any) -> date | None:
    """Bitable DateTime 值为毫秒时间戳，转为 date。"""
    if isinstance(value, (int, float)) and value > 0:
        try:
            return datetime.fromtimestamp(value / 1000, tz=UTC).date()
        except (OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            return datetime.fromtimestamp(int(value) / 1000, tz=UTC).date()
        except (ValueError, OSError):
            pass
    return None


def _extract_select_value(value: Any) -> str:
    """从 Bitable select/multi_select 字段提取值。"""
    if isinstance(value, str):
        return value
    if isinstance(value, list) and len(value) > 0:
        if isinstance(value[0], dict):
            return value[0].get("text", "") or value[0].get("name", "")
        return str(value[0])
    if isinstance(value, dict):
        return value.get("text", "") or value.get("name", "") or ""
    return ""


def _extract_attachment_list(value: Any) -> list[dict]:
    """从 Bitable attachment 字段提取附件列表。"""
    if isinstance(value, list):
        return [a for a in value if isinstance(a, dict) and a.get("file_token")]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [a for a in parsed if isinstance(a, dict) and a.get("file_token")]
        except (json.JSONDecodeError, TypeError):
            pass
    return []


def _map_knowledge_fields(bitable_fields: dict[str, Any]) -> dict[str, Any]:
    """Bitable 中文字段 → SafetyKnowledgeArticle 模型 dict。"""
    result: dict[str, Any] = {}

    for cn_name, en_name in KNOWLEDGE_BITABLE_TO_MODEL.items():
        raw = bitable_fields.get(cn_name)
        if raw is None or raw == "" or raw == []:
            continue

        if cn_name == "法规类别":
            val = _extract_select_value(raw)
            if val:
                result[en_name] = CATEGORY_CN_TO_EN.get(val, "other")
        elif cn_name == "法规状态":
            val = _extract_select_value(raw)
            if val:
                result[en_name] = STATUS_CN_TO_EN.get(val, "draft")
        elif cn_name in ("颁布修订日期", "实施日期"):
            d = _ms_to_date(raw)
            if d:
                result[en_name] = d
        else:
            # 文本字段直接取值
            val = raw if isinstance(raw, str) else str(raw)
            if val.strip():
                result[en_name] = val.strip()

    return result


# ═══════════════════════════════════════════════════════════════
# Redis 辅助
# ═══════════════════════════════════════════════════════════════

async def _is_duplicate(event_type: str, record_id: str, suffix: str = "") -> bool:
    """Redis 去重。返回 True 表示重复事件。"""
    key = f"bitable:knowledge:event:{record_id}:{event_type}"
    if suffix:
        key = f"{key}:{suffix}"
    try:
        return not await redis_client.set(key, "1", ex=60, nx=True)
    except Exception:
        return False


async def _set_sync_ignore(record_id: str, ttl: int = 60) -> None:
    """标记 record 为「平台发起」，让后续 changed 事件跳过。"""
    key = f"bitable:knowledge:ignore:{record_id}"
    try:
        await redis_client.set(key, "1", ex=ttl)
    except Exception:
        pass


async def _is_sync_ignored(record_id: str) -> bool:
    """检查是否应跳过此次 changed 事件。"""
    key = f"bitable:knowledge:ignore:{record_id}"
    try:
        return await redis_client.exists(key) > 0
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════
# 表格匹配
# ═══════════════════════════════════════════════════════════════

def _match_knowledge_target(file_token: str, table_id: str) -> bool:
    """检查事件是否属于知识库 Bitable 表格。"""
    if not _KNOWLEDGE_APP_TOKEN or not _KNOWLEDGE_TABLE_ID:
        return False
    if file_token and file_token != _KNOWLEDGE_APP_TOKEN:
        return False
    if table_id and table_id != _KNOWLEDGE_TABLE_ID:
        return False
    return True


# ═══════════════════════════════════════════════════════════════
# 附件下载
# ═══════════════════════════════════════════════════════════════

async def _download_knowledge_attachment(
    bitable: SafetyBitableClient,
    bitable_fields: dict[str, Any],
    record_id: str,
) -> tuple[str | None, str | None]:
    """下载法规原件到本地。返回 (file_path, original_name)。"""
    field_cn = "法规原件"
    raw = bitable_fields.get(field_cn)
    attachments = _extract_attachment_list(raw)

    # 如果事件数据没有附件，尝试 API 拉取
    if not attachments:
        try:
            api_fields = await bitable.get_record(record_id)
            if api_fields:
                raw = api_fields.get(field_cn, [])
                attachments = _extract_attachment_list(raw)
        except Exception:
            logger.exception("API 拉取附件失败: record_id=%s", record_id)

    if not attachments:
        return None, None

    # 只取第一个附件
    att = attachments[0]
    file_token = att.get("file_token", "")
    file_name = att.get("name", "document")
    download_url = att.get("url", "") or att.get("tmp_url", "")

    logger.info("下载知识库附件: record_id=%s file_token=%s name=%s", record_id, file_token, file_name)

    os.makedirs(UPLOAD_DIR, exist_ok=True)

    # 生成本地文件名
    safe_name = file_name.replace("/", "_").replace("\\", "_")
    local_path = os.path.join(
        UPLOAD_DIR,
        f"knowledge_sync_{record_id[:20]}_{file_token[:20]}_{safe_name}",
    )

    data: bytes | None = None

    # 策略1: 预签名 URL
    if download_url:
        try:
            data = await bitable.download_attachment_from_url(download_url)
        except Exception:
            logger.exception("预签名 URL 下载失败: file_token=%s", file_token)

    # 策略2: Drive API 回退
    if not data and file_token:
        try:
            data = await bitable.download_attachment(file_token)
        except Exception:
            logger.exception("Drive API 下载失败: file_token=%s", file_token)

    if data:
        with open(local_path, "wb") as f:
            f.write(data)
        logger.info("附件下载成功: record_id=%s path=%s size=%d", record_id, local_path, len(data))
        return local_path, file_name

    logger.warning("附件下载失败，跳过: record_id=%s file_token=%s", record_id, file_token)
    return None, None


# ═══════════════════════════════════════════════════════════════
# 编号生成
# ═══════════════════════════════════════════════════════════════

async def _generate_article_no(session: Any, category: str) -> str:
    """生成文档编号：{PREFIX}-{YYYYMMDD}-{3位序号}。"""
    from sqlalchemy import func, select

    from app.modules.safety.models import SafetyKnowledgeArticle

    prefix = CATEGORY_PREFIX_MAP.get(category, "GEN")
    today = date.today().strftime("%Y%m%d")
    pattern = f"{prefix}-{today}-%"

    stmt = select(func.max(SafetyKnowledgeArticle.article_no)).where(
        SafetyKnowledgeArticle.article_no.ilike(pattern),
    )
    result = await session.execute(stmt)
    max_no = result.scalar()

    if max_no and max_no.startswith(f"{prefix}-{today}-"):
        try:
            seq = int(max_no.rsplit("-", 1)[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1

    return f"{prefix}-{today}-{seq:03d}"


# ═══════════════════════════════════════════════════════════════
# 核心同步逻辑
# ═══════════════════════════════════════════════════════════════

async def _get_article_by_feishu_id(
    session: Any, feishu_record_id: str
) -> Any | None:
    """根据 feishu_record_id 查找 SafetyKnowledgeArticle（含已删除）。"""
    from sqlalchemy import select

    from app.modules.safety.models import SafetyKnowledgeArticle

    stmt = select(SafetyKnowledgeArticle).where(
        SafetyKnowledgeArticle.feishu_record_id == feishu_record_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


def _build_attachment_extra(
    table_id: str, record_id: str, field_id: str, file_token: str,
) -> str:
    """构建 Drive API 下载附件所需的 extra 参数。"""
    extra = {
        "bitablePerm": {
            "tableId": table_id,
            "attachments": {
                field_id: {record_id: [file_token]},
            },
        }
    }
    return json.dumps(extra, ensure_ascii=False)


async def _get_field_name_map(bitable: SafetyBitableClient) -> dict[str, str]:
    """获取 field_id → field_name 映射。"""
    try:
        fields = await bitable.list_fields()
        return {f.get("field_id", ""): f.get("field_name", "") for f in fields}
    except Exception:
        logger.exception("获取字段映射失败")
        return {}


async def _create_knowledge_from_bitable(
    bitable: SafetyBitableClient,
    record_id: str,
    bitable_fields: dict[str, Any],
) -> Any | None:
    """从 Bitable 记录创建 SafetyKnowledgeArticle + 回写 article_no。"""
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.modules.safety.models import SafetyKnowledgeArticle

    # 0. INSERT 互斥锁
    lock_key = f"bitable:knowledge:lock:insert:{record_id}"
    try:
        if not await redis_client.set(lock_key, "1", ex=120, nx=True):
            logger.warning("INSERT 互斥锁已存在，跳过: record_id=%s", record_id)
            return None
    except Exception:
        pass

    # 1. 幂等检查
    session = async_session_factory()
    try:
        existing = await _get_article_by_feishu_id(session, record_id)
        if existing and not existing.is_deleted:
            logger.info("record_id=%s 已关联 article_id=%s，跳过创建", record_id, existing.id)
            return None
    finally:
        await session.close()

    # 2. 拉取全量字段（确保获取完整数据）
    try:
        api_fields = await bitable.get_record(record_id)
    except Exception:
        logger.exception("API 拉取失败，使用事件字段: record_id=%s", record_id)
        api_fields = bitable_fields

    fields = {**bitable_fields, **api_fields} if api_fields else bitable_fields

    # 3. 字段映射
    mapped = _map_knowledge_fields(fields)

    # 4. 标题必填检查
    if not mapped.get("title"):
        logger.error("知识库记录标题为空，跳过创建: record_id=%s", record_id)
        return None

    # 5. 创建记录
    session = async_session_factory()
    try:
        # 生成编号
        category = mapped.get("category", "other")
        article_no = await _generate_article_no(session, category)

        # 下载附件
        file_path, file_name = await _download_knowledge_attachment(
            bitable, fields, record_id,
        )

        # 构建模型数据
        article_data = {
            **mapped,
            "feishu_record_id": record_id,
            "article_no": article_no,
            "attachment_path": file_path,
            "attachment_original_name": file_name,
            "status": mapped.get("status", "published"),
        }

        article = SafetyKnowledgeArticle(**article_data)
        session.add(article)
        await session.flush()

        # Re-fetch
        stmt = select(SafetyKnowledgeArticle).where(
            SafetyKnowledgeArticle.id == article.id,
        )
        result = await session.execute(stmt)
        article = result.scalar_one()
        await session.commit()

        logger.info(
            "知识库文章创建成功: id=%s article_no=%s title=%s record_id=%s",
            article.id, article_no, mapped.get("title"), record_id,
        )

        # 6. 回写 article_no 到 Bitable
        try:
            await bitable.update_record(record_id, {"article_no": article_no})
            await _set_sync_ignore(record_id)
            logger.info("article_no 已回写: record_id=%s article_no=%s", record_id, article_no)
        except Exception:
            logger.exception("回写 article_no 失败: record_id=%s", record_id)

        return article

    except Exception:
        logger.exception("创建知识库文章失败: record_id=%s", record_id)
        await session.rollback()
        return None
    finally:
        await session.close()


async def _update_knowledge_from_bitable(
    bitable: SafetyBitableClient,
    record_id: str,
    bitable_fields: dict[str, Any],
) -> Any | None:
    """更新已关联的知识库文章。"""
    from sqlalchemy import update

    from app.core.database import async_session_factory
    from app.modules.safety.models import SafetyKnowledgeArticle

    session = async_session_factory()
    try:
        existing = await _get_article_by_feishu_id(session, record_id)
        if not existing:
            logger.info("未找到关联文章，降级为创建: record_id=%s", record_id)
            await session.close()
            return await _create_knowledge_from_bitable(bitable, record_id, bitable_fields)

        if existing.is_deleted:
            logger.info("关联文章已删除，跳过更新: record_id=%s article_id=%s", record_id, existing.id)
            return None

        # 拉取全量字段
        try:
            api_fields = await bitable.get_record(record_id)
        except Exception:
            logger.exception("API 拉取失败: record_id=%s", record_id)
            api_fields = {}

        fields = {**bitable_fields, **api_fields} if api_fields else bitable_fields
        mapped = _map_knowledge_fields(fields)

        # 字段 diff：只更新实际变化的字段
        update_data: dict[str, Any] = {}
        for en_name, new_value in mapped.items():
            old_value = getattr(existing, en_name, None)
            if new_value != old_value:
                update_data[en_name] = new_value

        # 附件变更检测
        old_attachment = existing.attachment_path
        new_path, new_name = await _download_knowledge_attachment(
            bitable, fields, record_id,
        )
        if new_path and new_path != old_attachment:
            # 清理旧附件（仅本地文件）
            if old_attachment and os.path.exists(old_attachment):
                try:
                    os.remove(old_attachment)
                except OSError:
                    pass
            update_data["attachment_path"] = new_path
            update_data["attachment_original_name"] = new_name
            logger.info("附件已更新: record_id=%s old=%s new=%s", record_id, old_attachment, new_path)

        if not update_data:
            logger.info("字段无变化，跳过更新: record_id=%s article_id=%s", record_id, existing.id)
            return existing

        # 执行更新
        from sqlalchemy import func as sqlfunc

        stmt = (
            update(SafetyKnowledgeArticle)
            .where(
                SafetyKnowledgeArticle.id == existing.id,
                SafetyKnowledgeArticle.is_deleted == False,  # noqa: E712
            )
            .values(**update_data, updated_at=sqlfunc.now())
            .returning(SafetyKnowledgeArticle)
        )
        result = await session.execute(stmt)
        await session.commit()

        updated = result.scalar_one_or_none()
        logger.info(
            "知识库文章更新成功: article_id=%s fields=%s", existing.id, list(update_data.keys()),
        )
        return updated

    except Exception:
        logger.exception("更新知识库文章失败: record_id=%s", record_id)
        await session.rollback()
        return None
    finally:
        await session.close()


async def _delete_knowledge_from_bitable(record_id: str) -> None:
    """软删除知识库文章。"""
    from sqlalchemy import update

    from app.core.database import async_session_factory
    from app.modules.safety.models import SafetyKnowledgeArticle

    session = async_session_factory()
    try:
        existing = await _get_article_by_feishu_id(session, record_id)
        if not existing:
            logger.warning("未找到关联文章，无法删除: record_id=%s", record_id)
            return

        if existing.is_deleted:
            logger.info("文章已删除，跳过: record_id=%s", record_id)
            return

        stmt = (
            update(SafetyKnowledgeArticle)
            .where(
                SafetyKnowledgeArticle.id == existing.id,
                SafetyKnowledgeArticle.is_deleted == False,  # noqa: E712
            )
            .values(is_deleted=True)
        )
        await session.execute(stmt)
        await session.commit()

        logger.info("知识库文章已软删除: id=%s article_no=%s record_id=%s",
                    existing.id, existing.article_no, record_id)

    except Exception:
        logger.exception("删除知识库文章失败: record_id=%s", record_id)
        await session.rollback()
    finally:
        await session.close()


# ═══════════════════════════════════════════════════════════════
# 图谱自动更新
# ═══════════════════════════════════════════════════════════════

_GRAPH_REBUILD_LOCK_KEY = "bitable:knowledge:graph_rebuild_lock"
_GRAPH_REBUILD_DEBOUNCE_SEC = 60  # 1 分钟内多个文档变更合并为一次重建


async def _schedule_graph_rebuild() -> None:
    """文档变更后延迟触发图谱增量重建（Redis 去重防抖）。

    多次快速变更时只触发一次重建，等待 {debounce} 秒让变更趋于稳定。
    """
    try:
        acquired = await redis_client.set(
            _GRAPH_REBUILD_LOCK_KEY, "1", ex=_GRAPH_REBUILD_DEBOUNCE_SEC, nx=True,
        )
        if not acquired:
            logger.debug("图谱重建已在调度中，跳过")
            return

        import asyncio

        async def _rebuild():
            await asyncio.sleep(15)  # 等待批量变更稳定
            try:
                from app.core.database import async_session_factory
                from app.modules.safety.knowledge.graph_builder import GraphBuilder

                session = async_session_factory()
                try:
                    builder = GraphBuilder(session)
                    result = await builder.build_full_graph()
                    await session.commit()
                    logger.info(
                        "图谱自动重建完成: nodes_created=%d edges_created=%d errors=%d",
                        result["nodes_created"],
                        result["edges_created"],
                        len(result["errors"]),
                    )
                    if result["errors"]:
                        for err in result["errors"][:3]:
                            logger.warning("图谱重建错误: %s", err)
                except Exception:
                    logger.exception("图谱自动重建失败")
                finally:
                    await session.close()
            except Exception:
                logger.exception("图谱自动重建调度失败")

        asyncio.create_task(_rebuild())
    except Exception:
        logger.exception("图谱重建调度异常")


# ═══════════════════════════════════════════════════════════════
# 事件处理器（@on_event 注册）
# ═══════════════════════════════════════════════════════════════

async def _handle_single_knowledge_record_action(
    bitable: SafetyBitableClient,
    record_id: str,
    action: str,
    event_fields: dict[str, Any],
) -> None:
    """处理单条知识库记录变更。"""
    if action == "delete":
        # 去重
        if await _is_duplicate("delete", record_id):
            return
        await _delete_knowledge_from_bitable(record_id)
        # 文档删除后触发图谱更新
        await _schedule_graph_rebuild()
        return

    if action == "insert":
        if await _is_duplicate("insert", record_id):
            logger.info("重复插入事件已忽略: record_id=%s", record_id)
            return
        result = await _create_knowledge_from_bitable(bitable, record_id, event_fields)
        # 文档创建成功后触发图谱更新
        if result is not None:
            await _schedule_graph_rebuild()
        return

    if action == "update":
        # 去重：按字段名区分
        field_suffix = ",".join(sorted(event_fields.keys())) if event_fields else ""
        if await _is_duplicate("update", record_id, suffix=field_suffix):
            logger.info("重复更新事件已忽略: record_id=%s", record_id)
            return

        # sync_ignore 检查
        if await _is_sync_ignored(record_id):
            logger.info("平台回写触发的更新事件，已忽略: record_id=%s", record_id)
            return

        result = await _update_knowledge_from_bitable(bitable, record_id, event_fields)
        # 文档更新成功后触发图谱更新
        if result is not None:
            await _schedule_graph_rebuild()
        return


@on_event("drive.file.bitable_record_changed_v1")
async def handle_knowledge_record_changed(event_data: dict[str, Any]) -> None:
    """知识库表格的 record 变更事件。"""
    file_token = event_data.get("file_token", "")
    table_id = event_data.get("table_id", "")

    if not _match_knowledge_target(file_token, table_id):
        return  # 不是知识库表格事件，交给其他处理器

    logger.info("知识库 Bitable record 变更事件: file_token=%s table_id=%s", file_token, table_id)

    # 构建 Bitable client（使用知识库表格的 app_token 和 table_id）
    bitable = SafetyBitableClient(
        app_token=_KNOWLEDGE_APP_TOKEN,
        table_id=_KNOWLEDGE_TABLE_ID,
    )

    # 处理 action_list（新版事件格式）
    action_list = event_data.get("action_list", [])
    if action_list:
        for item in action_list:
            record_id = item.get("record_id", "")
            action = item.get("action", "")
            fields = item.get("fields", {})
            if not record_id:
                continue
            try:
                await _handle_single_knowledge_record_action(
                    bitable, record_id, action, fields,
                )
            except Exception:
                logger.exception(
                    "知识库 record 事件处理异常: record_id=%s action=%s", record_id, action,
                )
    else:
        # 旧格式：顶层 action + record_id
        record_id = event_data.get("record_id", "")
        action = event_data.get("action", "")
        if record_id:
            try:
                await _handle_single_knowledge_record_action(
                    bitable, record_id, action, event_data.get("fields", {}),
                )
            except Exception:
                logger.exception(
                    "知识库 record 事件处理异常: record_id=%s action=%s", record_id, action,
                )


@on_event("drive.file.bitable_field_changed_v1")
async def handle_knowledge_field_changed(event_data: dict[str, Any]) -> None:
    """知识库表格的 field 变更事件 → 委托给 record 处理。"""
    file_token = event_data.get("file_token", "")
    table_id = event_data.get("table_id", "")

    if not _match_knowledge_target(file_token, table_id):
        return

    logger.info("知识库 Bitable field 变更事件: file_token=%s table_id=%s", file_token, table_id)

    bitable = SafetyBitableClient(
        app_token=_KNOWLEDGE_APP_TOKEN,
        table_id=_KNOWLEDGE_TABLE_ID,
    )

    record_id = event_data.get("record_id", "")
    if not record_id:
        return

    # field_changed 事件没有 action 字段 → 视为 update
    try:
        await _handle_single_knowledge_record_action(
            bitable, record_id, "update", event_data.get("fields", {}),
        )
    except Exception:
        logger.exception("知识库 field 事件处理异常: record_id=%s", record_id)


# ═══════════════════════════════════════════════════════════════
# 文档事件订阅
# ═══════════════════════════════════════════════════════════════

async def ensure_knowledge_bitable_subscribed() -> bool:
    """订阅知识库多维表格云文档事件。

    飞书要求：在接收 Bitable 事件之前，必须先调用此 API 订阅文档事件。
    """
    if not _KNOWLEDGE_APP_TOKEN:
        logger.info("知识库 Bitable app_token 未配置，跳过文档事件订阅")
        return False

    try:
        import httpx

        from app.modules.safety.feishu.client import get_safety_tenant_token

        token = await get_safety_tenant_token()
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                f"https://open.feishu.cn/open-apis/drive/v1/files/{_KNOWLEDGE_APP_TOKEN}/subscribe",
                headers={"Authorization": f"Bearer {token}"},
                params={"file_type": "bitable"},
            )
            data = resp.json()
            if data.get("code") == 0:
                logger.info("知识库 Bitable 文档事件订阅成功: file_token=%s", _KNOWLEDGE_APP_TOKEN)
                return True
            logger.error(
                "知识库 Bitable 文档事件订阅失败: code=%s msg=%s",
                data.get("code"), data.get("msg"),
            )
            return False
    except Exception:
        logger.exception("知识库 Bitable 文档事件订阅异常")
        return False
