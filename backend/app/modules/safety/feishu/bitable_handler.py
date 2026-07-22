"""安全模块 Bitable 事件处理器 — 隐患登记双向同步。

监听飞书多维表格的 record.created_v1 / record.changed_v1 事件，
实现 Bitable ↔ HazardReport 双向同步。

Bitable → 平台：用户填表 → 自动创建隐患 + AI识别 + 回写结果
平台 → Bitable：平台上修改隐患 → 自动回写 Bitable 对应行
"""

import asyncio
import json
import logging
import os
import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from app.core.redis import redis_client
from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.feishu.dept_config import DEPARTMENT_CONFIG
from app.modules.safety.feishu.event_client import on_event
from app.modules.safety.schemas.enums import HazardCategory, HazardLevel, HazardType
from app.modules.safety.service.hazard import (
    _build_verify_card_content,
    _send_rectification_notification,
    _send_verify_notification,
)

logger = logging.getLogger(__name__)

# ── 调试文件日志：追踪通知流程的完整调用链 ──
_debug_log_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "debug_notify.log")


def _debug_log(msg: str) -> None:
    """写调试日志到文件（用于排查通知未发送问题）。"""
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with open(_debug_log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════════
# 字段映射：Bitable 中文字段名 → HazardReport 英文字段名
# ═══════════════════════════════════════════════════════════════

BITABLE_TO_MODEL: dict[str, str] = {
    # ── 基本信息 ──
    "检查日期":            "discovered_at",
    "检查人员":            "discovered_by_name",       # person 类型 → 取 name
    "检查人员.部门":       "inspector_department",      # multi_select → 逗号拼接（60 部门选项）
    "检查类别":            "inspection_category",       # multi_select → 逗号拼接
    "隐患描述":            "description",
    "责任部门":            "department",
    "整改责任人":            "rectification_responsible_person_name",
    # ── 隐患分类/分级（AI 识别，由平台回写）──
    "隐患分类（AI）":       "hazard_type",               # single_select: 人的不安全行为/物的不安全状态/环境的不安全因素/管理的缺陷
    "隐患类别（AI）":       "hazard_category",            # single_select: 设备设施/危化储存/仪表+电气/...（13种）
    "隐患级别（AI）":       "hazard_level",               # single_select: 一般隐患/较大隐患/重大隐患
    "隐患描述（AI）":       "key_defect",                 # text: AI 生成的隐患描述
    "隐患判定依据（AI）":   "major_hazard_basis",         # text: AI 生成的判定依据
    # ── 附件 ──
    "缺陷图片":            "defect_photos",              # attachment → JSON 路径数组
    "整改后图片":          "rectification_photos",
    # ── 整改相关（整改状态为平台→Bitable 单向，不在此映射）──
    "纠正预防措施":         "rectification_reply",
    "整改期限":            "deadline",
    "整改完成时间":         "actual_completion_date",
    # ── 三级复核（Bitable 审批字段）──
    "部门负责人复核":       "verify_level_1_status",      # single_select: 已同意→approved / 未同意→rejected
    "分管领导复核":         "verify_level_2_status",      # single_select: 已同意→approved / 未同意→rejected
    "检查人员复核":         "verify_level_3_status",      # single_select: 已同意→approved / 未同意→rejected
    # ── 系统回写字段 ──
    "隐患编号":            "hazard_no",
    "整改建议（AI）":       "corrective_preventive_measures",  # AI 生成的整改建议
}

# 反向映射：英文字段名 → 中文 Bitable 字段名
MODEL_TO_BITABLE: dict[str, str] = {v: k for k, v in BITABLE_TO_MODEL.items()}

# 需要从 Bitable 读取但不会直接写入 DB 的元数据字段
META_FIELDS: set[str] = {"隐患编号"}

# Bitable person 类型字段 — 不能写纯文本，必须用 [{"id": "bitable_open_id"}] 格式
# 这些字段在 push_hazard_to_bitable 中单独处理（查 BitableIdMapper），
# _map_model_to_bitable 输出时必须跳过，否则会因 UserFieldConvFail 导致整次回写失败
PERSON_FIELDS: set[str] = {"整改责任人", "检查人员"}

# Bitable attachment 类型字段 — 不能写纯文本/JSON 字符串，必须通过
# Bitable API 单独上传附件获取 file_token 后写入
# _map_model_to_bitable 输出时必须跳过，否则会因 AttachFieldConvFail 导致整次回写失败
ATTACHMENT_FIELDS: set[str] = {"缺陷图片", "整改后图片"}

# ── Bitable 值 → 模型值 的类型转换映射 ──
# 隐患分类
HAZARD_TYPE_MAP: dict[str, str] = {
    "人的不安全行为":   "unsafe_action",
    "物的不安全状态":   "unsafe_condition",
    "环境的不安全因素":  "environmental",
    "管理的缺陷":       "management_defect",
}
# 隐患类别（13种）
HAZARD_CATEGORY_MAP: dict[str, str] = {
    "设备设施":           "equipment",
    "危化储存":           "hazardous_storage",
    "应急管理":           "emergency_mgmt",
    "仪表+电气":          "instrument_electrical",
    "防雷防静电":         "lightning_antistatic",
    "职业健康+劳保防护":   "occupational_health",
    "三违作业":           "violation_operation",
    "6S":                "six_s",
    "标签标识":           "label_signage",
    "工艺管理":           "process_mgmt",
    "承包商缺陷":         "contractor_defect",
    "内页资料":           "documentation",
    "特殊作业":           "special_operation",
}
# 隐患级别
HAZARD_LEVEL_MAP: dict[str, str] = {
    "一般隐患": "general",
    "较大隐患": "serious",
    "重大隐患": "major",
}
# 审批状态（三级复核）
APPROVAL_STATUS_MAP: dict[str, str] = {
    "已同意": "approved",
    "未同意": "rejected",
    "无需复核": "no_review_needed",
}

# 整改状态 → Bitable 中文标签（平台→Bitable 回写用）
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

# 反向映射
HAZARD_TYPE_REVERSE = {v: k for k, v in HAZARD_TYPE_MAP.items()}
HAZARD_CATEGORY_REVERSE = {v: k for k, v in HAZARD_CATEGORY_MAP.items()}
HAZARD_LEVEL_REVERSE = {v: k for k, v in HAZARD_LEVEL_MAP.items()}
APPROVAL_STATUS_REVERSE = {v: k for k, v in APPROVAL_STATUS_MAP.items()}


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _extract_person_info(value: Any) -> dict[str, str]:
    """从 Bitable person 字段一次性提取全部可用信息。

    Bitable person 字段值格式（事件 / API 返回）：
        旧格式: [{"id": "ou_xxx", "name": "张三", "email": "zhangsan@example.com", ...}]
        新格式: {"users": [{"userId": "7307...", "name": "张三", ...}]}

    Returns:
        {"name": ..., "id": ..., "email": ...}  —— 缺失字段为空字符串。
        空输入返回全空 dict。
    """
    if not value:
        return {"name": "", "id": "", "email": ""}

    # ── 新格式: {"users": [{"userId": ..., "name": ...}]} ──
    if isinstance(value, dict) and "users" in value:
        users = value["users"]
        if isinstance(users, list) and users:
            first = users[0]
            if isinstance(first, dict):
                return {
                    "name": (first.get("name") or "").strip(),
                    "id": (first.get("userId") or first.get("id") or "").strip(),
                    "email": (first.get("email") or "").strip(),
                }
        return {"name": "", "id": "", "email": ""}

    if isinstance(value, list):
        if not value:
            return {"name": "", "id": "", "email": ""}
        first = value[0]
    elif isinstance(value, dict):
        first = value
    else:
        return {"name": str(value) if value else "", "id": "", "email": ""}
    if not isinstance(first, dict):
        return {"name": str(first), "id": "", "email": ""}
    return {
        "name": (first.get("name") or "").strip(),
        "id": (first.get("id") or "").strip(),
        "email": (first.get("email") or "").strip(),
    }


def _is_open_id_like(s: str) -> bool:
    """判断字符串是否像飞书 open_id（不以 ou_ 开头则可能是真实姓名）。"""
    return bool(s and s.startswith("ou_"))


# ── 统一身份解析 ──

async def _resolve_person(
    session,
    bt_value: Any,
    *,
    bt_field_label: str = "person",
    existing_name: str | None = None,
) -> tuple[str | None, str | None, str]:
    """将 Bitable person 字段值解析为 (db_uuid, open_id, display_name)。

    解析优先级（从高到低）：
      1. Bitable 里的 name（如果有且不像 open_id）→ 直接用
      2. 按 person.id 查 identity.users（user_id 回退 open_id）
      3. 按 person.email 查 identity.users
      4. 按 Bitable name 查 identity.users
      5. Bitable id 本身（避免数据显示为空）
      6. existing_name（已有值，更新时不覆盖）
      7. "飞书用户"（最终 fallback）

    Returns:
        (uuid_str | None, open_id_str, display_name_str)
        display_name 保证不为空字符串。
    """
    info = _extract_person_info(bt_value)
    person_id = info["id"]
    person_name = info["name"]
    person_email = info["email"]

    logger.debug(
        "_resolve_person[%s]: id=%r name=%r email=%r existing=%r",
        bt_field_label, person_id, person_name, person_email, existing_name,
    )

    from app.modules.safety.feishu.identity_resolver import IdentityResolver
    resolver = IdentityResolver(session)
    user = None

    # ── 策略 1：Bitable name 看起来像真实姓名 → 先用 ──
    usable_bt_name = person_name and not _is_open_id_like(person_name)

    # ── 策略 2：按 person.id 查 identity.users ──
    if person_id:
        try:
            user = await resolver._find_user_by_user_id(person_id)
        except Exception:
            logger.exception("_resolve_person[%s] 按 id 查询异常", bt_field_label)

    # ── 策略 2.5：安全应用 open_id → user_id 反向映射 → identity.users ──
    # Bitable person 字段的 open_id 是安全应用命名空间，identity.users 存的是全局应用 open_id，
    # 两个命名空间不同导致策略 2 的 feishu_open_id 匹配失败。通过 bitable_open_ids.json
    # 反向查找 user_id，再按 feishu_user_id 查 identity.users。
    if not user and person_id and _is_open_id_like(person_id):
        try:
            from app.modules.safety.feishu.bitable_id_mapper import (
                get_user_id_by_bitable_open_id,
            )
            mapped_user_id = get_user_id_by_bitable_open_id(person_id)
            if mapped_user_id:
                user = await resolver._find_user_by_user_id(mapped_user_id)
                if user:
                    logger.info(
                        "_resolve_person[%s] bitable open_id 反向映射成功: bitable_oid=%s → user_id=%s → %s",
                        bt_field_label, person_id, mapped_user_id, user.name,
                    )
        except Exception:
            logger.exception("_resolve_person[%s] bitable open_id 反向映射异常", bt_field_label)

    # ── 策略 3：按 email 查（Bitable open_id 与 identity 表可能不同）──
    if not user and person_email:
        try:
            user = await resolver._find_user_by_email(person_email)
            if user:
                logger.info(
                    "_resolve_person[%s] email 回退成功: email=%s → %s",
                    bt_field_label, person_email, user.name,
                )
        except Exception:
            logger.exception("_resolve_person[%s] 按 email 查询异常", bt_field_label)

    # ── 策略 4：按 Bitable name 查 identity.users ──
    if not user and usable_bt_name:
        try:
            user = await resolver._find_user_by_name(person_name)
            if user:
                logger.info(
                    "_resolve_person[%s] name 回退成功: name=%s → %s",
                    bt_field_label, person_name, user.name,
                )
        except Exception:
            logger.exception("_resolve_person[%s] 按 name 查询异常", bt_field_label)

    # ── 确定最终返回值 ──
    if user:
        return (str(user.id), user.feishu_open_id or person_id, user.name)

    # identity 查不到 → 用 Bitable 中的数据
    if usable_bt_name:
        return (None, person_id, person_name)

    if person_id:
        # Bitable 有 ID 但没有可用的 name → 用 ID 作为显示名（比 "飞书用户" 好）
        return (None, person_id, person_id)

    # 完全空 → 用已有值或 fallback
    if existing_name and existing_name != "飞书用户":
        return (None, "", existing_name)

    return (None, "", "飞书用户")


def _extract_select_values(value: Any) -> str:
    """从 Bitable select 字段提取文本（单选返回字符串，多选返回逗号分隔）。"""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v)
    if isinstance(value, str):
        return value
    return ""


