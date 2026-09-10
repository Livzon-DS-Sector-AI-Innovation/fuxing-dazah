"""外部审计表 — 服务层

提供:
  - import_audit_table(): 读取一张表 → 解析 → upsert 到 HazardReport
  - import_all_audit_tables(): 读取全部 7 张表

不触发 AI 工作流、不发送通知、不回写源表。
"""

import json
import logging
import os
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.core.database import async_session_factory
from app.modules.safety.attachment_store import store_bytes
from app.modules.safety.audit.configs import ALL_AUDIT_TABLES, AUDIT_TABLES_BY_NAME
from app.modules.safety.audit.parser import parse_record
from app.modules.safety.audit.reader import read_table
from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.models import HazardReport

logger = logging.getLogger(__name__)

UTC = UTC

_IMAGE_MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


def _guess_image_content_type(file_name: str) -> str:
    """按扩展名猜图片 Content-Type（未知类型回退 octet-stream）。"""
    ext = os.path.splitext(file_name)[1].lower()
    return _IMAGE_MIME_BY_EXT.get(ext, "application/octet-stream")

# ============================================================
# 公开接口
# ============================================================


async def import_all_audit_tables() -> dict:
    """读取全部 7 张外部审计表并 upsert 到平台。

    Returns:
        {table_name: {"read": N, "created": N, "updated": N, "skipped": N}}
    """
    results = {}
    async with async_session_factory() as session:
        for config in ALL_AUDIT_TABLES:
            name = config["name"]
            try:
                results[name] = await _import_one_table(config, session)
            except Exception:
                logger.exception("导入表失败: %s (%s)", name, config.get("label"))
                results[name] = {"error": str(Exception.__name__)}
                await session.rollback()
            else:
                await session.commit()
    return results


async def import_audit_table(table_name: str) -> dict:
    """读取单张外部审计表并 upsert 到平台。

    Args:
        table_name: 配置中的 name 值

    Returns:
        {"read": N, "created": N, "updated": N, "skipped": N}
    """
    config = AUDIT_TABLES_BY_NAME.get(table_name)
    if config is None:
        raise ValueError(f"未知的审计表: {table_name}")

    async with async_session_factory() as session:
        result = await _import_one_table(config, session)
        await session.commit()
        return result


# ============================================================
# 单表导入
# ============================================================


async def _import_one_table(config: dict, session) -> dict:
    """读取一张表 → 解析 → upsert。"""
    label = config.get("label", config["name"])

    # 1. 读取源表
    raw_records = await read_table(config)
    stats = {"read": len(raw_records), "created": 0, "updated": 0, "skipped": 0}

    # 2. 逐个解析 + upsert
    pushed = 0
    for rec in raw_records:
        record_id = _extract_record_id(config, rec)
        if not record_id:
            stats["skipped"] += 1
            continue

        try:
            hazard_data = parse_record(config, rec)
        except Exception:
            logger.exception("记录解析失败: record_id=%s", record_id)
            stats["skipped"] += 1
            continue

        # 设置 AI 绕过值
        _apply_ai_bypass(hazard_data)

        # 下载附件
        await _download_photos(hazard_data, rec, config)

        # feishu_record_id
        hazard_data["feishu_record_id"] = record_id

        # 补全必填字段（含 supervision_level 同步）
        old_superv = None
        _ensure_required(hazard_data)

        # 构造来源信息（供通报生成正确的来源链接）
        src = config.get("source", {})
        source_info = {
            "type": src.get("type", "bitable"),
            "name": config["name"],
            "inspection_category": config.get("defaults", {}).get("inspection_category", ""),
        }
        if src.get("type") == "bitable":
            source_info["app_token"] = src["app_token"]
            source_info["table_id"] = src["table_id"]
        elif src.get("type") == "sheets":
            source_info["spreadsheet_token"] = src["spreadsheet_token"]

        # upsert
        is_new, old_superv = await _upsert_hazard(session, hazard_data, source_info)
        if is_new:
            stats["created"] += 1
        else:
            stats["updated"] += 1

        # 逐条 flush 避免批量失败
        try:
            await session.flush()
        except Exception:
            logger.exception("flush 失败: record_id=%s", record_id)
            stats["skipped"] += 1
            continue

        # 如果等级变化了，推回源表
        new_superv = hazard_data.get("supervision_level")
        if old_superv is not None and new_superv is not None and old_superv != new_superv:
            pushed += await _push_superv_to_source(config, record_id, new_superv)

    if pushed:
        logger.info("督办等级推回源表: %s → %d 条", label, pushed)

    logger.info(
        "表导入完成: %s → 读取 %d, 新建 %d, 更新 %d, 跳过 %d",
        label,
        stats["read"],
        stats["created"],
        stats["updated"],
        stats["skipped"],
    )
    return stats


