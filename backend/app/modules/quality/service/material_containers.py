"""物料容器赋码业务编排：批量赋码、进出库流转、标签 PDF。"""

import io
import uuid
from datetime import datetime

import segno
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.time import today as _today
from app.modules.quality.models import (
    QualityMaterialContainer,
)
from app.modules.quality.repository import (
    create_container_movement,
    create_material_containers,
    get_material_container_by_no,
    list_containers_by_nos,
    max_container_seq,
    update_container_status,
)
from app.modules.quality.schemas import (
    ContainerBatchMoveRequest,
    ContainerMoveRequest,
    MaterialContainerGenerateRequest,
)

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

# 状态流转白名单（阶段1人工操作；后续接入请验/放行后自动联动）
_MOVE_TRANSITIONS: dict[str, dict[str, str]] = {
    # op_type -> {from_status: to_status}
    "in": {"labeled": "in_warehouse", "returned": "in_warehouse"},
    "out": {"in_warehouse": "issued", "qualified": "issued"},
    "return": {"issued": "returned"},
}
_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "in_warehouse": {"labeled"},
    "qualified": {"in_warehouse"},
    "void": {"labeled", "in_warehouse"},
}


def _qr_content(container: QualityMaterialContainer) -> str:
    """二维码富文本内容：容器号首行（机器可解析），后续行供手机扫码直接阅读。"""
    lines = [container.container_no, container.material_name]
    if container.inbound_batch_no:
        lines.append(f"批号:{container.inbound_batch_no}")
    if container.expiry_date:
        lines.append(f"复验期:{container.expiry_date}")
    return "\n".join(lines)