def _extract_attachments(value: Any) -> list[dict]:
    """从 Bitable attachment 字段提取附件列表。"""
    if isinstance(value, list):
        return [
            {"file_token": a.get("file_token", ""), "name": a.get("name", "")}
            for a in value if isinstance(a, dict)
        ]
    return []


def _extract_rich_text(value: Any) -> str:
    """从 Bitable 富文本字段提取纯文本。

    Bitable 富文本字段返回格式：
        [{"type": "text", "text": "合成", "style": {}}]

    普通文本字段返回纯字符串。此函数兼容两种格式。
    """
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                parts.append(item.get("text", ""))
            elif item:
                parts.append(str(item))
        return "".join(parts)
    if isinstance(value, str):
        return value
    return str(value) if value else ""


def _ms_to_datetime(value: Any) -> datetime | None:
    """将 Bitable 毫秒时间戳转为 datetime。"""
    if isinstance(value, (int, float)) and value > 0:
        try:
            return datetime.fromtimestamp(value / 1000, tz=UTC)
        except (OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
        except (ValueError, OSError):
            pass
    return None


def _datetime_to_ms(value: Any) -> int | str:
    """将 datetime 转为 Bitable 毫秒时间戳。"""
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return int(value.timestamp() * 1000)
    return ""


def _map_bitable_fields(bitable_fields: dict[str, Any]) -> dict[str, Any]:
    """将 Bitable 中文字段 → HazardReport 模型 dict。

    处理类型转换：
    - person → name string
    - select/multi_select → string
    - datetime (ms) → datetime
    - attachment → JSON string (file_token list)
    """
    result: dict[str, Any] = {}

    for cn_name, en_name in BITABLE_TO_MODEL.items():
        if cn_name not in bitable_fields:
            continue
        raw = bitable_fields[cn_name]
        if raw is None:
            continue

        # ── 按字段类型处理 ──
        if en_name in ("discovered_by_name", "rectification_responsible_person_name"):
            # person 字段：先提取 Bitable 中的 name，非空才入 mapped
            # （空 person 如 [] 会产生空字符串，跳过避免覆盖已有数据）
            # 注意：如果 Bitable 只有 id 没有 name，这里会把 id 作为 name
            #       后续 _resolve_person 会按 id/email 做 identity 查询修正
            info = _extract_person_info(raw)
            if info["name"]:
                result[en_name] = info["name"]
            elif info["id"]:
                result[en_name] = info["id"]
        elif en_name in ("inspection_category", "hazard_category", "hazard_type",
                         "hazard_level",
                         "inspector_department",
                         "verify_level_1_status", "verify_level_2_status", "verify_level_3_status"):
            val = _extract_select_values(raw)
            # 跳过空值，避免 Pydantic enum 校验失败
            if not val:
                continue
            if en_name == "hazard_type":
                mapped = HAZARD_TYPE_MAP.get(val, "unsafe_condition")
                if mapped in HazardType.__members__:
                    result[en_name] = mapped
            elif en_name == "hazard_category":
                mapped = HAZARD_CATEGORY_MAP.get(val, val)
                if mapped in HazardCategory.__members__:
                    result[en_name] = mapped
            elif en_name == "hazard_level":
                mapped = HAZARD_LEVEL_MAP.get(val, "general")
                if mapped in HazardLevel.__members__:
                    result[en_name] = mapped
            elif en_name in ("verify_level_1_status", "verify_level_2_status", "verify_level_3_status"):
                result[en_name] = APPROVAL_STATUS_MAP.get(val, "pending")
            else:
                result[en_name] = val
        elif en_name in ("defect_photos", "rectification_photos"):
            attachments = _extract_attachments(raw)
            result[en_name] = json.dumps(attachments, ensure_ascii=False) if attachments else None
        elif en_name in ("discovered_at", "deadline", "actual_completion_date"):
            dt = _ms_to_datetime(raw)
            if dt:
                result[en_name] = dt
        elif en_name in ("_ai_summary", "_rectification_advice"):
            # 元数据字段，不写入 DB
            pass
        else:
            # 纯文本/富文本字段（兼容 Bitable 富文本 [{"type":"text","text":"..."}] 格式）
            result[en_name] = _extract_rich_text(raw) or None

    return result


def _format_bitable_select_value(field_cn: str, value: Any) -> Any:
    """根据 Bitable 字段类型调整值的格式。

    - single_select (type=3): 保持字符串
    - multi_select (type=4): 必须是数组，字符串自动包装为 [str]
    - 其他类型: 原样返回
    """
    ftype = (_field_type_cache or {}).get(field_cn, 0)
    if ftype == 4 and isinstance(value, str):
        return [value]
    return value


def _map_model_to_bitable(hazard: Any) -> dict[str, Any]:
    """将 HazardReport 模型 → Bitable 中文字段 dict（仅含需要回写的字段）。"""
    result: dict[str, Any] = {}

    for en_name, cn_name in MODEL_TO_BITABLE.items():
        if cn_name in META_FIELDS or cn_name in PERSON_FIELDS or cn_name in ATTACHMENT_FIELDS or en_name.startswith("_"):
            continue
        val = getattr(hazard, en_name, None)
        if val is None:
            continue

        if en_name == "hazard_type":
            result[cn_name] = _format_bitable_select_value(cn_name, HAZARD_TYPE_REVERSE.get(val, val))
        elif en_name == "hazard_category":
            result[cn_name] = _format_bitable_select_value(cn_name, HAZARD_CATEGORY_REVERSE.get(val, val))
        elif en_name == "hazard_level":
            result[cn_name] = _format_bitable_select_value(cn_name, HAZARD_LEVEL_REVERSE.get(val, val))
        elif en_name in ("verify_level_1_status", "verify_level_2_status", "verify_level_3_status"):
            result[cn_name] = _format_bitable_select_value(cn_name, APPROVAL_STATUS_REVERSE.get(val, val))
        elif en_name in ("inspection_category", "inspector_department"):
            # multi_select 字段：DB 存储为逗号分隔字符串，Bitable 需要数组
            items = [item.strip() for item in str(val).split(",") if item.strip()]
            if items:
                result[cn_name] = items
        elif en_name in ("discovered_at", "deadline", "actual_completion_date"):
            ms = _datetime_to_ms(val)
            if ms:
                result[cn_name] = ms
        else:
            # _format_bitable_select_value 利用 _field_type_cache 判断字段类型：
            #   single_select (type=3) → 原样返回字符串
            #   multi_select (type=4)  → 包装为 [str]
            # 其他未显式列出的 select 字段走此路径
            result[cn_name] = _format_bitable_select_value(cn_name, str(val) if not isinstance(val, str) else val)

    return result


async def _is_duplicate(event_type: str, record_id: str, ttl: int = 60, suffix: str = "") -> bool:
    """Redis 去重。返回 True 表示重复事件。

    为避免同一 record 的不同字段编辑在 TTL 窗口内被错误去重，
    suffix 应包含变更字段名以区分不同编辑操作。
    例如：suffix="整改完成时间" → key="bitable:event:recXXX:update:整改完成时间"
    """
    key = f"bitable:event:{record_id}:{event_type}"
    if suffix:
        key = f"{key}:{suffix}"
    try:
        return not await redis_client.set(key, "1", ex=ttl, nx=True)
    except Exception:
        logger.warning("Redis 不可用，跳过去重", exc_info=True)
        return False


async def _set_sync_ignore(record_id: str, ttl: int = 30) -> None:
    """标记 record 为「平台发起」，让 changed_v1 处理器跳过。"""
    key = f"bitable:ignore:{record_id}"
    try:
        await redis_client.set(key, "1", ex=ttl, nx=False)
    except Exception:
        pass


async def _is_sync_ignored(record_id: str) -> bool:
    """检查是否应跳过此次 changed 事件。"""
    key = f"bitable:ignore:{record_id}"
    try:
        return await redis_client.exists(key) > 0
    except Exception:
        return False


def _compute_advisory_lock_id(record_id: str) -> int:
    """将 feishu_record_id 转换为 PostgreSQL advisory lock 使用的 bigint。

    pg_advisory_lock 接受一个 signed 64-bit 整数（bigint）。
    我们用 record_id 的 MD5 前 16 字符（64-bit）取模映射到 [0, 2^63-1] 范围。
    """
    import hashlib
    hash_hex = hashlib.md5(record_id.encode()).hexdigest()[:16]
    return int(hash_hex, 16) % (2**63 - 1)


# ═══════════════════════════════════════════════════════════════
# 核心同步逻辑
# ═══════════════════════════════════════════════════════════════

async def _get_hazard_by_feishu_id(feishu_record_id: str) -> Any | None:
    """根据 feishu_record_id 查找 HazardReport。

    返回唯一的未删除记录。当 feishu_record_id 因 INSERT 竞态条件而重复时，
    记录警告日志并返回第一条（避免 MultipleResultsFound 异常导致整个 handler 崩溃）。
    """
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.modules.safety.models import HazardReport

    async with async_session_factory() as session:
        stmt = (
            select(HazardReport)
            .where(
                HazardReport.feishu_record_id == feishu_record_id,
                HazardReport.is_deleted == False,  # noqa: E712
            )
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()
        if not rows:
            return None
        if len(rows) > 1:
            logger.warning(
                "feishu_record_id=%s 存在 %d 条重复记录（hazard_ids=%s），"
                "取第一条。建议手动清理重复记录。",
                feishu_record_id,
                len(rows),
                [str(r.id) for r in rows],
            )
        return rows[0]


def _build_attachment_extra(
    table_id: str,
    record_id: str,
    field_id: str,
    file_token: str,
) -> str:
    """构建高级权限多维表格的 extra 鉴权参数（URL-encoded JSON）。

    飞书要求格式：
    {"bitablePerm": {"tableId": "...", "attachments": {"fldXXX": {"recXXX": ["file_token"]}}}}
    """
    import urllib.parse

    payload = {
        "bitablePerm": {
            "tableId": table_id,
            "attachments": {
                field_id: {record_id: [file_token]},
            },
        },
    }
    return urllib.parse.quote(json.dumps(payload, separators=(",", ":")))


async def _download_and_save_attachments(
    bitable: SafetyBitableClient,
    bitable_fields: dict[str, Any],
    hazard_id: str,
    record_id: str = "",
) -> dict[str, list[str]]:
    """下载 Bitable 附件并保存到本地。返回 {"defect": [路径], "rectification": [路径]}。

    核心策略：
    1. 优先通过 Bitable API 拉取完整记录（附件字段含 url/tmp_url 预签名链接）
    2. API 失败 → 回退到事件数据 file_token（需手工构建 extra 走 Drive API）
    3. url 下载先带 Authorization header，失败则无 auth 重试（兼容内部预签名 URL）
    4. 下载后校验内容类型，避免将 JSON/HTML 误存为图片
    5. 缺陷图片 和 整改后图片 分开返回
    """
    _att_fields = ("缺陷图片", "整改后图片")
    upload_dir = os.path.join("uploads", "safety", "hazard")
    os.makedirs(upload_dir, exist_ok=True)

    if not record_id:
        logger.warning("Bitable 下载附件缺少 record_id，跳过")
        return {"defect": [], "rectification": []}

    # ── Step 1: 获取 field_name ↔ field_id 映射（提前准备，用于回退策略和字段名解析）──
    field_id_to_name = await _get_field_name_map(bitable)
    field_name_to_id = {v: k for k, v in field_id_to_name.items()}

    # ── Step 2: 通过 Bitable API 拉取完整记录 ──
    #    事件数据只含 [{file_token, name}]，不含 url。
    #    API 返回的附件包含 url（永久下载链接，extra 已内嵌）和 tmp_url。
    logger.info("通过 API 拉取 Bitable 完整记录以下载附件: record_id=%s", record_id)
    api_fields = await bitable.get_record(record_id)

    # ── Step 3: 构建待下载附件列表 ──
    #    优先从 API 响应提取（含 url/tmp_url）；API 失败则回退到事件数据。
    all_attachments: list[tuple[str, dict]] = []  # [(field_cn, att_dict), ...]

    if api_fields:
        for field_cn in _att_fields:
            raw = api_fields.get(field_cn)
            # 如果 API 返回 field_id 作为 key，尝试通过映射获取
            if raw is None:
                field_id = field_name_to_id.get(field_cn, "")
                if field_id:
                    raw = api_fields.get(field_id)
            if isinstance(raw, list):
                valid = [a for a in raw if isinstance(a, dict) and a.get("file_token")]
                if valid:
                    has_url = any(a.get("url") or a.get("tmp_url") for a in valid)
                    logger.info(
                        "发现附件字段 %s: %d 个文件 (has_url=%s)",
                        field_cn, len(valid), has_url,
                    )
                    if not has_url:
                        logger.warning(
                            "API 返回的附件缺少 url/tmp_url，将回退到 Drive API: field=%s record_id=%s",
                            field_cn, record_id,
                        )
                    all_attachments.extend((field_cn, a) for a in valid)

    # 回退：API 未返回附件时，尝试从事件字段提取 file_token（仅含 file_token/name，需 Drive API）
    if not all_attachments and bitable_fields:
        logger.info("API 未返回附件，回退到事件数据: record_id=%s", record_id)
        for field_cn in _att_fields:
            raw = bitable_fields.get(field_cn)
            if isinstance(raw, list):
                attachments = _extract_attachments(raw)
            elif isinstance(raw, str) and raw.strip():
                try:
                    attachments = _extract_attachments(json.loads(raw))
                except (json.JSONDecodeError, TypeError):
                    logger.warning("附件字段 JSON 解析失败: field=%s raw=%s", field_cn, str(raw)[:100])
                    attachments = []
                if attachments:
                    logger.info(
                        "从事件数据发现附件: field=%s count=%d", field_cn, len(attachments),
                    )
                    all_attachments.extend((field_cn, a) for a in attachments)

    if not all_attachments:
        logger.info("Bitable 记录无附件: record_id=%s", record_id)
        return {"defect": [], "rectification": []}

    logger.info(
        "开始下载 Bitable 附件: record_id=%s count=%d api_fetched=%s",
        record_id, len(all_attachments), bool(api_fields),
    )

    # ── Step 4: 下载每个附件 ──
    saved: dict[str, list[str]] = {"defect": [], "rectification": []}

    for field_cn, att in all_attachments:
        file_token = att.get("file_token", "")
        file_name = att.get("name", "")
        download_url = att.get("url", "") or att.get("tmp_url", "")

        logger.info(
            "下载附件: field=%s file_token=%s name=%s has_presigned_url=%s",
            field_cn, file_token, file_name, bool(download_url),
        )

        data: bytes | None = None

        # 策略1: 优先用 Bitable API 返回的预签名 url（内部处理 auth/no-auth 重试 + 内容校验）
        if download_url:
            try:
                data = await bitable.download_attachment_from_url(download_url)
            except Exception:
                logger.exception(
                    "预签名 URL 下载异常: file_token=%s url=%s...",
                    file_token, download_url[:120],
                )

        # 策略2: 回退 — file_token + 手工构建 extra → Drive API
        if not data and file_token:
            try:
                extra: str | None = None
                field_id = field_name_to_id.get(field_cn, "")
                if field_id:
                    extra = _build_attachment_extra(
                        bitable.table_id, record_id, field_id, file_token,
                    )
                else:
                    logger.warning(
                        "无法找到字段 ID: field_cn=%s, 将不带 extra 尝试下载", field_cn,
                    )
                data = await bitable.download_attachment(file_token, extra=extra)
            except Exception:
                logger.exception(
                    "Drive API 下载异常: file_token=%s extra=%s",
                    file_token, bool(extra),
                )

        if not data:
            logger.error(
                "附件下载失败(所有策略耗尽): file_token=%s name=%s field=%s",
                file_token, file_name, field_cn,
            )
            continue

        # ── 保存到本地 ──
        try:
            safe_name = f"hazard_{hazard_id}_{file_token[:12]}_{file_name}"
            file_path = os.path.join(upload_dir, safe_name).replace("\\", "/")
            with open(file_path, "wb") as f:
                f.write(data)

            if field_cn == "整改后图片":
                saved["rectification"].append(file_path)
            else:
                saved["defect"].append(file_path)
            logger.info("附件已保存: %s (%d bytes)", file_path, len(data))
        except Exception:
            logger.exception("附件保存失败: name=%s", file_name)

    logger.info(
        "Bitable 附件下载完成: record_id=%s defect=%d rectification=%d",
        record_id, len(saved["defect"]), len(saved["rectification"]),
    )
    return saved


async def _create_hazard_from_bitable(
    record_id: str,
    bitable_fields: dict[str, Any],
) -> Any | None:
    """从 Bitable 记录创建 HazardReport，执行 AI 脚本，回写结果。

    采用 bot_handler.py 验证过的 commit-after-each-step 模式：
    create → commit → upload photos → commit → AI → commit → writeback。
    每一步变更立即持久化，确保后续步骤读取到最新状态。
    """
    from sqlalchemy import select, text, update
    from sqlalchemy.exc import IntegrityError

    from app.core.database import async_session_factory
    from app.modules.safety.models import HazardReport
    from app.modules.safety.schemas import HazardReportCreate
    from app.modules.safety.service import SafetyService

    # ── 阶段追踪（用于异常时精确定位失败步骤）──
    _stage = ""

    # 0. PostgreSQL 咨询锁：防止并发创建同一 feishu_record_id 的重复记录。
    #    Redis 去重/互斥锁在 Redis 不可用时静默失效，咨询锁作为 DB 级兜底。
    #    ⚠️ 关键：必须在显式事务中操作，因为 autocommit 模式下每次 session.execute()
    #    可能使用不同的连接池连接（pool_size=10），导致 advisory lock 失效。
    #    显式事务 (session.begin()) 保证所有操作都在同一连接上执行。
    _stage = "acquire_advisory_lock"
    session = async_session_factory()
    _lock_id = _compute_advisory_lock_id(record_id)
    _lock_transaction = None  # 保存事务引用，用于后续 rollback
    try:
        # 显式开启事务，将 session 绑定到单一连接
        _lock_transaction = await session.begin()
        # 先非阻塞尝试，快速检测冲突
        result = await session.execute(
            text("SELECT pg_try_advisory_lock(:id)"), {"id": _lock_id}
        )
        acquired = result.scalar()
        if not acquired:
            # 锁被占用 → 另一个创建正在进行 → 阻塞等待（最多 120s）
            logger.info(
                "advisory lock 竞争: record_id=%s lock_id=%s，等待中...",
                record_id, _lock_id,
            )
            _debug_log(
                f"ADVISORY_LOCK_WAIT: record_id={record_id} lock_id={_lock_id}"
            )
            await session.execute(
                text("SET LOCAL lock_timeout = '120s'; SELECT pg_advisory_lock(:id)"),
                {"id": _lock_id},
            )
            logger.info(
                "advisory lock 获取成功（等待后）: record_id=%s", record_id
            )
            # 锁已获取 → 检查前一个创建者是否已完成（同一连接、同一事务内查询）
            existing_after_wait = await session.execute(
                select(HazardReport).where(
                    HazardReport.feishu_record_id == record_id,
                    HazardReport.is_deleted == False,  # noqa: E712
                )
            )
            if existing_after_wait.scalar_one_or_none():
                logger.info(
                    "advisory lock 获取后发现记录已存在，跳过创建: record_id=%s", record_id
                )
                _debug_log(
                    f"ADVISORY_LOCK_SKIP: record_id={record_id} — 前一个创建已完成"
                )
                await _lock_transaction.rollback()
                await session.close()
                return None

        # 事务中检查：当前是否已有记录（非阻塞路径的重复检查）
        existing = await session.execute(
            select(HazardReport).where(
                HazardReport.feishu_record_id == record_id,
                HazardReport.is_deleted == False,  # noqa: E712
            )
        )
        if existing.scalar_one_or_none():
            logger.info(
                "advisory lock 获取后发现记录已存在（非竞争路径），跳过: record_id=%s", record_id
            )
            _debug_log(
                f"ADVISORY_LOCK_SKIP_FAST: record_id={record_id} — 记录已存在"
            )
            await _lock_transaction.rollback()
            await session.close()
            return None

        # 记录不存在 → 提交事务（释放锁，连接归还池）
        # 之后依赖 partial unique index on feishu_record_id 做最终兜底
        await _lock_transaction.commit()
    except Exception:
        logger.exception(
            "advisory lock 获取失败，降级继续（依赖 unique index 兜底）: record_id=%s",
            record_id,
        )
        # 清理事务和 session
        if _lock_transaction is not None:
            try:
                await _lock_transaction.rollback()
            except Exception:
                pass
        try:
            await session.close()
        except Exception:
            pass
        session = async_session_factory()

    # 1. 字段映射
    _stage = "map_fields"
    mapped = _map_bitable_fields(bitable_fields)
    mapped.setdefault("discovered_at", datetime.now(tz=UTC))

    # 2. 创建 HazardReport（不含附件字段，参照 bot_handler 模式）
    try:
        # 2.1 检查人员身份解析 — 统一使用 _resolve_person
        _stage = "resolve_inspector"
        inspector_raw = bitable_fields.get("检查人员")
        _debug_log(
            f"CREATE_INSPECTOR_RAW: record_id={record_id} "
            f"raw={str(inspector_raw)[:200]} mapped_name={mapped.get('discovered_by_name')}"
        )
        inspector_uuid, inspector_open_id, inspector_name = await _resolve_person(
            session,
            inspector_raw,
            bt_field_label="检查人员",
            existing_name=mapped.get("discovered_by_name"),
        )
        _debug_log(
            f"CREATE_INSPECTOR_RESOLVED: record_id={record_id} "
            f"uuid={inspector_uuid} name={inspector_name} open_id={inspector_open_id}"
        )
        if inspector_uuid:
            mapped["discovered_by"] = inspector_uuid
        # 只在解析出非 fallback 名称时才写入；不写入"飞书用户"以保留后续自动判定机会
        if inspector_name and inspector_name != "飞书用户":
            mapped["discovered_by_name"] = inspector_name
        _debug_log(
            f"CREATE_INSPECTOR_FINAL: record_id={record_id} "
            f"discovered_by_name={mapped.get('discovered_by_name')} discovered_by={mapped.get('discovered_by')}"
        )

        # 2.2 责任人身份解析 — 统一使用 _resolve_person
        _stage = "resolve_responsible"
        resp_uuid, resp_open_id, resp_name = await _resolve_person(
            session,
            bitable_fields.get("整改责任人"),
            bt_field_label="整改责任人",
            existing_name=mapped.get("rectification_responsible_person_name"),
        )
        if resp_name and resp_name != "飞书用户":
            mapped["rectification_responsible_person_name"] = resp_name
        # 注意：不写 elif fallback —— "飞书用户"无意义，留空让自动判定逻辑运行
        if resp_uuid:
            mapped["rectification_responsible_person"] = resp_uuid

        service = SafetyService(session)
        photo_fields = {"defect_photos", "rectification_photos"}
        create_data = {
            k: v for k, v in mapped.items()
            if k in HazardReportCreate.model_fields and k not in photo_fields
        }
        logger.info(
            "🔍 CREATE 即将入库: record_id=%s create_data keys=%s inspector_name=%r resp_name=%r",
            record_id, list(create_data.keys()),
            create_data.get("discovered_by_name"),
            create_data.get("rectification_responsible_person_name"),
        )
        logger.info(
            "🔍 CREATE create_data 详情: record_id=%s data=%s",
            record_id,
            {k: str(v)[:200] for k, v in create_data.items()},
        )
        _stage = "create_hazard_validate"
        data = HazardReportCreate(**create_data)
        _stage = "create_hazard_service"
        item = await service.hazard.create_hazard(data, auto_run_ai=False)
        item.feishu_record_id = record_id
        _stage = "create_hazard_commit"
        await session.flush()
        # 匹配 bot_handler: 创建后立即 commit（避免后续 AI 步骤读取到未提交的数据）
        try:
            await session.commit()
        except IntegrityError:
            # 并发 INSERT 触发了 feishu_record_id 部分唯一索引冲突
            # → 另一个事件处理者已先提交，回滚当前事务并获取已有记录
            await session.rollback()
            logger.warning(
                "feishu_record_id 唯一约束冲突（并发创建），获取已有记录: record_id=%s",
                record_id,
            )
            _debug_log(
                f"CREATE_UNIQUE_CONFLICT: record_id={record_id} — 并发创建，回退获取已有记录"
            )
            stmt = select(HazardReport).where(
                HazardReport.feishu_record_id == record_id,
                HazardReport.is_deleted == False,  # noqa: E712
            )
            result = await session.execute(stmt)
            existing_item = result.scalar_one_or_none()
            if existing_item:
                logger.info(
                    "唯一约束冲突后获取到已有记录: record_id=%s hazard_id=%s hazard_no=%s",
                    record_id, existing_item.id, existing_item.hazard_no,
                )
                return existing_item
            # 极端情况：冲突但查不到记录（可能已被并发删除）
            logger.error(
                "唯一约束冲突但查不到已有记录，放弃创建: record_id=%s", record_id
            )
            return None
        logger.info(
            "Bitable 隐患已创建: record_id=%s hazard_id=%s hazard_no=%s ai_progress=%s",
            record_id, item.id, item.hazard_no, item.ai_node_progress,
        )

        # 2.5 责任部门 → 责任人自动判定（有部门但无有效责任人时自动查询部门负责人）
        _resolved_leader_open_id: str | None = None  # identity 侧 open_id（仅作 fallback）
        _resolved_leader_user_id: str | None = None  # employee user_id，用于查 Bitable open_id
        _resp_name = (item.rectification_responsible_person_name or "").strip()
        if item.department and (
            not _resp_name
            or _resp_name == "飞书用户"
            or item.department in DEPARTMENT_CONFIG
        ):
            try:
                from app.modules.safety.feishu.identity_resolver import IdentityResolver
                resolver = IdentityResolver(session)
                person = await resolver.resolve_department_leader(item.department)
                if person and person.name:
                    stmt_update_leader = (
                        update(HazardReport)
                        .where(HazardReport.id == item.id)
                        .values(
                            rectification_responsible_person=_uuid.UUID(person.id) if person.id else None,
                            rectification_responsible_person_name=person.name,
                        )
                    )
                    await session.execute(stmt_update_leader)
                    await session.commit()
                    item.rectification_responsible_person_name = person.name
                    _resolved_leader_open_id = person.open_id
                    _resolved_leader_user_id = person.user_id
                    logger.info(
                        "责任人自动判定: dept=%s leader=%s uuid=%s open_id=%s user_id=%s",
                        item.department, person.name, person.id, person.open_id, person.user_id,
                    )
            except Exception:
                logger.exception("责任人自动判定失败: dept=%s", item.department)

        # 3. 下载附件到本地 → 直接 SET clean file paths（不 append，避免 Bitable attachment 对象残留）
        _stage = "download_attachments"
        saved = await _download_and_save_attachments(
            SafetyBitableClient(), bitable_fields, str(item.id), record_id=record_id,
        )
        if saved.get("defect") or saved.get("rectification"):
            import json as _json

            stmt_photos = update(HazardReport).where(HazardReport.id == item.id)
            photo_updates: dict[str, Any] = {}
            if saved.get("defect"):
                photo_updates["defect_photos"] = _json.dumps(
                    [p.replace("\\", "/") for p in saved["defect"]], ensure_ascii=False,
                )
            if saved.get("rectification"):
                photo_updates["rectification_photos"] = _json.dumps(
                    [p.replace("\\", "/") for p in saved["rectification"]], ensure_ascii=False,
                )
            if photo_updates:
                await session.execute(stmt_photos.values(**photo_updates))
                await session.commit()
                # 刷新 item 属性
                for k, v in photo_updates.items():
                    setattr(item, k, v)
            logger.info(
                "附件已入库(SET模式): hazard_id=%s defect=%d rectification=%d",
                item.id, len(saved.get("defect", [])), len(saved.get("rectification", [])),
            )

        # 4. 重新获取最新状态（含附件路径），执行 AI 脚本
        #    无条件执行 — 有照片走视觉模型，无照片走纯文本模型
        #    不跳过审核流程
        stmt = select(HazardReport).where(HazardReport.id == item.id)
        result = await session.execute(stmt)
        item = result.scalar_one()

        ai_summary_parts: list[str] = []
        advice_parts: list[str] = []

        if item:
            try:
                # AI 隐患识别（插件：含 few-shot prompt + 规则引擎 + 整改建议）
                _stage = "run_ai_script"
                item = await service.hazard.run_hazard_ai_script(item.id, 1)
                if item and not item.ai_error_message:
                    ai_summary_parts.append(
                        f"分类:{HAZARD_TYPE_REVERSE.get(item.hazard_type, item.hazard_type)}"
                    )
                    ai_summary_parts.append(
                        f"等级:{HAZARD_LEVEL_REVERSE.get(item.hazard_level, item.hazard_level)}"
                    )
                    if item.hazard_category:
                        ai_summary_parts.append(f"类别:{HAZARD_CATEGORY_REVERSE.get(item.hazard_category, item.hazard_category)}")
                    if item.key_defect:
                        ai_summary_parts.append(f"重点缺陷:{item.key_defect}")
                    if item.corrective_preventive_measures:
                        advice_parts.append(item.corrective_preventive_measures)
                else:
                    logger.warning(
                        "AI 隐患识别失败: hazard_id=%s error=%s",
                        item.id, getattr(item, 'ai_error_message', 'unknown'),
                    )
            except Exception:
                logger.exception("AI 脚本执行异常: hazard_id=%s", item.id)

            await session.commit()
            logger.info(
                "AI 脚本执行完成: hazard_id=%s overall_status=%s ai_error=%s ai_progress=%s",
                item.id, item.overall_status, bool(item.ai_error_message), item.ai_node_progress,
            )

        # 5. 整改期限：自动计算（discovered_at + 2 个月）并写入 DB
        from datetime import timedelta

        if not item.deadline:
            base_date = item.discovered_at or datetime.now(tz=UTC)
            computed_deadline = base_date + timedelta(days=60)
            stmt_deadline = (
                update(HazardReport)
                .where(HazardReport.id == item.id)
                .values(deadline=computed_deadline)
            )
            await session.execute(stmt_deadline)
            await session.commit()
            item.deadline = computed_deadline
            logger.info("整改期限自动计算: hazard_id=%s deadline=%s", item.id, computed_deadline)

        # 6. 回写 Bitable（隐患编号 + AI 结果 + 整改期限 + 责任人）
        bitable = SafetyBitableClient()
        writeback: dict[str, Any] = {
            "隐患编号": item.hazard_no,
        }
        # 责任人 → Bitable person 字段
        # 使用 BitableIdMapper 将 identity user_id 转换为 Bitable 侧的 open_id，
        # 解决安全应用与全局应用 open_id 命名空间不一致的问题。
        from app.modules.safety.feishu.bitable_id_mapper import get_bitable_person_value

        responsible_person_value: list[dict] | None = None
        if _resolved_leader_user_id or _resolved_leader_open_id:
            # 自动判定：通过 user_id 查 Bitable open_id
            # ⚠️ 不使用 fallback_to_identity——全局应用 open_id 与安全应用 Bitable
            # 的 open_id 命名空间不同，直接回退会导致 UserFieldConvFail
            responsible_person_value = get_bitable_person_value(
                user_id=_resolved_leader_user_id,
            )
            if responsible_person_value:
                logger.info(
                    "责任人已加入 Bitable 回写(自动判定): name=%s user_id=%s bitable_id=%s",
                    getattr(item, 'rectification_responsible_person_name', '?'),
                    _resolved_leader_user_id, responsible_person_value[0]["id"],
                )
        elif item.rectification_responsible_person_name:
            # 从 Bitable 直接填写 → 解析 identity 再查 Bitable open_id
            try:
                from app.modules.safety.feishu.identity_resolver import IdentityResolver
                resolver2 = IdentityResolver(session)
                person2 = await resolver2.resolve_by_name(
                    item.rectification_responsible_person_name,
                    department_hint=item.department,
                )
                if person2:
                    responsible_person_value = get_bitable_person_value(
                        user_id=person2.user_id,
                        name=person2.name,
                    )
                    if responsible_person_value:
                        logger.info(
                            "责任人 Bitable open_id 解析成功: name=%s user_id=%s bitable_id=%s",
                            item.rectification_responsible_person_name,
                            person2.user_id, responsible_person_value[0]["id"],
                        )
                    else:
                        logger.warning(
                            "责任人 Bitable open_id 未找到: name=%s user_id=%s (identity open_id=%s)",
                            item.rectification_responsible_person_name,
                            person2.user_id, person2.open_id,
                        )
                else:
                    logger.warning(
                        "责任人 identity 解析失败(未在 identity.users 中找到): name=%s dept=%s",
                        item.rectification_responsible_person_name, item.department,
                    )
            except Exception:
                logger.exception(
                    "责任人 open_id 解析异常: name=%s",
                    item.rectification_responsible_person_name,
                )
        if responsible_person_value:
            writeback["整改责任人"] = responsible_person_value
        else:
            logger.warning(
                "责任人未回写(无 Bitable open_id): hazard_no=%s name=%s user_id=%s identity_open_id=%s",
                item.hazard_no,
                getattr(item, 'rectification_responsible_person_name', None),
                _resolved_leader_user_id,
                _resolved_leader_open_id,
            )
        # 整改期限 → Bitable（毫秒时间戳）
        if item.deadline:
            writeback["整改期限"] = _datetime_to_ms(item.deadline)
        # AI 识别结果 → 回写到 Bitable 对应的独立 AI 字段
        # 注意: select/multi_select 字段需要匹配 Bitable 字段类型（multi_select 须为数组）
        if item.hazard_type:
            writeback["隐患分类（AI）"] = _format_bitable_select_value(
                "隐患分类（AI）", HAZARD_TYPE_REVERSE.get(item.hazard_type, item.hazard_type),
            )
        if item.hazard_level:
            writeback["隐患级别（AI）"] = _format_bitable_select_value(
                "隐患级别（AI）", HAZARD_LEVEL_REVERSE.get(item.hazard_level, item.hazard_level),
            )
        if item.hazard_category:
            writeback["隐患类别（AI）"] = _format_bitable_select_value(
                "隐患类别（AI）", HAZARD_CATEGORY_REVERSE.get(item.hazard_category, item.hazard_category),
            )
        if item.key_defect:
            writeback["隐患描述（AI）"] = item.key_defect
        if item.major_hazard_basis:
            writeback["隐患判定依据（AI）"] = item.major_hazard_basis
        # AI 整改建议 → 回写到「整改建议（AI）」
        if advice_parts:
            writeback["整改建议（AI）"] = "；".join(advice_parts)

        _stage = "writeback_bitable"
        await _set_sync_ignore(record_id, ttl=30)
        ok = await bitable.update_record(record_id, writeback)
        if not ok:
            raise RuntimeError(
                f"Bitable 回写失败: record_id={record_id} "
                f"fields={list(writeback.keys())}"
            )

        # 7. 异步通知责任人整改
        import asyncio as _asyncio

        _debug_log(
            f"CREATE_DISPATCH_RECTIFY: record_id={record_id} hazard_no={item.hazard_no} "
            f"resp_name={item.rectification_responsible_person_name} dept={item.department}"
        )
        _asyncio.create_task(_send_rectification_notification(item))

        _debug_log(
            f"CREATE_DONE: record_id={record_id} hazard_no={item.hazard_no} "
            f"hazard_id={item.id} status={item.overall_status}"
        )
        return item

    except Exception as exc:
        # 截取异常类名 + 前 80 字符的消息，用于 Bitable 回写诊断
        exc_cls = type(exc).__name__
        exc_msg = str(exc)[:80].replace("\n", " ").replace("\r", "")
        logger.exception(
            "Bitable 创建隐患失败: record_id=%s stage=%s exc=%s: %s",
            record_id, _stage or "unknown", exc_cls, exc_msg,
        )
        await session.rollback()

        # 回写失败状态（不写"同步状态"字段，因为 Bitable 中不存在该字段）
        try:
            bitable = SafetyBitableClient()
            await _set_sync_ignore(record_id, ttl=30)
            error_label = f"ERROR:{_stage}:{exc_cls}:{record_id[:10]}"
            ok2 = await bitable.update_record(record_id, {"隐患编号": error_label})
            if not ok2:
                logger.error(
                    "Bitable 错误回写失败(update_record=False): record_id=%s",
                    record_id,
                )
        except Exception:
            logger.exception("回写失败状态异常: record_id=%s", record_id)
        return None
    finally:
        await session.close()


def _compute_rectification_status(
    v1: str | None,
    v2: str | None,
    v3: str | None,
    hazard_level: str | None,
) -> str | None:
    """根据三级复核状态计算整体整改状态。

    与 SafetyService.verify_level 的状态机逻辑保持一致：
      - 一般隐患：AI初审 → L1（部门负责人）→ L3（检查人员），L2 自动设为「无需复核」
      - 较大/重大隐患：AI初审 → L1 → L2（分管领导）→ L3
      - 任一驳回 → rejected
      - L3 通过 → closed
      - L2 通过 或 L2 无需复核 → level2_approved（已通过 L2 阶段，可进入 L3）
      - L1 通过 → level1_approved
    """
    if v1 == "rejected" or v2 == "rejected" or v3 == "rejected":
        return "rejected"
    if v3 == "approved":
        return "closed"
    # L2 已通过 或 无需复核 → 等效于已通过 L2 阶段
    if v2 == "approved" or v2 == "no_review_needed":
        return "level2_approved"
    if v1 == "approved":
        return "level1_approved"
    return None


async def _update_hazard_from_bitable(
    record_id: str,
    hazard: Any,
    bitable_fields: dict[str, Any],
) -> Any | None:
    """Bitable 记录更新 → 同步到已有 HazardReport。"""
    from app.core.database import async_session_factory
    from app.modules.safety.service import SafetyService

    mapped = _map_bitable_fields(bitable_fields)
    # 过滤掉不应更新的系统字段。附件字段需特殊处理（下载 → 本地路径），不能直接写入 Bitable 对象
    skip_fields = {"hazard_no", "feishu_record_id"}
    # 空字符串视为未提供（Bitable API 可能返回 [] → ""），防御性拦截
    update_data = {k: v for k, v in mapped.items() if k not in skip_fields and v is not None and v != ""}
    logger.info(
        "📝 UPDATE mapped: record_id=%s bitable_keys=%s mapped_keys=%s update_keys=%s",
        record_id,
        list(bitable_fields.keys()),
        list(mapped.keys()),
        list(update_data.keys()),
    )
    if "rectification_reply" in bitable_fields:
        logger.info(
            "📝 整改回复内容: record_id=%s raw_type=%s raw_preview=%s",
            record_id,
            type(bitable_fields.get("纠正预防措施")).__name__,
            str(bitable_fields.get("纠正预防措施"))[:200],
        )
    if "rectification_photos" in mapped:
        logger.info(
            "📝 rectification_photos in mapped: record_id=%s preview=%s",
            record_id, str(mapped.get("rectification_photos"))[:200],
        )

    # ── 附件字段单独处理：下载 → 本地路径（与 CREATE 流程一致）──
    photo_updates: dict[str, str] = {}  # field_name → JSON string of local paths
    _bt_photo_fields = {
        k: v for k, v in bitable_fields.items()
        if k in ("缺陷图片", "整改后图片") and v
    }
    if _bt_photo_fields:
        try:
            saved = await _download_and_save_attachments(
                SafetyBitableClient(), _bt_photo_fields, str(hazard.id), record_id=record_id,
            )
            import json as _json

            # 缺陷图片：按文件名去重后合并（防止重复同步导致照片重复）
            if saved.get("defect"):
                existing_defect: list[str] = []
                if getattr(hazard, "defect_photos", None):
                    try:
                        existing_defect = _json.loads(hazard.defect_photos)
                        if not isinstance(existing_defect, list):
                            existing_defect = []
                    except (_json.JSONDecodeError, TypeError):
                        existing_defect = []
                # 按文件名去重：只追加新文件
                existing_basenames = {
                    os.path.basename(p.replace("\\", "/")) for p in existing_defect
                }
                new_paths = [p.replace("\\", "/") for p in saved["defect"]]
                unique_new = [
                    p for p in new_paths
                    if os.path.basename(p) not in existing_basenames
                ]
                if unique_new:
                    merged_defect = existing_defect + unique_new
                    photo_updates["defect_photos"] = _json.dumps(merged_defect, ensure_ascii=False)
                    logger.info(
                        "📸 defect 照片去重: record_id=%s existing=%d downloaded=%d new=%d merged=%d",
                        record_id, len(existing_defect), len(new_paths), len(unique_new), len(merged_defect),
                    )
                else:
                    logger.info(
                        "📸 defect 照片全部已存在，跳过: record_id=%s count=%d",
                        record_id, len(existing_defect),
                    )
                update_data.pop("defect_photos", None)  # 移除 mapped 中的原始对象

            # 整改图片：按文件名去重后合并
            if saved.get("rectification"):
                existing_rect: list[str] = []
                if getattr(hazard, "rectification_photos", None):
                    try:
                        existing_rect = _json.loads(hazard.rectification_photos)
                        if not isinstance(existing_rect, list):
                            existing_rect = []
                    except (_json.JSONDecodeError, TypeError):
                        existing_rect = []
                existing_basenames = {
                    os.path.basename(p.replace("\\", "/")) for p in existing_rect
                }
                new_paths = [p.replace("\\", "/") for p in saved["rectification"]]
                unique_new = [
                    p for p in new_paths
                    if os.path.basename(p) not in existing_basenames
                ]
                if unique_new:
                    merged_rect = existing_rect + unique_new
                    photo_updates["rectification_photos"] = _json.dumps(merged_rect, ensure_ascii=False)
                    logger.info(
                        "📸 rectification 照片去重: record_id=%s existing=%d downloaded=%d new=%d merged=%d",
                        record_id, len(existing_rect), len(new_paths), len(unique_new), len(merged_rect),
                    )
                else:
                    logger.info(
                        "📸 rectification 照片全部已存在，跳过: record_id=%s count=%d",
                        record_id, len(existing_rect),
                    )
                update_data.pop("rectification_photos", None)  # 移除 mapped 中的原始对象

            if photo_updates:
                logger.info(
                    "📸 UPDATE 附件已下载: hazard_id=%s defect=%d rectification=%d",
                    hazard.id, len(saved.get("defect", [])), len(saved.get("rectification", [])),
                )
        except Exception:
            logger.exception("UPDATE 附件下载失败: record_id=%s hazard_id=%s", record_id, hazard.id)
            # ⚠️ 下载失败时必须清除 update_data 中的原始 Bitable attachment 对象，
            # 否则 [{"file_token":"", "name":"xxx.jpg"}] 会被写入 DB，前端无法渲染。
            update_data.pop("defect_photos", None)
            update_data.pop("rectification_photos", None)
    else:
        # 无新附件上传：移除 mapped 中可能残留的空/原始附件对象
        update_data.pop("defect_photos", None)
        update_data.pop("rectification_photos", None)

    logger.info(
        "📝 UPDATE mapped: record_id=%s current_names=(inspector=%r, resp=%r) "
        "mapped_names=(inspector=%r, resp=%r) bitable_has_inspector=%s bitable_has_resp=%s",
        record_id,
        getattr(hazard, "discovered_by_name", None),
        getattr(hazard, "rectification_responsible_person_name", None),
        mapped.get("discovered_by_name"),
        mapped.get("rectification_responsible_person_name"),
        "检查人员" in bitable_fields,
        "整改责任人" in bitable_fields,
    )

    # 身份解析：统一使用 _resolve_person（支持 id → email → name 三层回退）
    session = async_session_factory()
    try:
        # 检查人员
        inspector_uuid, _, inspector_name = await _resolve_person(
            session,
            bitable_fields.get("检查人员"),
            bt_field_label="检查人员",
            existing_name=getattr(hazard, "discovered_by_name", None),
        )
        if inspector_uuid:
            update_data["discovered_by"] = inspector_uuid
        if inspector_name and inspector_name != "飞书用户" and (
            "discovered_by_name" not in update_data or not update_data.get("discovered_by_name")
        ):
            update_data["discovered_by_name"] = inspector_name

        # 责任人
        resp_uuid, _, resp_name = await _resolve_person(
            session,
            bitable_fields.get("整改责任人"),
            bt_field_label="整改责任人",
            existing_name=getattr(hazard, "rectification_responsible_person_name", None),
        )
        if resp_uuid:
            update_data["rectification_responsible_person"] = resp_uuid
        if resp_name and resp_name != "飞书用户" and (
            "rectification_responsible_person_name" not in update_data
            or not update_data.get("rectification_responsible_person_name")
        ):
            update_data["rectification_responsible_person_name"] = resp_name
    finally:
        await session.close()

    # 根据三级复核状态自动计算整体整改状态（与 SafetyService.verify_level 状态机一致）
    old_rectification_status = getattr(hazard, "rectification_status", None)

    # 检测整改回复提交：有整改完成时间 + 当前状态为 pending/in_progress/rejected → 转为 replied
    _debug_log(
        f"UPDATE_STATUS_CHECK: record_id={record_id} hazard_no={getattr(hazard, 'hazard_no', '?')} "
        f"old_status={old_rectification_status} "
        f"has_completion_date={'actual_completion_date' in update_data} "
        f"has_reply={'rectification_reply' in update_data} "
        f"status_in_update={'rectification_status' in update_data} "
        f"update_keys={list(update_data.keys())}"
    )
    if (
        "actual_completion_date" in update_data
        and update_data.get("actual_completion_date")
        and old_rectification_status in ("pending", "in_progress", "rejected")
        and "rectification_status" not in update_data
    ):
        update_data["rectification_status"] = "ai_reviewing"
        _debug_log(
            f"UPDATE_STATUS_SET: record_id={record_id} hazard_no={getattr(hazard, 'hazard_no', '?')} "
            f"old_status={old_rectification_status} → ai_reviewing"
        )
        logger.info(
            "整改回复已提交，状态自动转换: record_id=%s %s → ai_reviewing",
            record_id, old_rectification_status,
            record_id,
        )
    else:
        _debug_log(
            f"UPDATE_STATUS_SKIP: record_id={record_id} — 不满足 replied 转换条件 "
            f"(completion_date_in_data={'actual_completion_date' in update_data}, "
            f"old_in_allowed={old_rectification_status in ('pending', 'in_progress', 'rejected')}, "
            f"status_explicit={'rectification_status' in update_data})"
        )

    if any(k in mapped for k in ("verify_level_1_status", "verify_level_2_status", "verify_level_3_status")):
        v1 = mapped.get("verify_level_1_status", getattr(hazard, "verify_level_1_status", None))
        v2 = mapped.get("verify_level_2_status", getattr(hazard, "verify_level_2_status", None))
        v3 = mapped.get("verify_level_3_status", getattr(hazard, "verify_level_3_status", None))
        hl = mapped.get("hazard_level", getattr(hazard, "hazard_level", None))
        computed_status = _compute_rectification_status(v1, v2, v3, hl)
        _debug_log(
            f"UPDATE_COMPUTE_STATUS: record_id={record_id} hazard_no={getattr(hazard, 'hazard_no', '?')} "
            f"v1={v1} v2={v2} v3={v3} level={hl} old={old_rectification_status} computed={computed_status} "
            f"mapped_verify_keys={[k for k in mapped if 'verify' in k]}"
        )
        # 防御性关卡：AI 初审必须已完成，否则不允许从 Bitable 同步复核状态变更。
        # 防止在 AI 审核未通过/未完成时，通过直接修改 Bitable 审批字段绕过 AI 初审流程。
        ai_status = getattr(hazard, "ai_review_status", None)
        if computed_status and computed_status != old_rectification_status:
            if ai_status != "completed":
                logger.warning(
                    "Bitable 复核状态变更被拒绝: record_id=%s AI 初审未完成 (ai_review_status=%s)，"
                    "不允许同步复核状态 (v1=%s v2=%s v3=%s computed=%s)",
                    record_id, ai_status, v1, v2, v3, computed_status,
                )
            else:
                update_data["rectification_status"] = computed_status
                _debug_log(
                    f"UPDATE_COMPUTE_APPLY: record_id={record_id} hazard_no={getattr(hazard, 'hazard_no', '?')} "
                    f"{old_rectification_status} → {computed_status}"
                )
                if computed_status == "closed":
                    update_data["status"] = "closed"
                logger.info(
                    "复核状态自动计算: record_id=%s v1=%s v2=%s v3=%s level=%s current=%s → %s",
                    record_id, v1, v2, v3, hl, old_rectification_status, computed_status,
                )
        else:
            _debug_log(
                f"UPDATE_COMPUTE_SKIP: record_id={record_id} hazard_no={getattr(hazard, 'hazard_no', '?')} "
                f"computed={computed_status} old={old_rectification_status} "
                f"equal={computed_status == old_rectification_status}"
            )
    if not update_data and not photo_updates:
        logger.info("📝 UPDATE 跳过 (无变更): record_id=%s", record_id)
        return hazard

    logger.info(
        "📝 UPDATE 即将执行: record_id=%s update_data keys=%s photo_updates=%s "
        "inspector_name=%r resp_name=%r has_rectification_reply=%s rectification_reply_len=%d",
        record_id, list(update_data.keys()), list(photo_updates.keys()),
        update_data.get("discovered_by_name"),
        update_data.get("rectification_responsible_person_name"),
        "rectification_reply" in update_data,
        len(update_data.get("rectification_reply", "") or ""),
    )

    session = async_session_factory()
    try:
        service = SafetyService(session)
        # 合并 photo_updates 到 update_data 用于 DB 写入
        if photo_updates:
            update_data.update(photo_updates)
        _updated = await service.hazard.update_hazard(hazard.id, type(
            "Update", (), {"model_dump": lambda self=None, **kw: update_data},
        )())
        # 手动更新内存对象

        for field, value in update_data.items():
            if hasattr(hazard, field):
                setattr(hazard, field, value)
        await session.flush()

        # 更新完成，不写"同步状态"字段（Bitable 中不存在该字段）
        await _set_sync_ignore(record_id, ttl=30)

        await session.commit()
        logger.info("Bitable→平台更新完成: record_id=%s hazard_id=%s", record_id, hazard.id)

        # ── 状态变更后异步发送飞书复核通知 ──
        new_status = update_data.get("rectification_status")
        _debug_log(
            f"UPDATE_NOTIFY_CHECK: record_id={record_id} hazard_no={getattr(hazard, 'hazard_no', '?')} "
            f"new_status={new_status} old_status={old_rectification_status} "
            f"changed={new_status and new_status != old_rectification_status}"
        )
        if new_status and new_status != old_rectification_status:
            hl = update_data.get("hazard_level") or getattr(hazard, "hazard_level", None)
            _debug_log(
                f"UPDATE_NOTIFY_TRIGGER: record_id={record_id} hazard_no={getattr(hazard, 'hazard_no', '?')} "
                f"{old_rectification_status}→{new_status} level={hl}"
            )
            logger.info(
                "📬 状态变更触发通知: record_id=%s %s→%s level=%s hazard_no=%s",
                record_id, old_rectification_status, new_status, hl, hazard.hazard_no,
            )
            if new_status == "ai_reviewing":
                # AI 初审中 → 异步触发 AI 审查（不阻塞）
                _debug_log(
                    f"UPDATE_NOTIFY_DISPATCH: record_id={record_id} hazard_no={getattr(hazard, 'hazard_no', '?')} "
                    f"→ run_rectification_review(hazard)"
                )
                asyncio.create_task(service.hazard.run_rectification_review(hazard.id))
            elif new_status == "replied":
                _debug_log(
                    f"UPDATE_NOTIFY_DISPATCH: record_id={record_id} hazard_no={getattr(hazard, 'hazard_no', '?')} "
                    f"→ run_rectification_review(hazard)"
                )
                asyncio.create_task(service.hazard.run_rectification_review(hazard.id))
            elif new_status == "level1_approved":
                # 一般隐患：L2（分管领导）无需复核，自动设为「无需复核」并跳至 L3
                if getattr(hazard, "hazard_level", None) == "general":
                    asyncio.create_task(
                        _auto_skip_level2_for_general_hazard(hazard, record_id)
                    )
                else:
                    asyncio.create_task(_send_verify_notification(hazard, 2))
            elif new_status == "level2_approved":
                asyncio.create_task(_send_verify_notification(hazard, 3))

            # ── 回写整改状态到 Bitable（跳过 ai_reviewing 中间态，AI 完成后会同步最终状态）──
            if new_status != "ai_reviewing":
                try:
                    status_label = _STATUS_TO_BITABLE_LABEL.get(new_status, new_status)
                    _bt = SafetyBitableClient()
                    await _set_sync_ignore(record_id, ttl=30)
                    ok3 = await _bt.update_record(record_id, {"整改状态": status_label})
                    if not ok3:
                        logger.error(
                            "整改状态回写 Bitable 失败(update_record=False): record_id=%s status=%s",
                            record_id, new_status,
                        )
                    else:
                        logger.info(
                            "整改状态已回写 Bitable: record_id=%s status=%s label=%s",
                            record_id, new_status, status_label,
                        )
                except Exception:
                    logger.exception("整改状态回写 Bitable 失败: record_id=%s", record_id)

        return hazard

    except Exception:
        logger.exception("Bitable 更新隐患失败: record_id=%s", record_id)
        await session.rollback()
        return None
    finally:
        await session.close()


# ═══════════════════════════════════════════════════════════════
# 公开 API：平台 → Bitable 方向
# ═══════════════════════════════════════════════════════════════

async def push_hazard_to_bitable(hazard: Any) -> bool:
    """平台 HazardReport 更新后，将变更推送到 Bitable。

    在 SafetyService.update_hazard() 等写操作后调用。
    仅当 hazard.feishu_record_id 非空时执行。

    注意：
    - person 字段（责任人、检查人员）和 attachment 字段（缺陷图片、整改后图片）
      不在 _map_model_to_bitable 输出中，因此不会回写。person 字段在初次创建时
      （_create_hazard_from_bitable）通过 get_bitable_person_value() 设置。
    - _format_bitable_select_value 依赖 _field_type_cache 判断 multi_select vs single_select，
      调用前必须确保缓存已加载，否则 multi_select 字段会因纯文本格式而触发
      MultiSelectFieldConvFail (1254063)。
    """
    if not hazard.feishu_record_id:
        return False

    # 确保字段类型缓存已加载（_format_bitable_select_value 依赖此缓存）
    await _get_field_definitions(SafetyBitableClient())

    fields = _map_model_to_bitable(hazard)
    if not fields:
        return True

    bitable = SafetyBitableClient()
    await _set_sync_ignore(hazard.feishu_record_id, ttl=30)
    ok = await bitable.update_record(hazard.feishu_record_id, fields)
    if ok:
        logger.info("平台→Bitable 同步完成: hazard_id=%s record_id=%s", hazard.id, hazard.feishu_record_id)
    return ok


# ═══════════════════════════════════════════════════════════════
# 事件处理器
# ═══════════════════════════════════════════════════════════════
#
# 事件类型说明：
#   drive.file.bitable_record_changed_v1  记录级变更，payload 含 action (insert/update/delete)
#   drive.file.bitable_field_changed_v1   字段级变更，更细粒度
# 我们使用 record_changed_v1 为主，field_changed_v1 作为补充。

# Bitable 目标凭证（模块级缓存，避免每次 os.getenv）
_TARGET_FILE_TOKEN = os.getenv("SAFETY_FEISHU_BITABLE_APP_TOKEN", "")
_TARGET_TABLE_ID = os.getenv("SAFETY_FEISHU_BITABLE_HAZARD_TABLE_ID", "")

# field_id → field_name 缓存（用于解析 action_list 中的 after_value）
_field_name_cache: dict[str, str] | None = None
# field_name → {option_id: option_name} 缓存（用于将 after_value 中的选项ID转为显示名称）
_option_map_cache: dict[str, dict[str, str]] | None = None
# field_name → field_type 缓存
_field_type_cache: dict[str, int] | None = None

# 飞书 action_list action 映射
_ACTION_MAP: dict[str, str] = {
    "record_added": "insert",
    "record_edited": "update",
    "record_deleted": "delete",
}


async def _get_field_definitions(bitable: SafetyBitableClient) -> None:
    """加载字段定义（ID映射 + 类型 + 选项映射），惰性缓存。"""
    global _field_name_cache, _option_map_cache, _field_type_cache
    if _option_map_cache is not None and _field_type_cache is not None:
        return
    fields = await bitable.list_fields()
    _field_name_cache = {}
    _option_map_cache = {}
    _field_type_cache = {}
    for f in (fields or []):
        fid = f.get("field_id", "")
        fname = f.get("field_name", "")
        ftype = f.get("type", 0)
        if fid and fname:
            _field_name_cache[fid] = fname
        if fname and isinstance(ftype, int) and ftype > 0:
            _field_type_cache[fname] = ftype
        # 单选/多选字段：构建 option_id → option_name 映射
        if fname and ftype in (3, 4):
            opts: dict[str, str] = {}
            for opt in (f.get("property", {}) or {}).get("options", []) or []:
                oid = opt.get("id", "")
                oname = opt.get("name", "")
                if oid and oname:
                    opts[oid] = oname
            if opts:
                _option_map_cache[fname] = opts
    logger.info(
        "Bitable 字段定义已缓存: %d 个字段, %d 个有选项映射",
        len(_field_name_cache), len(_option_map_cache),
    )


async def _get_field_name_map(bitable: SafetyBitableClient) -> dict[str, str]:
    """获取 field_id → field_name 映射表（惰性缓存）。"""
    global _field_name_cache
    if _field_name_cache is not None:
        return _field_name_cache
    await _get_field_definitions(bitable)
    return _field_name_cache or {}


def _resolve_option_ids(
    raw: Any,
    opt_map: dict[str, str],
    ftype: int,
) -> Any:
    """将 select/multi_select 字段的选项 ID 解析为显示名称。

    - single_select (type=3): raw 是选项 ID 字符串 → 返回选项名称
    - multi_select (type=4): raw 是选项 ID 列表 → 返回选项名称列表
    - 未知 ID 保留原值
    """
    if not opt_map or ftype not in (3, 4):
        return raw
    if isinstance(raw, list):
        return [opt_map.get(str(v), v) for v in raw]
    if isinstance(raw, str) and raw in opt_map:
        return opt_map[raw]
    return raw


def _convert_after_value_to_fields(
    after_value: list[dict],
    field_map: dict[str, str],
) -> dict[str, Any]:
    """将飞书 action_list 的 after_value [{field_id, field_value}] 转为 {field_name: value}。

    处理特殊字段类型：
    - attachment: field_value 是 JSON 字符串，解析为 list[dict]
    - select/multi_select: 选项 ID → 选项名称（依赖 _option_map_cache / _field_type_cache）
    - 其他类型: field_value 已是正确的 Python 值
    """
    opt_map_cache = _option_map_cache or {}
    type_cache = _field_type_cache or {}

    result: dict[str, Any] = {}
    for item in (after_value or []):
        fid = item.get("field_id", "")
        fname = field_map.get(fid)
        if not fname:
            continue
        raw = item.get("field_value")
        # 尝试解析 JSON（attachment、multi_select 等复杂类型以 JSON 字符串存储）
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, (list, dict)):
                    raw = parsed
            except (json.JSONDecodeError, TypeError):
                pass
        # 将选项 ID 解析为显示名称
        raw = _resolve_option_ids(raw, opt_map_cache.get(fname, {}), type_cache.get(fname, 0))
        result[fname] = raw
    return result


def _extract_field_value(
    item: dict,
    field_id: str,
    field_map: dict[str, str],
) -> dict[str, Any]:
    """从 field_changed_v1 事件的单个 item 中提取字段值。

    与 _convert_after_value_to_fields 不同，field_changed 的 after_value
    是单字段值（非列表），且 item 中直接有 field_id 标识是哪个字段。

    Returns:
        {field_name: value} 单键字典，转换失败返回空字典。
    """
    if not field_id:
        return {}
    fname = field_map.get(field_id)
    if not fname:
        return {}

    raw = item.get("after_value")
    if raw is None:
        return {}

    # 尝试解析 JSON（attachment、multi_select 等以 JSON 字符串存储）
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, (list, dict)):
                raw = parsed
        except (json.JSONDecodeError, TypeError):
            pass

    # 将选项 ID 解析为显示名称
    opt_map_cache = _option_map_cache or {}
    type_cache = _field_type_cache or {}
    raw = _resolve_option_ids(raw, opt_map_cache.get(fname, {}), type_cache.get(fname, 0))

    return {fname: raw}


