"""对话式填报：@机器人发指令 → 解析 → 按标准库限度判定 → 写入检验任务 → 群内回执。

指令格式示例：
    @消息推送机器人 批号 HAF2608001B 水分 4.5 炽灼残渣 0.10 残留溶剂(乙醇) 30
"""

import json
import logging
import re
import time

from app.core.time import today as _app_today
from app.modules.quality.feishu.client import (
    QUALITY_FEISHU_CHAT_IDS,
    QUALITY_FEISHU_CREATE_USER_IDS,
    QUALITY_FEISHU_USER_IDS,
)
from app.modules.quality.models import QualityStandardDocument, QualityTestTask
from app.modules.quality.repository import (
    get_test_task_by_batch,
    get_test_task_by_batch_number,
    list_standard_documents,
)
from app.modules.quality.service import TestTaskService

logger = logging.getLogger(__name__)

_BATCH_RE = re.compile(r"批\s*号[：:\s]*([A-Za-z0-9-]+)")
_PAIR_RE = re.compile(r"([一-鿿][^\s]*)\s+(\d+(?:\.\d+)?)")

# 液相计算表解析覆盖的项目名片段（这些项目上传计算表自动填入，表单卡片不再列出）
# 生物组项目（微生物/效价/含量类），其余归理化组
_BIO_PATTERNS = ["需氧菌", "效价", "含量"]
_LC_SHEET_PATTERNS = ["杂质", "万古霉素", "总杂质", "任何未知杂质", "rs"]


def _extract_command(event: dict) -> tuple[str | None, str | None, str | None, str | None]:
    """从 im.message.receive_v1 事件提取 (chat_id, sender_open_id, 消息文本, chat_type)。"""
    try:
        ev = event.get("event", {})
        msg = ev.get("message", {})
        chat_id = msg.get("chat_id")
        sender = (ev.get("sender", {}).get("sender_id") or {}).get("open_id")
        content = msg.get("content", "{}")
        text = json.loads(content).get("text", "")
        return chat_id, sender, text, msg.get("chat_type", "group")
    except Exception:
        return None, None, None, None


def _allowed(chat_id: str, sender: str) -> bool:
    if QUALITY_FEISHU_CHAT_IDS and chat_id not in QUALITY_FEISHU_CHAT_IDS:
        return False
    if QUALITY_FEISHU_USER_IDS and sender not in QUALITY_FEISHU_USER_IDS:
        return False
    return True


def _allowed_create(sender: str) -> bool:
    """新建任务权限：配置了 QUALITY_FEISHU_CREATE_USER_IDS 时仅白名单用户可建；空 = 不限制。"""
    if not QUALITY_FEISHU_CREATE_USER_IDS:
        return True
    return bool(sender) and sender in QUALITY_FEISHU_CREATE_USER_IDS


_CREATE_DENY_TEXT = "⛔ 你没有新建任务的权限，请联系质量管理员"


async def _known_codes(db) -> list[str]:
    """标准库已配置的全部产品代号（错误提示用）。"""
    docs = await list_standard_documents(db)
    return sorted({(d.product_code or "").strip() for d in docs if (d.product_code or "").strip()})


async def _resolve_docs_by_batch(db, batch: str) -> list[QualityStandardDocument]:
    """批号必然含产品代号：按批号开头收敛到该代号的标准文件（标准文档）。"""
    docs = await list_standard_documents(db)
    _, matched = TestTaskService._match_docs_by_batch_code(docs, batch)
    return matched


def _doc_to_card_dict(doc: QualityStandardDocument) -> dict:
    return {
        "id": str(doc.id),
        "file_no": doc.file_no,
        "product_code": doc.product_code,
        "product_internal_code": doc.product_internal_code,
    }


async def _resolve_task_by_batch(db, batch: str) -> QualityTestTask | None:
    """按批号查任务；同批号跨产品时用批号代号收敛到对应产品。"""
    task = await get_test_task_by_batch_number(db, batch)
    if not task:
        return None
    matched = await _resolve_docs_by_batch(db, batch)
    if not matched:
        return task

    def _norm(n: str) -> str:
        return re.sub(r"\s+", "", n)

    if _norm(task.product_name) in {_norm(d.product_name) for d in matched}:
        return task
    return await get_test_task_by_batch(db, matched[0].product_name, batch)


# 标准文件多选点选卡片的进行中勾选状态（按批号隔离，任务创建成功后清除）
_PENDING_DOC_SELECT: dict[str, set[str]] = {}

# 图片消息暂存（先发图 → 回复「附件 批号 X」两步归档原始证据）；30 分钟过期自动清理
_LAST_IMAGE: dict[str, dict[str, str]] = {}
_LAST_IMAGE_TS: dict[str, float] = {}

