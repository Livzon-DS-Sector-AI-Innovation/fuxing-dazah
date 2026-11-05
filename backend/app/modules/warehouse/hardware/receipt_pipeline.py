"""五金库 OCR 入库编排管线（M2 主通道，设计 §四 4.1）。

拍照 → 识别（recognizer，场景开关/审计全继承）→ 四级匹配（matcher，
低置信标黄只标记不代改）→ 入库草稿（hardware_receipts draft，红线：OCR
永不自动动账）→ 一屏确认（service.accept_receipt 双签入账 / reject 拒收）。

Web 工作台与 agent 对话共用本管线；agent 侧另行走 warehouse_agent_drafts
两段式确认门（草稿回显卡片 → 确认卡）。
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.ai_config.scenario_store import scenario_store
from app.modules.warehouse.hardware import matcher as hw_matcher
from app.modules.warehouse.hardware import recognizer as hw_recognizer
from app.modules.warehouse.hardware import service as hw_service
from app.modules.warehouse.hardware.models import HardwareMaterial, HardwareReceipt
from app.modules.warehouse.hardware.schemas import ReceiptCreate, ReceiptItemIn

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")

HARDWARE_SCENARIO = hw_recognizer.HARDWARE_SCENARIO


class ScenarioDisabled(Exception):
    """场景开关关闭（API 层转 503）。"""


async def load_active_materials(db: AsyncSession) -> list[HardwareMaterial]:
    """全量主数据载入（492 项规模，匹配器纯内存计算）。"""
    return list(
        (
            await db.execute(
                select(HardwareMaterial).where(
                    HardwareMaterial.is_deleted.is_(False),
                    HardwareMaterial.active.is_(True),
                )
            )
        ).scalars().all()
    )


def _parse_arrived(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日", "%Y%m%d"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=CN_TZ)
        except ValueError:
            continue
    return None


async def build_ocr_draft(
    db: AsyncSession,
    *,
    image_b64: str,
    content_type: str = "image/jpeg",
    source_image_token: str | None = None,
    operator: str | None = None,
    auto_accept: bool = True,
) -> tuple[HardwareReceipt, dict[str, Any]]:
    """图片 → 识别 → 匹配 → 入库草稿（不动账）。

    返回 (receipt, summary)；summary 含逐行匹配置信度（前端标黄依据）。
    auto_accept=False 供 agent 对话入口（gateway_inbound）禁用 M9 自动
    入账评估——对话入库保持两段式确认卡人工红线。
    """
    if not scenario_store.is_enabled(HARDWARE_SCENARIO):
        raise ScenarioDisabled("五金库送货单识别场景已停用")

    # ① 方向预判+旋正 ② 结构化识别（recognizer 内含审计 resource 标记）
    rotated_b64, rotated_type = await hw_recognizer.rotate_image_if_needed(
        image_b64, content_type
    )
    recognized = await hw_recognizer.recognize_hardware_receipt(
        rotated_b64, rotated_type
    )
    if not recognized.rows:
        raise ValueError("未识别到物料行（图片可能不是送货单，请用手动登记兜底）")

    # ③ 四级匹配 + 行分类（stocked/direct）
    materials = await load_active_materials(db)
    match_summary: list[dict[str, Any]] = []
    items: list[ReceiptItemIn] = []
    matched_stocked = matched_direct = unmatched = 0
    for row in recognized.rows:
        result = hw_matcher.match_one(
            code=row.code, name=row.name, spec=row.spec, materials=materials
        )
        item = ReceiptItemIn(
            material_id=str(result.material.id) if result.material else None,
            name=result.material.name if result.material else row.name,
            spec=(result.material.spec if result.material else row.spec),
            unit=(result.material.unit if result.material else row.unit),
            quantity=Decimal(str(row.quantity)),
            match_confidence=result.method,
            match_score=result.score,
        )
        items.append(item)
        if result.material and result.material.managed_class == "stocked":
            matched_stocked += 1
        elif result.material:
            matched_direct += 1
        else:
            unmatched += 1
        match_summary.append(
            {
                "ocr_name": row.name,
                "ocr_spec": row.spec,
                "quantity": row.quantity,
                "matched": result.material.name if result.material else None,
                "method": result.method,
                "score": float(result.score),
                "low_confidence": result.low_confidence,
            }
        )

    # ④ 单头 mode 预判：全部行清单外=direct（直发单），否则 stocked
    mode = "direct" if (unmatched == len(recognized.rows) and matched_stocked == 0) else "stocked"

    payload = ReceiptCreate(
        source="ocr",
        mode=mode,  # type: ignore[arg-type]
        supplier_name=recognized.supplier,
        delivery_note_no=recognized.delivery_note_no,
        arrived_at=_parse_arrived(recognized.arrived_date) or datetime.now(CN_TZ),
        target_dept=None if mode == "stocked" else _guess_dept(recognized.remark),
        attachments=(
            [{"kind": "delivery_note_photo", "file_token": source_image_token}]
            if source_image_token
            else None
        ),
        items=items,
    )
    receipt = await hw_service.create_receipt(db, payload)

    # ocr_result JSON 留痕（原样提取 + 逐行匹配置信度，设计 §2.3）
    receipt.ocr_result = {
        "supplier": recognized.supplier,
        "delivery_note_no": recognized.delivery_note_no,
        "arrived_date": recognized.arrived_date,
        "remark": recognized.remark,
        "rows": [r.model_dump() for r in recognized.rows],
        "match_summary": match_summary,
    }
    await db.flush()

    summary = {
        "receipt_id": str(receipt.id),
        "receipt_no": receipt.receipt_no,
        "mode": mode,
        "matched_stocked": matched_stocked,
        "matched_direct": matched_direct,
        "unmatched": unmatched,
        "rows": match_summary,
    }

    # M9：direct 高置信自动入账评估（开关关=短路返回 None，行为逐字节现状；
    # agent 对话入口 auto_accept=False 保持人工确认卡）
    if auto_accept:
        from app.modules.warehouse.hardware.service import try_auto_accept_direct

        auto = await try_auto_accept_direct(
            db, receipt.id, operator=operator or "ocr_pipeline"
        )
        if auto is not None:
            receipt = auto
            summary["auto_accepted"] = True
    return receipt, summary


def _guess_dept(remark: str | None) -> str | None:
    """从备注猜直发车间（发酵/提炼一期/提炼二期/精制机修/动力机修）。"""
    from app.modules.warehouse.hardware.models import DEMAND_DEPARTMENTS

    if not remark:
        return None
    for dept in DEMAND_DEPARTMENTS:
        if dept in remark:
            return dept
    return None