# ═══════════════════════════════════════════════════════════════
# 文档事件订阅（飞书要求必须先调用此 API，Bitable 事件才会推送）
# ═══════════════════════════════════════════════════════════════

async def ensure_bitable_subscribed() -> bool:
    """订阅多维表格云文档事件。

    飞书要求：在接收 Bitable 事件之前，必须先调用 /drive/v1/files/:file_token/subscribe
    订阅文档事件。此订阅持久存在于飞书侧，只需调用一次，但每次启动时重试无害。
    """
    if not _TARGET_FILE_TOKEN:
        logger.warning("Bitable file_token 未配置，跳过文档事件订阅")
        return False

    try:
        import httpx

        from app.modules.safety.feishu.client import get_safety_tenant_token

        token = await get_safety_tenant_token()
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                f"https://open.feishu.cn/open-apis/drive/v1/files/{_TARGET_FILE_TOKEN}/subscribe",
                headers={"Authorization": f"Bearer {token}"},
                params={"file_type": "bitable"},
            )
            data = resp.json()
            if data.get("code") == 0:
                logger.info("Bitable 文档事件订阅成功: file_token=%s", _TARGET_FILE_TOKEN)
                return True
            logger.error(
                "Bitable 文档事件订阅失败: code=%s msg=%s",
                data.get("code"), data.get("msg"),
            )
            return False
    except Exception:
        logger.exception("Bitable 文档事件订阅异常")
        return False