# 归档模式：chat_id → task_id（连拍多张自动归档，发「结束」退出）；30 分钟过期自动清理
_ARCHIVE_MODE: dict[str, str] = {}
_ARCHIVE_MODE_TS: dict[str, float] = {}

_STATE_TTL = 30 * 60  # 临时状态过期时间（秒）


def _prune_stale_state() -> None:
    """机会式清理过期临时状态（多副本部署各自独立——短期状态可接受，防内存只增不减）。"""
    now = time.monotonic()
    for ts_map, state_map in ((_LAST_IMAGE_TS, _LAST_IMAGE), (_ARCHIVE_MODE_TS, _ARCHIVE_MODE)):
        for key in [k for k, ts in ts_map.items() if now - ts > _STATE_TTL]:
            state_map.pop(key, None)
            ts_map.pop(key, None)

# 当前批号上下文：chat_id → batch（省略批号的指令沿用）
_LAST_BATCH: dict[str, str] = {}


async def _download_image(message_id: str, file_key: str) -> bytes | None:
    """下载飞书图片消息原始文件；失败返回 None。"""
    try:
        from lark_oapi.api.im.v1 import MessageResourceGetRequest

        from app.modules.quality.feishu.client import build_client

        req = (
            MessageResourceGetRequest.builder()
            .message_id(message_id)
            .file_key(file_key)
            .type_("image")
            .build()
        )
        resp = await build_client().im.v1.message_resource.get(req)
        if resp.success() and resp.file:
            return resp.file.read()
    except Exception:
        logger.exception("飞书图片下载失败")
    return None

async def _task_doc_file_nos(db, task: QualityTestTask) -> list[str]:
    """任务对应的标准文件编号列表（出报清单展示用）。"""
    from app.modules.quality.repository import (
        get_standard_document,
        list_task_standard_document_ids,
    )

    ids = await list_task_standard_document_ids(db, task.id)
    out: list[str] = []
    for did in ids:
        d = await get_standard_document(db, did)
        if d:
            out.append(d.file_no)
    return out




def _limit_text(row, unit: str) -> str:
    """限度摘要（如 ≤ 3.0%）。"""
    return (
        f"{row.operator or ''} {row.limit_min if row.limit_min is not None else ''}"
        f"{row.limit_max if row.limit_max is not None else ''}{unit}"
    ).strip()

def _today_str() -> str:
    """北京日期 YYYY-MM-DD（与流水号/每日推送/出报日期口径一致）。"""
    return _app_today().isoformat()


def _norm_sop(s: str | None) -> str:
    """SOP 号归一化（去空白+大写），相同 SOP 判定用。"""
    return re.sub(r"\s+", "", s or "").upper()


def _unfilled_groups(rows: list) -> tuple[list[dict], list[dict]]:
    """未填报的数值型项目按 生物组/理化组 分组。

    相同 SOP 号合并为一个输入（填写一次、提交时按组内每行限度分别判定自动匹配）；
    组 entry：{label, map_value}，map_value 为 JSON 化的结果行 ID 列表。
    （液相解析覆盖项与默认规则项排除。）
    """
    candidates = [
        r for r in rows
        if r.judge_mode == "auto" and r.is_pass is None
        and not any(pat in TestTaskService._norm_name(r.item_name) for pat in _LC_SHEET_PATTERNS)
        and TestTaskService._norm_name(r.item_name) not in TestTaskService._DEFAULT_FILL_RULES
    ]
    groups: dict[str, list] = {}
    order: list[str] = []
    for r in candidates:
        sop = _norm_sop(r.sop_no)
        key = f"sop:{sop}" if sop else f"item:{TestTaskService._norm_name(r.item_name)}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(r)

    def _build(rs: list) -> dict:
        names: list[str] = []
        limits: list[str] = []
        for r in rs:
            if r.item_name not in names:
                names.append(r.item_name)
            limit = (
                f"{r.operator or ''} {r.limit_min if r.limit_min is not None else ''}"
                f"{r.limit_max if r.limit_max is not None else ''}"
                f"{TestTaskService._unit_of(r.standard_text)}"
            ).strip()
            if limit not in limits:
                limits.append(limit)
        sop_label = (rs[0].sop_no or "").strip()
        label = (f"{sop_label} " if sop_label else "") + "、".join(names) + f"（{'；'.join(limits)}）"
        return {"label": label, "map_value": json.dumps([str(r.id) for r in rs])}

    out = [_build(groups[k]) for k in order]
    bio_rows = [r for r in out if any(p in r["label"] for p in _BIO_PATTERNS)]
    chem_rows = [r for r in out if r not in bio_rows]
    return bio_rows, chem_rows

def _frontend_task_link(task_id: str) -> str:
    """系统任务详情页链接（推送消息附带，飞书自动识别可点）。"""
    from app.core.config import get_settings

    base = (get_settings().FRONTEND_URL or "http://localhost:3000").rstrip("/")
    return f"{base}/quality/task/{task_id}"
