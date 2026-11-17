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


class ParsedReceipt:
    """截图纯解析结果（不落库）：方式2「上传截图自动填单」的前后端契约源。

    parse_receipt_image 产出；Web 表单预填 → 人工核对修正 → POST /receipts
    （source=ocr + ocr_result 留痕原样回传）。build_ocr_draft（直落草稿）
    复用同一解析段，两条入库录入方式共享匹配语义。
    """

    def __init__(
        self,
        *,
        supplier: str | None,
        delivery_note_no: str | None,
        arrived_date: str | None,
        remark: str | None,
        mode: str,
        target_dept: str | None,
        items: list[ReceiptItemIn],
        matched_names: list[str | None],
        low_confidences: list[bool],
        match_summary: list[dict[str, Any]],
        rows_raw: list[dict[str, Any]],
        matched_stocked: int,
        matched_direct: int,
        unmatched: int,
    ) -> None:
        self.supplier = supplier
        self.delivery_note_no = delivery_note_no
        self.arrived_date = arrived_date
        self.remark = remark
        self.mode = mode
        self.target_dept = target_dept
        self.items = items
        self.matched_names = matched_names
        self.low_confidences = low_confidences
        self.match_summary = match_summary
        self.rows_raw = rows_raw
        self.matched_stocked = matched_stocked
        self.matched_direct = matched_direct
        self.unmatched = unmatched

    def ocr_result(self) -> dict[str, Any]:
        """留痕 JSON（与 build_ocr_draft 直落草稿口径逐字段一致）。"""
        return {
            "supplier": self.supplier,
            "delivery_note_no": self.delivery_note_no,
            "arrived_date": self.arrived_date,
            "remark": self.remark,
            "rows": self.rows_raw,
            "match_summary": self.match_summary,
        }


async def parse_receipt_image(
    db: AsyncSession,
    *,
    image_b64: str,
    content_type: str = "image/jpeg",
) -> ParsedReceipt:
    """图片 → 识别 → 四级匹配 → 结构化解析结果（**不写任何库表**）。

    供「上传截图自动填写单据」预填表单；异常口径与 build_ocr_draft 一致
    （ScenarioDisabled / ValueError 空行 / LLM 失败原样上抛）。
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
        raise ValueError("未识别到物料行（图片可能不是送货单，请用手动填写）")

    # ③ 四级匹配 + 行分类（stocked/direct）
    materials = await load_active_materials(db)
    match_summary: list[dict[str, Any]] = []
    items: list[ReceiptItemIn] = []
    matched_names: list[str | None] = []
    low_confidences: list[bool] = []
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
        matched_names.append(result.material.name if result.material else None)
        low_confidences.append(result.low_confidence)
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

    return ParsedReceipt(
        supplier=recognized.supplier,
        delivery_note_no=recognized.delivery_note_no,
        arrived_date=recognized.arrived_date,
        remark=recognized.remark,
        mode=mode,
        target_dept=None if mode == "stocked" else _guess_dept(recognized.remark),
        items=items,
        matched_names=matched_names,
        low_confidences=low_confidences,
        match_summary=match_summary,
        rows_raw=[r.model_dump() for r in recognized.rows],
        matched_stocked=matched_stocked,
        matched_direct=matched_direct,
        unmatched=unmatched,
    )


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
    parsed = await parse_receipt_image(db, image_b64=image_b64, content_type=content_type)

    payload = ReceiptCreate(
        source="ocr",
        mode=parsed.mode,  # type: ignore[arg-type]
        supplier_name=parsed.supplier,
        delivery_note_no=parsed.delivery_note_no,
        arrived_at=_parse_arrived(parsed.arrived_date) or datetime.now(CN_TZ),
        target_dept=parsed.target_dept,
        attachments=(
            [{"kind": "delivery_note_photo", "file_token": source_image_token}]
            if source_image_token
            else None
        ),
        items=parsed.items,
    )
    receipt = await hw_service.create_receipt(db, payload)

    # ocr_result JSON 留痕（原样提取 + 逐行匹配置信度，设计 §2.3）
    receipt.ocr_result = parsed.ocr_result()
    await db.flush()

    summary = {
        "receipt_id": str(receipt.id),
        "receipt_no": receipt.receipt_no,
        "mode": parsed.mode,
        "matched_stocked": parsed.matched_stocked,
        "matched_direct": parsed.matched_direct,
        "unmatched": parsed.unmatched,
        "rows": parsed.match_summary,
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
    """从备注猜直发车间。

    两级：①台账五部门桶名（发酵/提炼一期/…）子串优先——与月度需求列对齐；
    ②真实组织名捕获——送货单备注里常见「提五机修/环保工程中心/电工班组」
    这类全称或简称，按组织后缀正则截取原样返回（target_dept 是自由文本
    展示列，不强制枚举）。识别不到返回 None，由仓管员确认时补（accept
    侧强制非空，schema 建单不再拦截）。
    """
    import re

    from app.modules.warehouse.hardware.models import DEMAND_DEPARTMENTS

    if not remark:
        return None
    for dept in DEMAND_DEPARTMENTS:
        if dept in remark:
            return dept
    m = re.search(
        r"[\u4e00-\u9fa5]{2,12}?(?:工程[一二三四五六七八]部|部|车间|机修|班组|中心)",
        remark,
    )
    return m.group(0) if m else None