def _match_target(file_token: str, table_id: str) -> bool:
    """检查事件是否属于目标 Bitable 表格。"""
    if file_token and file_token != _TARGET_FILE_TOKEN:
        return False
    if table_id and table_id != _TARGET_TABLE_ID:
        return False
    return True


async def _get_fields_fallback(bitable: SafetyBitableClient, record_id: str, event_fields: dict) -> dict[str, Any]:
    """获取记录字段：优先用事件自带的 fields，缺失时调 API 拉取。"""
    if event_fields:
        logger.debug("使用事件自带 fields: keys=%s", list(event_fields.keys())[:20])
        return event_fields
    logger.info("⚠️ 事件未带 fields，通过 API 拉取全量: record_id=%s", record_id)
    api_fields = await bitable.get_record(record_id)
    logger.info(
        "API 返回字段: record_id=%s keys=%s inspector_raw=%s resp_raw=%s",
        record_id,
        list(api_fields.keys())[:20] if api_fields else [],
        str(api_fields.get("检查人员"))[:150] if api_fields.get("检查人员") else "N/A",
        str(api_fields.get("整改责任人"))[:150] if api_fields.get("整改责任人") else "N/A",
    )
    return api_fields


async def _handle_single_record_action(
    bitable: SafetyBitableClient,
    file_token: str,
    table_id: str,
    record_id: str,
    action: str,
    event_fields: dict[str, Any],
) -> None:
    """处理单条记录变更（action_list 中的一项或旧格式的一条事件）。

    统一入口：从 handle_bitable_record_changed 调用。
    """
    # 删除事件 → 暂不处理（可后续扩展为软删除）
    if action == "delete":
        logger.info("Bitable 记录已删除，暂不同步: record_id=%s", record_id)
        return

    # 去重（按 action+record_id+字段名，避免同record不同字段编辑被错误去重）
    # INSERT 使用 record 级 key（不加字段后缀），防止同一 record 的多个事件创建重复隐患
    if action == "insert":
        field_suffix = ""
    else:
        field_suffix = ",".join(sorted(event_fields.keys())) if event_fields else ""
    if await _is_duplicate(action, record_id, suffix=field_suffix):
        logger.info(
            "重复事件已忽略: action=%s record_id=%s fields=%s",
            action, record_id, field_suffix or "(none)",
        )
        return

    # ── insert: 新增记录 → 创建 HazardReport ──
    if action == "insert":
        logger.info("📌 Bitable 新增记录: record_id=%s", record_id)

        # INSERT 互斥锁：防止并行处理同一 record 的多个事件
        # （第一个事件未提交 DB 时，后续事件的 _get_hazard_by_feishu_id 查不到已有记录）
        lock_key = f"bitable:lock:insert:{record_id}"
        try:
            if not await redis_client.set(lock_key, "1", ex=120, nx=True):
                logger.warning(
                    "INSERT 互斥锁已存在，跳过: record_id=%s（可能有正在进行的创建）",
                    record_id,
                )
                return
        except Exception:
            pass  # Redis 不可用时降级，依赖去重 + DB 查询兜底

        # 检查是否已有 feishu_record_id（极少数重复场景）
        existing = await _get_hazard_by_feishu_id(record_id)
        if existing:
            logger.info("record_id=%s 已关联 hazard_id=%s，跳过创建", record_id, existing.id)
            return

        # ── CREATE 特殊处理：始终通过 API 拉取全量字段 ──
        # 原因：event_fields 仅含变更字段，person 类型字段（检查人员、责任人）
        # 可能缺失或格式不完整，导致 discovered_by_name 等关键字段为空。
        # 注意：「责任人」字段初始为空，由平台根据「责任部门」反推部门负责人后回填。
        # API 返回完整记录含 person 字段的 id/name，确保身份解析正确。
        api_fields = await bitable.get_record(record_id)
        fields: dict[str, Any] = {}
        if api_fields:
            fields = api_fields
            logger.info(
                "API 返回全量字段: record_id=%s keys=%s",
                record_id, list(api_fields.keys())[:30],
            )
        # 合并 event_fields（事件数据优先级更高，覆盖 API 返回的同名字段）
        if event_fields:
            fields.update(event_fields)
            logger.info(
                "合并事件字段: record_id=%s event_keys=%s final_keys=%s",
                record_id, list(event_fields.keys()), list(fields.keys())[:30],
            )
        if not fields:
            logger.warning("CREATE 无可用字段: record_id=%s", record_id)
            await _set_sync_ignore(record_id, ttl=30)
            return

        # 处理中（无字段更新，Bitable 中无"同步状态"字段）
        await _set_sync_ignore(record_id, ttl=120)

        await _create_hazard_from_bitable(record_id, fields)
        return

    # ── update: 修改记录 → 同步到已有 HazardReport ──
    if action == "update":
        # 平台→Bitable 方向触发的变更，跳过
        if await _is_sync_ignored(record_id):
            logger.debug("跳过平台主动推送触发的 update 事件: record_id=%s", record_id)
            return

        logger.info("📝 Bitable 修改记录: record_id=%s", record_id)

        hazard = await _get_hazard_by_feishu_id(record_id)
        if not hazard:
            # 还没有关联记录。
            # 检查是否有正在进行的 INSERT（通过互斥锁判断）。
            # 如果 INSERT 正在进行，跳过本次 update，避免重复创建。
            # 如果 INSERT 事件确实丢失，此 update 会承担创建职责。
            lock_key = f"bitable:lock:insert:{record_id}"
            try:
                if await redis_client.get(lock_key):
                    # INSERT 互斥锁存在 → 有 INSERT 正在进行
                    logger.info(
                        "record_id=%s 无关联记录但 INSERT 进行中，跳过本次更新"
                        "（INSERT 完成后会拉取全量字段，不会丢失数据）",
                        record_id,
                    )
                    return
            except Exception:
                pass  # Redis 不可用时降级，走查询 + 创建路径

            # 尝试获取 INSERT 锁，确保只有一个创建者
            try:
                if not await redis_client.set(lock_key, "1", ex=120, nx=True):
                    logger.info(
                        "record_id=%s INSERT 锁竞争失败，跳过",
                        record_id,
                    )
                    return
            except Exception:
                pass  # Redis 不可用时降级

            # 再次查询（可能在等待锁期间已有 INSERT 完成）
            hazard = await _get_hazard_by_feishu_id(record_id)
            if hazard:
                logger.info(
                    "record_id=%s 二次查询查到记录 hazard_id=%s，按 update 处理",
                    record_id, hazard.id,
                )
                # 已查到，继续走下面的 update 流程
            else:
                # 确实没有 → 作为新增处理（INSERT 事件丢失场景）
                # 先设置 INSERT 去重 key，防止可能到达的 INSERT 事件重复创建
                await _is_duplicate("insert", record_id, suffix="")
                logger.info("record_id=%s 无关联记录，按新增处理", record_id)
                fields = await _get_fields_fallback(bitable, record_id, event_fields)
                if fields:
                    await _create_hazard_from_bitable(record_id, fields)
                return

        # ── UPDATE 特殊处理：始终通过 API 拉取全量字段 ──
        # 原因：event_fields 仅含变更字段，附件字段缺少预签名 url/tmp_url，
        # 仅凭 file_token 难以下载。API 返回完整记录含可下载 URL，确保
        # 整改回复内容（纠正预防措施）和整改后图片（整改后图片）都能正确同步。
        api_fields = await bitable.get_record(record_id)
        fields: dict[str, Any] = {}
        if api_fields:
            fields = api_fields
            logger.info(
                "API 返回全量字段: record_id=%s keys=%s",
                record_id, list(api_fields.keys())[:30],
            )
        # 合并 event_fields（事件数据优先级更高，覆盖 API 返回的同名字段）
        if event_fields:
            fields.update(event_fields)
            logger.info(
                "合并事件字段: record_id=%s event_keys=%s final_keys=%s",
                record_id, list(event_fields.keys()), list(fields.keys())[:30],
            )
        if not fields:
            logger.warning("UPDATE 无可用字段: record_id=%s", record_id)
            return

        await _update_hazard_from_bitable(record_id, hazard, fields)