# ============================================================
# Record ID 提取
# ============================================================


def _extract_record_id(config: dict, raw_record: dict) -> str:
    """从源记录提取唯一标识。

    Bitable: 使用 record_id
    Sheets:  使用 "spreadsheet_token:row{N}"
    空记录跳过。
    """
    source_type = config["source"]["type"]

    if source_type == "bitable":
        rid = raw_record.get("_record_id", "")
        # 空记录检测
        has_content = any(
            v for k, v in raw_record.items()
            if k != "_record_id" and v is not None
        )
        return rid if (rid and has_content) else ""

    elif source_type == "sheets":
        row = raw_record.get("_row_index", 0)
        # 空行检测
        has_content = any(
            v for k, v in raw_record.items()
            if k != "_row_index" and k != "_record_id" and v is not None
        )
        if not has_content:
            return ""
        token = config["source"]["spreadsheet_token"]
        return f"{token}:row{row}"

    return ""


# ============================================================
# AI 绕过
# ============================================================


def _apply_ai_bypass(hazard_data: dict) -> None:
    """设置 AI 流程绕过值（不触发隐患识别和整改初审）。

    这些固定值确保记录处于"已完成"状态，不会进入 AI 管线。
    """
    hazard_data.setdefault("ai_node_progress", "completed")
    hazard_data.setdefault("overall_status", "completed")
    hazard_data.setdefault("ai_generated", False)
    hazard_data.setdefault("verify_level_1_status", "approved")
    hazard_data.setdefault("verify_level_2_status", "no_review_needed")
    hazard_data.setdefault("verify_level_3_status", "approved")
    hazard_data.setdefault("ai_review_status", "pending")
    hazard_data.setdefault("script1_review_status", "pending")
    hazard_data.setdefault("script2_review_status", "pending")


# ============================================================
# 必填字段兜底
# ============================================================


def _ensure_required(hazard_data: dict) -> None:
    """补全必填字段的兜底值。

    SQLAlchemy 模型上的 nullable=False + server_default 字段:
      - hazardous_level → "general" (DB default)
      - status → "open" (DB default)
      - rectification_status → "pending" (DB default)
      - verify_level_1/2/3 → "pending" (DB default, 已被 _apply_ai_bypass 覆盖)
      - ai_node_progress → "pending_input" (DB default, 已被 _apply_ai_bypass 覆盖)
      - overall_status → "draft" (DB default, 已被 _apply_ai_bypass 覆盖)
      - ai_review_status → "pending" (DB default)
      - ai_generated → false (DB default)

    无 server_default 但 nullable=False:
      - hazard_no → 调用方生成
      - hazard_type → defaults 已给 "unsafe_condition"
      - description → defaults 已给 ""
      - discovered_at → nullable=False 但无 default → 兜底用当前时间
    """
    # discovered_at 是 nullable=False 且无 server_default，必须给值
    if hazard_data.get("discovered_at") is None:
        hazard_data["discovered_at"] = datetime.now(UTC)

    # status 跟随 rectification_status
    rect_status = hazard_data.get("rectification_status", "pending")
    if rect_status == "closed":
        hazard_data["status"] = "closed"
        hazard_data.setdefault("supervision_level", "closed")
    else:
        hazard_data.setdefault("status", "open")

    # hazard_no 必须由调用方生成（_upsert_hazard 中处理）
    hazard_data.setdefault("hazard_type", "unsafe_condition")
    hazard_data.setdefault("hazard_level", "general")
    hazard_data.setdefault("description", "")