class MaterialContainerService:
    """物料容器：赋码/进出库/标签。"""

    @staticmethod
    def _prefix(material_code: str, date_str: str) -> str:
        return f"MC-{material_code}-{date_str}-"

    @staticmethod
    async def generate_containers(
        db: AsyncSession,
        payload: MaterialContainerGenerateRequest,
        issued_by: uuid.UUID | None = None,
    ) -> list[QualityMaterialContainer]:
        """批量赋码：连续容器号 MC-{物料代码}-{YYYYMMDD}-{4位流水}。

        流水从该前缀已有最大值续起；唯一索引兜底并发撞号（异常时重试一次）。
        """
        code = payload.material_code.strip()
        if not code or "/" in code or " " in code:
            raise AppException(status_code=400, detail="物料代码不能为空且不能含空格/斜杠")
        date_str = datetime.now().strftime("%Y%m%d")
        prefix = MaterialContainerService._prefix(code, date_str)
        start = await max_container_seq(db, prefix)
        rows = []
        for i in range(payload.count):
            rows.append({
                "container_no": f"{prefix}{start + i + 1:04d}",
                "material_code": code,
                "material_name": payload.material_name,
                "vendor_code": payload.vendor_code,
                "inbound_batch_no": payload.inbound_batch_no,
                "expiry_date": payload.expiry_date,
                "seq": start + i + 1,
                "status": "labeled",
                "qr_issued_by": issued_by,
            })
        try:
            return await create_material_containers(db, rows)
        except Exception:
            # 并发撞号：唯一索引拦截后重试一次（重新取最大值）
            await db.rollback()
            start = await max_container_seq(db, prefix)
            for i, row in enumerate(rows):
                row["container_no"] = f"{prefix}{start + i + 1:04d}"
                row["seq"] = start + i + 1
            return await create_material_containers(db, rows)

    @staticmethod
    async def move_container(
        db: AsyncSession,
        container_no: str,
        payload: ContainerMoveRequest,
        operator: uuid.UUID | None = None,
    ) -> QualityMaterialContainer:
        """进出库：in 入库登记 / out 领料出库 / auto 按状态自动判定。非法流转或过期出库 400。"""
        container = await get_material_container_by_no(db, container_no)
        if container is None:
            raise AppException(status_code=404, detail=f"容器 {container_no} 不存在")
        if payload.op_type == "auto":
            resolved = {"labeled": "in", "in_warehouse": "out", "qualified": "out"}.get(container.status)
            if resolved is None:
                raise AppException(
                    status_code=400,
                    detail=f"容器状态为 {container.status}，无法自动判定操作（已领出/已退库/已作废需人工处理）",
                )
            payload = ContainerMoveRequest(
                op_type=resolved, related_doc=payload.related_doc, remark=payload.remark,
            )
        to_status = _MOVE_TRANSITIONS[payload.op_type].get(container.status)
        if to_status is None:
            raise AppException(
                status_code=400,
                detail=f"容器状态为 {container.status}，不可执行{('入库' if payload.op_type == 'in' else '出库')}操作",
            )
        if payload.op_type == "out" and container.expiry_date and container.expiry_date < _today().isoformat():
            raise AppException(
                status_code=400,
                detail=f"容器 {container_no} 已过复验期（{container.expiry_date}），禁止出库",
            )
        from_status = container.status
        if payload.op_type == "in" and not container.inbound_date:
            container.inbound_date = _today().isoformat()
        updated = await update_container_status(db, container.id, to_status)
        await create_container_movement(
            db,
            container_id=container.id,
            container_no=container_no,
            op_type=payload.op_type,
            from_status=from_status,
            to_status=to_status,
            operator=operator,
            related_doc=payload.related_doc,
            remark=payload.remark,
        )
        return updated  # type: ignore[return-value]

    @staticmethod
    async def batch_move(
        db: AsyncSession,
        payload: ContainerBatchMoveRequest,
        operator: uuid.UUID | None = None,
    ) -> list[dict[str, object]]:
        """批量进出库：逐容器独立校验，单个失败不影响其余，结果逐条返回。"""
        results: list[dict[str, object]] = []
        for no in payload.container_nos:
            try:
                updated = await MaterialContainerService.move_container(
                    db,
                    no,
                    ContainerMoveRequest(
                        op_type=payload.op_type,
                        related_doc=payload.related_doc,
                        remark=payload.remark,
                    ),
                    operator=operator,
                )
                results.append({"container_no": no, "ok": True, "status": updated.status})
            except AppException as exc:
                results.append({"container_no": no, "ok": False, "detail": exc.detail})
        return results

    @staticmethod
    async def update_status(
        db: AsyncSession,
        container_no: str,
        new_status: str,
        operator: uuid.UUID | None = None,
        remark: str | None = None,
    ) -> QualityMaterialContainer:
        """人工状态流转（阶段1：手动合格/作废；后续由请验/放行联动取代）。"""
        container = await get_material_container_by_no(db, container_no)
        if container is None:
            raise AppException(status_code=404, detail=f"容器 {container_no} 不存在")
        allowed = _STATUS_TRANSITIONS.get(new_status, set())
        if container.status not in allowed:
            raise AppException(
                status_code=400,
                detail=f"容器状态 {container.status} 不可变更为 {new_status}",
            )
        updated = await update_container_status(db, container.id, new_status)
        await create_container_movement(
            db,
            container_id=container.id,
            container_no=container_no,
            op_type="status",
            from_status=container.status,
            to_status=new_status,
            operator=operator,
            remark=remark or "阶段1人工流转",
        )
        return updated  # type: ignore[return-value]

    @staticmethod
    async def purchase_suggestions(db: AsyncSession) -> list[dict[str, object]]:
        """采购建议：字典里设了安全库存阈值且可用库存低于阈值的物料。

        可用库存 = 在库待验 + 合格；字典有阈值但从未赋码的物料可用按 0 计。
        """
        from app.modules.quality.repository import (
            list_materials,
            material_stock_summary,
        )

        materials, _total = await list_materials(db, page_size=500)
        summary = {s["material_code"]: s for s in await material_stock_summary(db)}
        result: list[dict[str, object]] = []
        for material in materials:
            if material.min_stock is None:
                continue
            available = summary.get(material.code, {}).get("available", 0)
            if int(available) < int(material.min_stock):
                result.append({
                    "material_code": material.code,
                    "material_name": material.name,
                    "vendor_name": material.vendor_name,
                    "pack_spec": material.pack_spec,
                    "available": int(available),
                    "min_stock": int(material.min_stock),
                    "gap": int(material.min_stock) - int(available),
                })
        return result

    @staticmethod
    async def build_label_pdf(
        db: AsyncSession, container_nos: list[str]
    ) -> bytes:
        """批量标签：A4 不干胶 2列×4行，每格=二维码+物料名/代码/批号/容器号/复验期。"""
        containers = await list_containers_by_nos(db, container_nos)
        if not containers:
            raise AppException(status_code=404, detail="未找到任何有效容器")
        by_no = {c.container_no: c for c in containers}
        ordered = [by_no[n] for n in container_nos if n in by_no]

        buf = io.BytesIO()
        pdf = canvas.Canvas(buf, pagesize=A4)
        page_w, page_h = A4
        margin = 12 * mm
        cols, rows = 2, 4
        cell_w = (page_w - margin * 2) / cols
        cell_h = (page_h - margin * 2) / rows

        def draw_label(pdf_cv: canvas.Canvas, c: QualityMaterialContainer, x: float, y: float) -> None:
            qr_img = io.BytesIO()
            segno.make(_qr_content(c), error="m").save(qr_img, kind="png", scale=6, border=1)
            qr_img.seek(0)
            qr_size = min(cell_h * 0.52, cell_w * 0.4)
            pdf_cv.drawImage(
                ImageReader(qr_img), x + 4 * mm, y + cell_h - qr_size - 4 * mm,
                width=qr_size, height=qr_size,
            )
            text_x = x + qr_size + 8 * mm
            top = y + cell_h - 8 * mm
            lines = [
                c.material_name,
                f"代码:{c.material_code}",
                f"批号:{c.inbound_batch_no}",
                f"编号:{c.container_no}",
                f"复验期:{c.expiry_date or '-'}",
            ]
            for k, line in enumerate(lines):
                # 编号等长行自动缩字号防溢出（此前截断 20 字符导致末段编号被切掉）
                size = 9 if len(line) <= 20 else 8
                pdf_cv.setFont("STSong-Light", size)
                pdf_cv.drawString(text_x, top - k * 5.5 * mm, line)
            # 分隔线
            pdf_cv.setStrokeGray(0.7)
            pdf_cv.rect(x + 1.5 * mm, y + 1.5 * mm, cell_w - 3 * mm, cell_h - 3 * mm)

        idx = 0
        while idx < len(ordered):
            for r in range(rows):
                for col in range(cols):
                    if idx >= len(ordered):
                        break
                    x = margin + col * cell_w
                    y = page_h - margin - (r + 1) * cell_h
                    draw_label(pdf, ordered[idx], x, y)
                    idx += 1
            pdf.showPage()
        pdf.save()
        return buf.getvalue()


material_container_service = MaterialContainerService()