@on_event("drive.file.bitable_record_changed_v1")
async def handle_bitable_record_changed(event: dict) -> None:
    """处理多维表格记录变更事件。

    飞书实际 payload 结构（v2 action_list 格式）：
    {
        "file_token": "FIESb6X5kaMhUBsubrLcXvhfnxh",
        "table_id": "tblejHMrXJQVd3Qc",
        "action_list": [
            {
                "action": "record_added",          // record_added | record_edited | record_deleted
                "record_id": "recxxxxx",
                "after_value": [{"field_id": "fld...", "field_value": "..."}],
                "before_value": [...]
            }
        ]
    }
    """
    file_token = event.get("file_token", "")
    table_id = event.get("table_id", "")

    # ── 校验目标表格 ──
    if not _match_target(file_token, table_id):
        logger.debug("忽略非目标表格事件: file_token=%s table_id=%s", file_token, table_id)
        return

    bitable = SafetyBitableClient()

    # ── 解析 action_list（飞书实际格式）──
    action_list = event.get("action_list", [])

    if action_list:
        # v2 格式：action_list 数组
        logger.info(
            "📨 Bitable 事件(action_list): file_token=%s table_id=%s items=%d",
            file_token, table_id, len(action_list),
        )

        # 获取字段定义（含选项ID→名称映射，用于 after_value 中 field_id → field_name 转换）
        await _get_field_definitions(bitable)
        field_map = _field_name_cache or {}

        for item in action_list:
            record_id = item.get("record_id", "")
            action_raw = item.get("action", "")
            action = _ACTION_MAP.get(action_raw, action_raw)

            if not record_id:
                logger.warning("Bitable action_list 项缺少 record_id，跳过: action=%s", action_raw)
                continue

            # 从 after_value 解析字段值（field_id → field_name 转换）
            after_value = item.get("after_value", [])
            event_fields: dict[str, Any] = {}
            if after_value:
                event_fields = _convert_after_value_to_fields(after_value, field_map)
                logger.info(
                    "action_list 项: action=%s→%s record_id=%s fields=%d",
                    action_raw, action, record_id, len(event_fields),
                )

            await _handle_single_record_action(
                bitable, file_token, table_id, record_id, action, event_fields,
            )
        return

    # ── 兼容旧格式（flat record_id/action/fields）──
    record_id = event.get("record_id", "")
    action = event.get("action", "")
    event_fields = event.get("fields", {}) or {}

    logger.info(
        "📨 Bitable 事件(flat): action=%s file_token=%s table_id=%s record_id=%s fields=%d",
        action, file_token, table_id, record_id, len(event_fields),
    )

    if not record_id:
        logger.warning("Bitable 事件缺少 record_id，忽略")
        return

    await _handle_single_record_action(
        bitable, file_token, table_id, record_id, action, event_fields,
    )