# ============================================================
# Upsert
# ============================================================


async def _upsert_hazard(session, hazard_data: dict, source_info: dict | None = None) -> tuple[bool, str | None]:
    """按 feishu_record_id 去重 upsert。

    Args:
        source_info: 可选，外部审计来源信息 {"type": "bitable"/"sheets", "app_token": ..., "table_id": ...}
                    存储到 notes 字段，供通报生成正确的来源链接。

    Returns:
        (is_new, old_supervision_level): 是否新建 + 更新前的 supervision_level
    """
    feishu_id = hazard_data.get("feishu_record_id")
    if not feishu_id:
        return False, None

    # 合并来源信息到 notes
    if source_info:
        existing_notes = hazard_data.get("notes") or ""
        try:
            notes_obj = json.loads(existing_notes) if existing_notes else {}
        except (json.JSONDecodeError, TypeError):
            notes_obj = {}
        notes_obj["_audit_source"] = source_info
        hazard_data["notes"] = json.dumps(notes_obj, ensure_ascii=False)

    # 查询已有记录
    result = await session.execute(
        select(HazardReport).where(
            HazardReport.feishu_record_id == feishu_id,
            HazardReport.is_deleted == False,  # noqa: E712
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        old_superv = existing.supervision_level
        _update_existing(existing, hazard_data)
        return False, old_superv
    else:
        hazard_data["id"] = str(uuid.uuid4())
        if not hazard_data.get("hazard_no"):
            hazard_data["hazard_no"] = await _gen_hazard_no(session)
        hazard = HazardReport(**hazard_data)
        session.add(hazard)
        return True, None  # 新建记录，无旧值


def _update_existing(existing: HazardReport, data: dict) -> None:
    """更新已有记录的外部审计字段。

    只更新外部审计可能变化的字段，不覆盖平台内部字段。
    """
    _updatable = [
        "description",
        "department",
        "deadline",
        "actual_completion_date",
        "rectification_reply",
        "rectification_status",
        "status",
        "rectification_photos",
        "rectification_responsible_person_name",
        "supervision_level",
        "hazard_level_manual",
        "discovered_at",
        "discovered_by_name",
        "inspection_category",
        "inspector_department",
    ]
    for field in _updatable:
        if field in data and data[field] is not None:
            setattr(existing, field, data[field])

    # 同步 rectification_status → status + supervision_level
    if "rectification_status" in data:
        rect_status = data["rectification_status"]
        existing.status = "closed" if rect_status == "closed" else "open"
        if rect_status == "closed":
            existing.supervision_level = "closed"


# ============================================================
# hazard_no 生成
# ============================================================


async def _gen_hazard_no(session) -> str:
    """生成 HZ-YYYYMMDD-NNN 格式的隐患编号。

    统计当天所有记录（含软删除），确保唯一性。
    """
    today = datetime.now().strftime("%Y%m%d")
    result = await session.execute(
        select(func.count(HazardReport.id)).where(
            HazardReport.hazard_no.like(f"HZ-{today}-%"),
        ),
    )
    count = result.scalar() or 0
    return f"HZ-{today}-{count + 1:03d}"


# ============================================================
# 附件下载
# ============================================================


async def _download_photos(
    hazard_data: dict,
    raw_record: dict,
    config: dict,
) -> None:
    """下载 rectification_photos 中的附件。

    parser 层已将附件元数据存为 JSON 字符串，这里下载实际文件并替换为路径 JSON。
    """
    photos_json = hazard_data.get("rectification_photos")
    if not photos_json:
        return

    try:
        attachments = json.loads(photos_json)
    except (json.JSONDecodeError, TypeError):
        return

    if not isinstance(attachments, list) or len(attachments) == 0:
        return

    # 使用 SafetyBitableClient 下载
    source_type = config["source"]["type"]
    if source_type != "bitable":
        # Sheets 表无附件功能，跳过
        hazard_data["rectification_photos"] = None
        return

    client = SafetyBitableClient(
        app_token=config["source"]["app_token"],
        table_id=config["source"]["table_id"],
    )

    rid = raw_record.get("_record_id", "unknown")[:16]
    downloaded = []

    for att in attachments:
        if not isinstance(att, dict):
            continue
        file_token = att.get("file_token", "")
        file_name = att.get("name", "unknown")
        tmp_url = att.get("tmp_url", "")
        url = att.get("url", "")

        # 两策略下载
        data = None
        if tmp_url:
            data = await client.download_attachment_from_url(tmp_url)
        if data is None and url:
            data = await client.download_attachment_from_url(url)
        if data is None and file_token:
            data = await client.download_attachment(file_token)

        if data:
            # 安全路径 + store_bytes 入桶（MinIO key / 本地相对路径）
            safe_name = file_name.replace("\\", "/").split("/")[-1]
            stored = store_bytes(
                "hazard",
                f"audit_{rid}_{file_token[:12]}_{safe_name}",
                data,
                content_type=_guess_image_content_type(safe_name),
            )
            downloaded.append(stored)
        else:
            logger.warning("附件下载失败: %s (%s)", file_name, file_token)

    if downloaded:
        hazard_data["rectification_photos"] = json.dumps(downloaded)
    else:
        hazard_data["rectification_photos"] = None


# ============================================================
# 推回源表
# ============================================================

# 督办等级中文标签
SUPERVISION_LEVEL_LABEL = {
    "closed": "已关闭",
    "红色预警": "红色预警",
    "一般预警": "一般预警",
}


async def _push_superv_to_source(
    config: dict,
    record_id: str,
    level: str,
) -> int:
    """将督办等级推回源 Bitable。

    只对 Bitable 源表有效（Sheets 不支持）。

    Returns:
        1 = 成功, 0 = 失败/跳过
    """
    source = config["source"]
    if source["type"] != "bitable":
        return 0  # Sheets 不支持回写

    if not record_id:
        return 0

    label = SUPERVISION_LEVEL_LABEL.get(level, level)

    try:
        client = SafetyBitableClient(
            app_token=source["app_token"],
            table_id=source["table_id"],
        )
        ok = await client.update_record(record_id, {"督办等级": label})
        if ok:
            logger.debug(
                "督办等级推回源表成功: %s record_id=%s level=%s",
                config.get("label"), record_id, label,
            )
            return 1
        else:
            logger.warning(
                "督办等级推回源表失败: %s record_id=%s (字段可能不存在)",
                config.get("label"), record_id,
            )
            return 0
    except Exception:
        logger.exception(
            "督办等级推回源表异常: %s record_id=%s", config.get("label"), record_id,
        )
        return 0


# ============================================================
# 督办计算（保留供直接使用，日常不调用）
# ============================================================


def _compute_supervision(hazard_data: dict) -> str:
    """计算督办等级。

    规则:
      rectification_status = "closed" → "closed"
      deadline 存在且已逾期 → "红色预警"
      其他 → "一般预警"
    """
    if hazard_data.get("rectification_status") == "closed":
        return "closed"

    deadline = hazard_data.get("deadline")
    if deadline is not None:
        if isinstance(deadline, datetime):
            if datetime.now(UTC) > deadline:
                return "红色预警"

    return "一般预警"
