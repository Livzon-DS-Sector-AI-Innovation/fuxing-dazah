"""五金库实物照片初筛（三期 M7，L1 vision，设计 §9.1 二期后按需项）。

入库确认环节（Web 工作台 + agent 两入口）可附实物照片 → vision 初筛
（破损/锈蚀/渗漏/受潮）→ **advisory 标记落 receipt 行 photo_screening**
（只标记不拦截不代改——MSDS 审核模式红线）。

降级三态（沿 plan_annotation 模式）：
- 场景停用（scenario_store.is_enabled=False）→ 无标记不阻塞；
- LLM 调用失败 / 输出非 JSON → 无标记不阻塞；
- 成功 → 按行落 {flagged, findings[], screened_at, scenario}。

场景 ``hardware_photo_screening``（scenario_registry 注册 + M7 迁移播种）。
行定位契约：LLM 按「行序号（送货单行序）+品名提示」回 index，与
list_receipt_items 顺序对齐；越界/缺失行忽略不报错。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent.llm_client import get_llm_client
from app.modules.warehouse.ai_audit.context import warehouse_audit_scope
from app.modules.warehouse.ai_config.scenario_store import scenario_store
from app.modules.warehouse.hardware import service as hw_service
from app.modules.warehouse.hardware.models import HardwareReceiptItem

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")

PHOTO_SCREENING_SCENARIO = "hardware_photo_screening"

PHOTO_SCREENING_PROMPT = """你是一名五金仓库的验收助理。图片是入库实物照片（可能与送货单一同拍摄）。
请对照片中的实物做质量初筛，检查以下四类问题：破损、锈蚀、渗漏、受潮。
严格输出 JSON（不要任何解释文字或代码块包裹）：

{
  "rows": [
    {
      "row_index": 行序号（送货单第几行，从 0 起；单图单行实物填 0）,
      "findings": [
        {"type": "破损|锈蚀|渗漏|受潮", "severity": "low|mid|high", "note": "20字内现象描述"}
      ]
    }
  ],
  "overall": "一句话整体初筛结论（无异常填'未见明显异常'）"
}

要求：
- 只描述照片中可见的现象，不做处置建议（处置由仓管员决定）；
- 没有问题的行 findings 返回 []；整张照片无对应单行时 row_index 填 0；
- 识别不到实物时返回 {"rows": [], "overall": "未识别到实物"}。"""

_FINDING_TYPES = ("破损", "锈蚀", "渗漏", "受潮")
_SEVERITIES = ("low", "mid", "high")


def _assistant_text(message: Any) -> str | None:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content if isinstance(p, dict)]
        return "\n".join(p for p in parts if p) or None
    return None


def _parse_findings(text: str | None) -> dict[str, Any] | None:
    """宽松解析 JSON（剥代码块围栏；失败返回 None=降级无标记）。"""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _sanitize_findings(raw_findings: Any) -> list[dict[str, str]]:
    """findings 收敛：类型/严重度白名单过滤，note 截断（LLM 输出不可信原则）。"""
    out: list[dict[str, str]] = []
    for f in raw_findings or []:
        if not isinstance(f, dict):
            continue
        ftype = str(f.get("type") or "").strip()
        if ftype not in _FINDING_TYPES:
            continue
        severity = str(f.get("severity") or "mid").strip()
        out.append({
            "type": ftype,
            "severity": severity if severity in _SEVERITIES else "mid",
            "note": str(f.get("note") or "").strip()[:100],
        })
    return out


async def screen_receipt_photos(
    db: AsyncSession,
    receipt_id: UUID,
    *,
    photos: list[dict[str, Any]],
    operator: str | None = None,
) -> dict[str, Any]:
    """实物照片初筛：vision 提取 → advisory 标记落 receipt 行。

    photos: [{file_token, image_b64, content_type}]（Web 上传/agent 附件同构）。
    返回 summary：{screened, reason?, flagged_rows, rows}；任何失败路径
    （停用/LLM 挂死/非 JSON）均不抛错不标记——初筛永不阻塞入库。
    """
    receipt = await hw_service.get_receipt(db, receipt_id)
    items = await hw_service.list_receipt_items(db, receipt_id)
    if not items or not photos:
        return {"screened": False, "reason": "no_items_or_photos", "flagged_rows": 0, "rows": []}

    if not scenario_store.is_enabled(PHOTO_SCREENING_SCENARIO):
        return {"screened": False, "reason": "scenario_disabled", "flagged_rows": 0, "rows": []}

    from app.modules.warehouse.agent.pipeline.recognizer import build_vision_message

    # 逐照片调用（单图单消息；多图逐张合并行结论）
    rows_payload: dict[int, dict[str, Any]] = {}
    overall_parts: list[str] = []
    try:
        with warehouse_audit_scope(
            PHOTO_SCREENING_SCENARIO, resource="photo_screening", channel="web",
        ):
            async with get_llm_client() as client:
                for photo in photos:
                    image_b64 = str(photo.get("image_b64") or "")
                    if not image_b64:
                        continue
                    content_type = str(photo.get("content_type") or "image/jpeg")
                    message = build_vision_message(
                        image_b64, content_type, prompt=PHOTO_SCREENING_PROMPT
                    )
                    content = await client.chat_with_tools(
                        [message], tools=None, temperature=0.1, max_tokens=2048
                    )
                    payload = _parse_findings(_assistant_text(content))
                    if payload is None:
                        return {
                            "screened": False, "reason": "llm_error",
                            "flagged_rows": 0, "rows": [],
                        }
                    for row_entry in payload.get("rows") or []:
                        if not isinstance(row_entry, dict):
                            continue
                        try:
                            idx = int(row_entry.get("row_index"))
                        except (TypeError, ValueError):
                            continue
                        if idx < 0 or idx >= len(items):
                            continue  # 越界行忽略
                        bucket = rows_payload.setdefault(idx, {"findings": []})
                        bucket["findings"].extend(_sanitize_findings(row_entry.get("findings")))
                    overall = str(payload.get("overall") or "").strip()
                    if overall:
                        overall_parts.append(overall)
    except Exception:  # noqa: BLE001
        logger.warning("实物照片初筛 LLM 调用失败（降级无标记，不阻塞入库）", exc_info=True)
        return {"screened": False, "reason": "llm_error", "flagged_rows": 0, "rows": []}

    # 标记落行（只标记：不改行任何业务字段，不拦截确认）
    now = datetime.now(CN_TZ)
    result_rows: list[dict[str, Any]] = []
    flagged = 0
    for idx, item in enumerate(items):
        bucket = rows_payload.get(idx)
        findings = bucket["findings"] if bucket else []
        item.photo_screening = {
            "flagged": bool(findings),
            "findings": findings,
            "overall": "；".join(overall_parts)[:200] or None,
            "screened_at": now.isoformat(),
            "screened_by": operator or "system",
            "scenario": PHOTO_SCREENING_SCENARIO,
            "photos": [p.get("file_token") for p in photos if p.get("file_token")],
        }
        if findings:
            flagged += 1
        result_rows.append({
            "item_id": str(item.id),
            "name": item.name,
            "flagged": bool(findings),
            "findings": findings,
        })
    await db.flush()
    logger.info(
        "实物照片初筛完成: receipt=%s photos=%d flagged_rows=%d",
        receipt.receipt_no, len(photos), flagged,
    )
    return {"screened": True, "flagged_rows": flagged, "rows": result_rows}