@on_event("drive.file.bitable_field_changed_v1")
async def handle_bitable_field_changed(event: dict) -> None:
    """处理多维表格字段级变更事件（补充处理器）。

    当记录的部分字段被修改时触发，比 record_changed_v1 更细粒度。
    从 event 中提取 after_value 字段数据，与 record_changed_v1 协同工作。

    重要：必须传递 fields 数据给 handle_bitable_record_changed。
    否则当两个事件竞速（field_changed 先到 + record_changed 被去重），
    只能靠 API 重拉取，API 延迟会导致字段变更丢失、状态转换不触发。
    """
    file_token = event.get("file_token", "")
    table_id = event.get("table_id", "")

    if not _match_target(file_token, table_id):
        return

    # 确保字段定义已加载（field_id → field_name 转换依赖此缓存）
    bitable = SafetyBitableClient()
    await _get_field_definitions(bitable)
    field_map = _field_name_cache or {}

    action_list = event.get("action_list", [])
    if action_list:
        # v2 格式：遍历 action_list，提取每个字段的 after_value
        for item in action_list:
            record_id = item.get("record_id", "")
            field_id = item.get("field_id", "")
            if not record_id:
                continue
            # 从 item 中提取字段值（field_changed 的 after_value 是单字段值）
            event_fields = _extract_field_value(item, field_id, field_map)
            logger.info(
                "📝 Bitable 字段变更: record_id=%s field_id=%s field_name=%s",
                record_id, field_id, list(event_fields.keys()),
            )
            await handle_bitable_record_changed({
                "file_token": file_token,
                "table_id": table_id,
                "record_id": record_id,
                "action": "update",
                "fields": event_fields,  # 传递字段数据，避免依赖 API 重拉取
            })
        return

    # 旧格式兼容
    record_id = event.get("record_id", "")
    field_id = event.get("field_id", "")
    if not record_id:
        return
    event_fields = _extract_field_value(event, field_id, field_map)
    logger.info(
        "📝 Bitable 字段变更(旧格式): record_id=%s field_id=%s field_name=%s",
        record_id, field_id, list(event_fields.keys()),
    )
    await handle_bitable_record_changed({
        "file_token": file_token,
        "table_id": table_id,
        "record_id": record_id,
        "action": "update",
        "fields": event_fields,
    })


