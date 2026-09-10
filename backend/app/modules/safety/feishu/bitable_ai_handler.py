"""安全模块 Bitable「数据表」AI 识别外置接入处理器。

目标表（store 的 hazard/hazard 连接，原 SAFETY_FEISHU_BITABLE_HAZARD_TABLE_ID）
已是一份完整的隐患闭环业务系统。本处理器仅把 AI 识别作为【外置模块】接入，
绝不影响原有业务：

  - create 事件：收录隐患 → AI 隐患识别 → 回写「隐患编号 + AI 识别结果」
  - update 事件（整改回复变更）：AI 整改初审 → 回写「AI初审结果 + AI初审说明」

铁律（不允许影响原有业务）：
  1. 本处理器自身不调用任何飞书通知（AI 外置流程零通知）
  2. 不参与三级复核 / 整改状态机
  3. 除 AI 字段 + 隐患编号外，不改写多维表格任何其他字段
     （不回写责任人、整改期限、整改状态、复核字段）
  4. 仅处理目标「数据表」事件（旧表已停用，防止串表）

复用 bitable_handler 的无副作用纯组件（字段映射、附件下载、去重、身份查询、
选项格式化、AI 生成方法），编排逻辑自成一体。
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.core.database import async_session_factory
from app.core.redis import redis_client
from app.modules.safety.feishu import bitable_handler as bh
from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.feishu.event_client import on_event
from app.modules.safety.vision.utils import merge_photos_json

logger = logging.getLogger(__name__)

# 目标「数据表」ID —— 与 bitable_handler 共用 store（hazard/hazard 连接），
# 函数内延迟读取，改表 ID 后新事件立即进新表（§5.2 R1）。

# AI 整改初审结论 → 目标表「AI初审结果」单选项（表中仅有：已通过/未通过/无需整改）
_REVIEW_CONCLUSION_TO_BITABLE = {
    "通过": "已通过",
    "无需整改": "无需整改",
    # 「不通过」及任何未知结论 → 「未通过」（表中无「已驳回」选项）
}


# ═══════════════════════════════════════════════════════════════
# 事件入口
# ═══════════════════════════════════════════════════════════════

@on_event("drive.file.bitable_record_changed_v1")
async def handle_ai_bitable_record_changed(event: dict) -> None:
    """目标「数据表」记录变更 → AI 识别外置接入（唯一注册的记录变更处理器）。"""
    file_token = event.get("file_token", "")
    table_id = event.get("table_id", "")

    # 旧路径总开关（2026-09-09 改造：AI 识别/初审改由 hazard_direct 轮询负责）
    from app.modules.safety.service.hazard_direct.config import event_sync_enabled

    if not event_sync_enabled():
        logger.debug("AI接入: 事件同步已关闭，忽略事件 table_id=%s", table_id)
        return

    if not bh._match_target(file_token, table_id):
        logger.debug(
            "AI接入: 忽略非目标表事件 file_token=%s table_id=%s", file_token, table_id,
        )
        return

    bitable = SafetyBitableClient()
    action_list = event.get("action_list", [])

    if action_list:
        logger.info(
            "AI接入: 收到事件(action_list) table_id=%s items=%d", table_id, len(action_list),
        )
        await bh._get_field_definitions(bitable)
        field_map = bh._field_name_cache or {}
        for item in action_list:
            record_id = item.get("record_id", "")
            action_raw = item.get("action", "")
            action = bh._ACTION_MAP.get(action_raw, action_raw)
            if not record_id:
                continue
            after_value = item.get("after_value", [])
            event_fields: dict[str, Any] = {}
            if after_value:
                event_fields = bh._convert_after_value_to_fields(after_value, field_map)
            await _handle_ai_record_action(bitable, record_id, action, event_fields)
        return

    # 兼容旧 flat 格式
    record_id = event.get("record_id", "")
    action = event.get("action", "")
    event_fields = event.get("fields", {}) or {}
    if not record_id:
        return
    await _handle_ai_record_action(bitable, record_id, action, event_fields)


async def _handle_ai_record_action(
    bitable: SafetyBitableClient,
    record_id: str,
    action: str,
    event_fields: dict[str, Any],
) -> None:
    """分发单条记录变更（AI-only）。"""
    if action == "delete":
        logger.info("AI接入: 删除事件忽略 record_id=%s", record_id)
        return

    # ── insert: 收录 + AI 识别 ──
    if action == "insert":
        if await bh._is_duplicate("insert", record_id, suffix=""):
            logger.info("AI接入: 重复 insert 事件忽略 record_id=%s", record_id)
            return
        lock_key = f"bitable:lock:insert:{record_id}"
        try:
            if not await redis_client.set(lock_key, "1", ex=120, nx=True):
                logger.warning("AI接入: INSERT 锁已存在，跳过 record_id=%s", record_id)
                return
        except Exception:
            pass  # Redis 不可用时降级，依赖 unique index 兜底
        existing = await bh._get_hazard_by_feishu_id(record_id)
        if existing:
            logger.info(
                "AI接入: record_id=%s 已关联 hazard_id=%s，跳过收录", record_id, existing.id,
            )
            return
        fields = await bitable.get_record(record_id) or event_fields
        if not fields:
            logger.warning("AI接入: insert 无可用字段 record_id=%s", record_id)
            return
        await _create_and_identify(record_id, fields)
        return

    # ── update: 整改完成时间被填写 → AI 整改初审 ──
    if action == "update":
        if await bh._is_sync_ignored(record_id):
            logger.debug("AI接入: 跳过平台自身回写触发的 update record_id=%s", record_id)
            return
        # 触发条件：本次填写/变更了「整改完成时间」（整改回复提交的信号，与旧流程一致）。
        # 仅「纠正预防措施」变更（尚未填完成时间）不触发初审，避免半成品被提前审。
        if "整改完成时间" not in event_fields:
            logger.debug("AI接入: update 未填写整改完成时间，跳过初审 record_id=%s", record_id)
            return
        # 校验值是否有效：event_fields 只报告哪些字段变了，不保证值非空。
        # 用户在 Bitable 中点进点出、或同步脚本写入空值，都会触发 changed 事件但值为空。
        completion_value = event_fields.get("整改完成时间")
        if not completion_value or (isinstance(completion_value, str) and not completion_value.strip()):
            logger.info(
                "AI接入: 整改完成时间为空，跳过初审 record_id=%s", record_id,
            )
            return
        suffix = ",".join(sorted(event_fields.keys()))
        if await bh._is_duplicate("update", record_id, suffix=suffix):
            logger.info("AI接入: 重复 update 事件忽略 record_id=%s", record_id)
            return

        # 拉全量字段（附件需要预签名 URL；整改回复/完成时间取完整值）
        fields = await bitable.get_record(record_id) or {}
        if event_fields:
            fields.update(event_fields)

        hazard = await bh._get_hazard_by_feishu_id(record_id)
        if not hazard:
            # INSERT 事件丢失场景：先收录 + 识别，再进行初审
            logger.info("AI接入: update 无关联记录，先收录 record_id=%s", record_id)
            hazard = await _create_and_identify(record_id, fields)
            if not hazard:
                return
        asyncio.create_task(_debounced_review(record_id, hazard, fields))
        return


# ═══════════════════════════════════════════════════════════════
# create：收录 + AI 隐患识别 + 回写
# ═══════════════════════════════════════════════════════════════

async def _create_and_identify(record_id: str, bitable_fields: dict[str, Any]) -> Any | None:
    """收录隐患 → AI 识别 → 回写「隐患编号 + AI 识别结果」。返回 HazardReport。"""
    from app.modules.safety.models import HazardReport
    from app.modules.safety.schemas import HazardReportCreate
    from app.modules.safety.service import SafetyService

    session = async_session_factory()
    try:
        service = SafetyService(session)
        mapped = bh._map_bitable_fields(bitable_fields)
        mapped.setdefault("discovered_at", datetime.now())

        # 收录仅取 AI 输入字段；不做飞书身份解析、不写业务人员字段（AI 外置）
        photo_fields = {"defect_photos", "rectification_photos"}
        create_data = {
            k: v for k, v in mapped.items()
            if k in HazardReportCreate.model_fields and k not in photo_fields
        }
        data = HazardReportCreate(**create_data)
        item = await service.hazard.create_hazard(data, auto_run_ai=False)
        item.feishu_record_id = record_id
        item.source_table_id = bh._hazard_table_id()
        await session.flush()
        try:
            await session.commit()
        except IntegrityError:
            # 并发创建冲突 → 取已有记录
            await session.rollback()
            logger.warning("AI接入: feishu_record_id 唯一冲突，取已有记录 record_id=%s", record_id)
            return await bh._get_hazard_by_feishu_id(record_id)

        logger.info(
            "AI接入: 隐患已收录 record_id=%s hazard_id=%s hazard_no=%s",
            record_id, item.id, item.hazard_no,
        )

        # 下载缺陷图片到本地（AI 视觉识别输入）
        saved = await bh._download_and_save_attachments(
            SafetyBitableClient(), bitable_fields, str(item.id), record_id=record_id,
        )
        photo_updates: dict[str, str] = {}
        if saved.get("defect"):
            photo_updates["defect_photos"] = json.dumps(
                [p.replace("\\", "/") for p in saved["defect"]], ensure_ascii=False,
            )
        if saved.get("rectification"):
            photo_updates["rectification_photos"] = json.dumps(
                [p.replace("\\", "/") for p in saved["rectification"]], ensure_ascii=False,
            )
        if photo_updates:
            await session.execute(
                update(HazardReport).where(HazardReport.id == item.id).values(**photo_updates)
            )
            await session.commit()

        # 重新加载最新状态 → 执行 AI 隐患识别
        item = await service.hazard.repo.get_hazard_by_id(item.id)
        item = await service.hazard.run_hazard_ai_script(item.id, 1)
        await session.commit()

        await _writeback_identification(record_id, item)
        return item
    except Exception:
        logger.exception("AI接入: 收录+识别失败 record_id=%s", record_id)
        try:
            await session.rollback()
        except Exception:
            pass
        return None
    finally:
        await session.close()


async def _writeback_identification(record_id: str, item: Any) -> None:
    """回写「隐患编号 + AI 识别结果」到目标表（仅这 7 个字段）。"""
    if not item:
        return
    writeback: dict[str, Any] = {"隐患编号": item.hazard_no}
    if item.hazard_type:
        writeback["隐患分类（AI）"] = bh._format_bitable_select_value(
            "隐患分类（AI）", bh.HAZARD_TYPE_REVERSE.get(item.hazard_type, item.hazard_type),
        )
    if item.hazard_level:
        writeback["隐患级别（AI）"] = bh._format_bitable_select_value(
            "隐患级别（AI）", bh.HAZARD_LEVEL_REVERSE.get(item.hazard_level, item.hazard_level),
        )
    if item.hazard_category:
        writeback["隐患类别（AI）"] = bh._format_bitable_select_value(
            "隐患类别（AI）", bh.HAZARD_CATEGORY_REVERSE.get(item.hazard_category, item.hazard_category),
        )
    if item.key_defect:
        writeback["隐患描述（AI）"] = item.key_defect
    if item.major_hazard_basis:
        writeback["隐患判定依据（AI）"] = item.major_hazard_basis
    if item.corrective_preventive_measures:
        writeback["整改建议（AI）"] = item.corrective_preventive_measures

    bitable = SafetyBitableClient()
    await bh._set_sync_ignore(record_id, ttl=30)
    ok = await bitable.update_record(record_id, writeback)
    if ok:
        logger.info(
            "AI接入: 识别结果已回写 record_id=%s hazard_no=%s fields=%s",
            record_id, item.hazard_no, list(writeback.keys()),
        )
    else:
        logger.error(
            "AI接入: 识别结果回写失败 record_id=%s fields=%s", record_id, list(writeback.keys()),
        )


# ═══════════════════════════════════════════════════════════════
# update：AI 整改初审 + 回写
# ═══════════════════════════════════════════════════════════════

async def _debounced_review(
    record_id: str, hazard: Any, bitable_fields: dict[str, Any],
    delay: int = 180,
) -> None:
    """防抖 AI 整改初审：delay 秒内如收到同记录新更新则重置计时器。

    设计意图：用户在 Bitable 中填完整改回复后常会继续微调（补充说明、
    更正错别字、上传更多照片），每次变更都触发 webhook。与其每次立即触发
    AI 初审（重复烧 token），不如等用户停止编辑 delay 秒后再触发一次。

    防抖逻辑：
    1. 每次更新 → SET Redis key = 新 generation（覆盖旧值）
    2. sleep delay 秒
    3. 醒来 → GET Redis key == 自己的 generation？
       是 → 无新更新，触发 AI 初审
       否 → 有新更新重置了计时器，取消本次

    Redis 不可用时降级为立即触发（fail-open，宁重复不错过）。
    """
    import uuid as uuid_mod

    debounce_key = f"safety:debounce:rectification:{record_id}"
    generation = str(uuid_mod.uuid4())

    try:
        await redis_client.set(debounce_key, generation, ex=delay + 60)
        logger.info(
            "防抖: 已排程AI初审 record_id=%s delay=%ds gen=%s",
            record_id, delay, generation[:8],
        )
    except Exception:
        logger.warning("Redis 不可用，防抖降级为立即触发 record_id=%s", record_id)
        await _review_rectification(record_id, hazard, bitable_fields)
        return

    await asyncio.sleep(delay)

    # 检查是否被后续更新重置了计时器
    try:
        current = await redis_client.get(debounce_key)
        if current != generation:
            current_preview = (current or b"expired").decode()[:8]
            logger.info(
                "防抖取消: record_id=%s %ds内有新更新 gen=%s→%s",
                record_id, delay, generation[:8], current_preview,
            )
            return
    except Exception:
        pass  # Redis 不可用 → 继续执行（fail-open）

    logger.info("防抖触发: record_id=%s %ds内无新更新，开始AI初审", record_id, delay)
    await _review_rectification(record_id, hazard, bitable_fields)


async def _review_rectification(
    record_id: str, hazard: Any, bitable_fields: dict[str, Any],
) -> None:
    """整改完成时间已填 → AI 整改初审（纯生成，无通知/状态机）→ 回写「AI初审结果 + AI初审说明」。"""
    from app.modules.safety.service import SafetyService
    from app.modules.safety.service.hazard import _build_ai_review_summary

    mapped = bh._map_bitable_fields(bitable_fields)
    reply = mapped.get("rectification_reply")
    completion = mapped.get("actual_completion_date")

    session = async_session_factory()
    try:
        service = SafetyService(session)
        item = await service.hazard.repo.get_hazard_by_id(hazard.id)
        if not item:
            return

        # 落库 AI 初审输入：整改回复 + 整改完成时间 + 整改后图片（仅本地 DB，不回写业务字段）
        update_data: dict[str, Any] = {}
        if reply and str(reply).strip():
            update_data["rectification_reply"] = str(reply)
        if completion:
            update_data["actual_completion_date"] = completion
        _photo_fields = {
            k: v for k, v in bitable_fields.items()
            if k in ("缺陷图片", "整改后图片") and v
        }
        if _photo_fields:
            saved = await bh._download_and_save_attachments(
                SafetyBitableClient(), _photo_fields, str(item.id), record_id=record_id,
            )
            if saved.get("rectification"):
                update_data["rectification_photos"] = merge_photos_json(
                    getattr(item, "rectification_photos", None), saved["rectification"],
                )
            if saved.get("defect"):
                update_data["defect_photos"] = merge_photos_json(
                    getattr(item, "defect_photos", None), saved["defect"],
                )
        if update_data:
            await service.hazard.repo.update_hazard(item.id, update_data)
            await session.commit()

        item = await service.hazard.repo.get_hazard_by_id(item.id)

        # 无整改回复 → 跳过 AI 初审（空数据无法审核）
        if not item.rectification_reply or not item.rectification_reply.strip():
            logger.info(
                "AI接入: 整改回复为空，跳过AI初审 record_id=%s hazard_no=%s",
                record_id, getattr(item, "hazard_no", "?"),
            )
            await session.close()
            return

        # ── 防重入（软检查）：已完成 1h 内 → 跳过 ──
        ai_status = getattr(item, "ai_review_status", None)
        if ai_status == "completed":
            completed_at = getattr(item, "ai_review_completed_at", None)
            if completed_at:
                age_s = (datetime.now() - completed_at).total_seconds()
                if age_s < 3600:
                    logger.info(
                        "AI接入: AI初审已完成(%.0fs前)，跳过重复触发 record_id=%s hazard_no=%s",
                        age_s, record_id, getattr(item, "hazard_no", "?"),
                    )
                    await session.close()
                    return

        # ── 防重入（原子锁）：条件 UPDATE 确保只有一个并发请求能获取处理权 ──
        # WHERE status != 'processing' 保证数据库层面互斥，消除 TOCTOU 竞态
        from sqlalchemy import update as sa_update

        from app.modules.safety.models import HazardReport

        lock_result = await session.execute(
            sa_update(HazardReport)
            .where(
                HazardReport.id == item.id,
                HazardReport.ai_review_status != "processing",
            )
            .values(ai_review_status="processing")
            .returning(HazardReport.id)
        )
        if not lock_result.scalar_one_or_none():
            logger.info(
                "AI接入: AI初审已被其他进程锁定，跳过 record_id=%s hazard_no=%s",
                record_id, getattr(item, "hazard_no", "?"),
            )
            await session.close()
            return
        await session.commit()

        # AI 整改初审（纯生成方法，不发通知、不驱动状态机）
        try:
            from app.modules.safety.ai_audit import ai_audit_scope

            # 审计归因：此处是 Bitable 事件驱动的初审主路径（不经过
            # run_rectification_review），必须自行开 scope，否则落 unknown
            with ai_audit_scope(
                scenario="rectification_review",
                resource_type="hazard",
                resource_id=item.id,
                channel="system",
            ):
                result = await service.hazard._generate_rectification_review(item)
        except Exception:
            logger.exception("AI接入: AI 整改初审生成失败 record_id=%s", record_id)
            await service.hazard.repo.update_hazard(
                item.id, {"ai_review_status": "failed"}
            )
            await session.commit()
            return

        await service.hazard.repo.update_hazard(
            item.id,
            {
                "ai_review_result": result,
                "ai_review_status": "completed",
                "ai_review_completed_at": datetime.now(),
            },
        )
        await session.commit()

        conclusion = (result.get("review_conclusion") or "").strip()
        bitable_conclusion = _REVIEW_CONCLUSION_TO_BITABLE.get(conclusion, "未通过")
        summary = _build_ai_review_summary(result)

        bitable = SafetyBitableClient()
        await bh._set_sync_ignore(record_id, ttl=30)
        ok = await bitable.update_record(
            record_id, {"AI初审结果": bitable_conclusion, "AI初审说明": summary},
        )
        if ok:
            logger.info(
                "AI接入: AI初审结果已回写 record_id=%s hazard_no=%s conclusion=%s",
                record_id, item.hazard_no, bitable_conclusion,
            )
        else:
            logger.error("AI接入: AI初审结果回写失败 record_id=%s", record_id)
    except Exception:
        logger.exception("AI接入: 整改初审失败 record_id=%s", record_id)
        try:
            await session.rollback()
        except Exception:
            pass
    finally:
        await session.close()



# 供事件客户端 import 时触发 @on_event 注册（无实际逻辑）
def _ensure_registered() -> None:
    """import 本模块即完成事件注册；此函数仅作显式引用锚点。"""
    return None