async def _auto_skip_level2_for_general_hazard(hazard: Any, record_id: str) -> None:
    """一般隐患 L1 通过后：自动将 L2（分管领导复核）设为「无需复核」并跳至 L3。

    一般隐患只需部门负责人复核（L1）和检查人员复核（L3），分管领导无需介入。
    此函数在 L1 审批通过时被调用，完成三步操作：
    1. DB: verify_level_2_status → "no_review_needed", rectification_status → "level2_approved"
    2. Bitable: 分管领导复核字段 → "无需复核"
    3. 通知 L3（检查人员）
    """
    from sqlalchemy import update

    from app.core.database import async_session_factory
    from app.modules.safety.models import HazardReport

    logger.info(
        "一般隐患 L1 已通过 → 自动跳过 L2（分管领导无需复核）: hazard_no=%s record_id=%s",
        hazard.hazard_no, record_id,
    )

    # 1. 更新 DB
    try:
        async with async_session_factory() as session:
            await session.execute(
                update(HazardReport)
                .where(HazardReport.id == hazard.id)
                .values(
                    verify_level_2_status="no_review_needed",
                    rectification_status="level2_approved",
                )
            )
            await session.commit()
            logger.info(
                "DB 已更新 (L2=no_review_needed): hazard_no=%s", hazard.hazard_no,
            )
    except Exception:
        logger.exception("DB 更新 L2=no_review_needed 失败: hazard_no=%s", hazard.hazard_no)
        return

    # 2. 回写 Bitable「分管领导复核」字段为「无需复核」
    # 注意：不设置 sync_ignore，因为重入 webhook 是安全的：
    #   - _compute_rectification_status 会计算出相同的 "level2_approved"
    #   - computed_status == old_rectification_status → 跳过更新，不会触发额外的 Bitable 写回
    # 设置 sync_ignore 反而会阻塞用户在 Bitable 的后续 V3 操作 webhook（TTL=30s 竞态）。
    try:
        _bt = SafetyBitableClient()
        ok = await _bt.update_record(record_id, {"分管领导复核": "无需复核"})
        if ok:
            logger.info(
                "Bitable「分管领导复核」已更新为「无需复核」: record_id=%s", record_id,
            )
        else:
            logger.error(
                "Bitable「分管领导复核」更新失败: record_id=%s", record_id,
            )
    except Exception:
        logger.exception("Bitable 回写「无需复核」失败: record_id=%s", record_id)

    # 3. 通知 L3（检查人员）
    # 更新内存对象以便通知使用最新状态
    hazard.verify_level_2_status = "no_review_needed"
    hazard.rectification_status = "level2_approved"
    asyncio.create_task(_send_verify_notification(hazard, 3))


# ═══════════════════════════════════════════════════════════════
# 卡片交互处理器：复核通知卡片中的「直接同意/驳回」按钮
# ═══════════════════════════════════════════════════════════════

# Level → Bitable 字段名
_LEVEL_TO_BITABLE_FIELD = {
    1: "部门负责人复核",
    2: "分管领导复核",
    3: "检查人员复核",
}

# Level → 显示标签
_LEVEL_LABELS = {1: "一级（部门负责人）", 2: "二级（分管领导）", 3: "三级（检查人员）"}


@on_event("card.action.trigger")
async def handle_card_action(event: dict) -> dict | None:
    """处理复核通知卡片中的「同意 / 驳回」按钮点击。

    收到按钮点击后：
    1. 从本地 DB 获取隐患记录，构建更新后的卡片（快速路径）
    2. ACK 立即返回卡片更新（防止飞书 3 秒超时导致卡片回滚）
    3. Bitable API 更新放入后台异步执行
    4. Bitable 更新成功后 PATCH 更新卡片；失败则 PATCH 恢复卡片原状

    注意：Bitable API 调用可能耗时超过 2.9s（飞书 WS 超时阈值），
    因此必须先在 ACK 中返回卡片更新，Bitable 写入作为后台任务兜底。
    """
    action_value = event.get("action", {})
    value_str = action_value.get("value", "{}")
    try:
        value = json.loads(value_str) if isinstance(value_str, str) else value_str
    except (json.JSONDecodeError, TypeError):
        logger.warning("卡片按钮 value 解析失败: %s", value_str)
        return None

    card_action = value.get("action", "")
    if card_action not in ("approve_rectification", "reject_rectification"):
        return None  # 不是我们的卡片

    record_id = value.get("record_id", "")
    level = value.get("level", 0)
    action_type = "approve" if card_action == "approve_rectification" else "reject"

    bt_field = _LEVEL_TO_BITABLE_FIELD.get(level)
    if not bt_field:
        logger.warning("未知复核级别: level=%s", level)
        return {"toast": {"type": "error", "content": f"未知复核级别: {level}"}}

    bt_value = "已同意" if action_type == "approve" else "未同意"
    level_label = _LEVEL_LABELS.get(level, f"{level}级")
    button_state = "approved" if action_type == "approve" else "rejected"
    action_label = "已同意" if action_type == "approve" else "已驳回"

    logger.info(
        "卡片操作: record_id=%s level=%s action=%s field=%r value=%r",
        record_id, level, action_type, bt_field, bt_value,
    )

    # ── 第一步：立即构建卡片更新（快速路径，不等待 Bitable API）──
    updated_card = None
    hazard = None
    try:
        hazard = await _get_hazard_by_feishu_id(record_id)
        if hazard:
            title, content, elements = await _build_verify_card_content(
                hazard, level, button_state=button_state, skip_photos=True,
            )
            updated_card = {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": "green" if action_type == "approve" else "red",
                },
                "elements": [
                    {"tag": "markdown", "content": content},
                    *elements,
                ],
            }
    except Exception:
        logger.exception("构建卡片更新失败: record_id=%s", record_id)

    # ── 第二步：Bitable 更新 + PATCH 卡片放入后台异步执行 ──
    open_message_id = event.get("context", {}).get("open_message_id", "")
    hazard_no = getattr(hazard, "hazard_no", "") if hazard else ""
    asyncio.create_task(
        _handle_approve_background(
            record_id=record_id,
            bt_field=bt_field,
            bt_value=bt_value,
            level=level,
            button_state=button_state,
            open_message_id=open_message_id,
            updated_card=updated_card,
            hazard_no=hazard_no,
        )
    )

    # ── 第三步：ACK 立即返回卡片更新（防止超时回滚）──
    if updated_card:
        return {
            "toast": {"type": "success", "content": f"{level_label} 审核{action_label}"},
            "card": {"type": "raw", "data": updated_card},
        }
    else:
        # 卡片构建失败：仍然返回 toast，Bitable 更新由后台处理
        return {
            "toast": {"type": "success", "content": f"{level_label} 审核{action_label}（卡片稍后更新）"},
        }


async def _patch_card_async(
    open_message_id: str,
    card: dict,
    hazard_no: str,
    level: int,
    button_state: str,
) -> None:
    """后台通过 Message PATCH API 更新卡片（兜底保障）。"""
    try:
        import httpx

        from app.modules.safety.feishu.client import get_safety_tenant_token

        token = await get_safety_tenant_token()
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.patch(
                f"https://open.feishu.cn/open-apis/im/v1/messages/{open_message_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={"content": json.dumps(card, ensure_ascii=False)},
            )
            if resp.status_code == 200 and resp.json().get("code") == 0:
                logger.info(
                    "卡片 PATCH 成功: msg=%s hazard=%s level=%s state=%s",
                    open_message_id, hazard_no, level, button_state,
                )
            else:
                logger.error(
                    "卡片 PATCH 失败: status=%s body=%s",
                    resp.status_code, resp.text[:500],
                )
    except Exception:
        logger.exception("卡片 PATCH 异常: msg=%s", open_message_id)


async def _handle_approve_background(
    record_id: str,
    bt_field: str,
    bt_value: str,
    level: int,
    button_state: str,
    open_message_id: str,
    updated_card: dict | None,
    hazard_no: str,
) -> None:
    """后台执行 Bitable 更新 + 卡片 PATCH 确认/恢复。

    ACK 已先行返回卡片更新防止超时回滚，此函数负责：
    1. 调用 Bitable API 更新审批字段
    2. 成功 → PATCH 确认卡片状态
    3. 失败 → PATCH 恢复卡片为原始激活态（含同意/驳回按钮），提示用户重试
    """
    try:
        bitable = SafetyBitableClient()
        success = await bitable.update_record(record_id, {bt_field: bt_value})

        if success:
            logger.info(
                "后台 Bitable 更新成功: record_id=%s field=%s value=%s",
                record_id, bt_field, bt_value,
            )
            # PATCH 卡片确认为最终状态（ACK 已先行更新，此处做确定性落盘）
            if open_message_id and updated_card:
                await _patch_card_async(
                    open_message_id, updated_card, hazard_no, level, button_state,
                )
        else:
            logger.error(
                "后台 Bitable 更新失败: record_id=%s field=%s — 尝试恢复卡片",
                record_id, bt_field,
            )
            # Bitable 写入失败 → 恢复卡片到原始状态，告知用户重试
            if open_message_id:
                try:
                    hazard = await _get_hazard_by_feishu_id(record_id)
                    if hazard:
                        title, content, elements = await _build_verify_card_content(
                            hazard, level, button_state=None, skip_photos=True,
                        )
                        revert_card = {
                            "config": {"wide_screen_mode": True},
                            "header": {
                                "title": {"tag": "plain_text", "content": title},
                                "template": "orange",
                            },
                            "elements": [
                                {"tag": "markdown", "content": content},
                                *elements,
                            ],
                        }
                        await _patch_card_async(
                            open_message_id, revert_card, hazard_no, level, "reverted",
                        )
                except Exception:
                    logger.exception("恢复卡片失败: record_id=%s", record_id)

    except Exception:
        logger.exception(
            "后台审批操作异常: record_id=%s field=%s", record_id, bt_field,
        )
        # 尝试恢复卡片
        if open_message_id:
            try:
                hazard = await _get_hazard_by_feishu_id(record_id)
                if hazard:
                    title, content, elements = await _build_verify_card_content(
                        hazard, level, button_state=None, skip_photos=True,
                    )
                    revert_card = {
                        "config": {"wide_screen_mode": True},
                        "header": {
                            "title": {"tag": "plain_text", "content": title},
                            "template": "orange",
                        },
                        "elements": [
                            {"tag": "markdown", "content": content},
                            *elements,
                        ],
                    }
                    await _patch_card_async(
                        open_message_id, revert_card, hazard_no, level, "reverted",
                    )
            except Exception:
                logger.exception("恢复卡片失败: record_id=%s", record_id)
