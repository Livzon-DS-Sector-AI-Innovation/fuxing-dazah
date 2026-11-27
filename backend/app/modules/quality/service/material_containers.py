"""物料容器赋码业务编排：批量赋码、进出库流转、标签 PDF。"""

import io
import uuid
from datetime import datetime
from typing import Any

import segno
from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
from reportlab.lib.units import mm  # type: ignore[import-untyped]
from reportlab.lib.utils import ImageReader  # type: ignore[import-untyped]
from reportlab.pdfbase import pdfmetrics  # type: ignore[import-untyped]
from reportlab.pdfbase.cidfonts import UnicodeCIDFont  # type: ignore[import-untyped]
from reportlab.pdfgen import canvas  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.core.time import today as _today
from app.modules.quality.models import (
    QualityMaterialContainer,
    QualityMaterialRequest,
    QualityStocktakeItem,
    QualityStocktakeSheet,
    QualityTestTask,
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
        # 挂单校验：请验单存在、物料一致、尚未结单（放行/拒收/让步/作废后不可再挂）
        if payload.material_request_id:
            from app.modules.quality.repository import get_material_request

            req = await get_material_request(db, payload.material_request_id)
            if req is None:
                raise AppException(status_code=404, detail="请验单不存在")
            if req.material_code != code:
                raise AppException(status_code=400, detail=f"请验单物料 {req.material_code} 与赋码物料 {code} 不一致")
            if req.status in ("released", "rejected", "conceded", "void"):
                raise AppException(status_code=400, detail=f"请验单已结单（{req.status}），不可再挂单")
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
                "material_request_id": payload.material_request_id,
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
    async def create_stocktake(
        db: AsyncSession,
        scope_material_code: str | None,
        remark: str | None,
    ) -> QualityStocktakeSheet:
        """创建盘点单：盘点口径=在库待验+合格（实物在库）。"""
        from app.modules.quality.repository import (
            create_stocktake_sheet,
            list_in_stock_containers,
            max_stocktake_seq,
        )

        date_str = datetime.now().strftime("%Y%m%d")
        prefix = f"ST-{date_str}-"
        seq = await max_stocktake_seq(db, prefix)
        expected = await list_in_stock_containers(db, scope_material_code)
        sheet = await create_stocktake_sheet(db, {
            "sheet_no": f"{prefix}{seq + 1:04d}",
            "scope_material_code": scope_material_code,
            "status": "in_progress",
            "remark": remark,
            "expected_count": len(expected),
        })
        return sheet

    @staticmethod
    async def scan_stocktake(
        db: AsyncSession,
        sheet_id: uuid.UUID,
        container_no: str,
        operator: uuid.UUID | None = None,
    ) -> QualityStocktakeItem:
        """盘点扫码：分类记录（在库匹配/系统有但不在库/系统不存在），重复扫描 409。"""
        from app.modules.quality.repository import (
            create_stocktake_item,
            get_material_container_by_no,
            get_stocktake_item,
            get_stocktake_sheet,
        )

        sheet = await get_stocktake_sheet(db, sheet_id)
        if sheet is None:
            raise AppException(status_code=404, detail="盘点单不存在")
        if sheet.status != "in_progress":
            raise AppException(status_code=400, detail=f"盘点单状态为 {sheet.status}，不可扫码")
        if await get_stocktake_item(db, sheet_id, container_no):
            raise AppException(status_code=409, detail=f"容器 {container_no} 已盘点过")
        container = await get_material_container_by_no(db, container_no)
        if container is None:
            result, snapshot, mcode, mname = "not_found", None, None, None
        elif container.status in ("in_warehouse", "qualified"):
            result, snapshot, mcode, mname = "matched", container.status, container.material_code, container.material_name
        else:
            result, snapshot, mcode, mname = "out_of_scope", container.status, container.material_code, container.material_name
        item = await create_stocktake_item(db, {
            "sheet_id": sheet_id,
            "container_no": container_no,
            "result": result,
            "status_snapshot": snapshot,
            "material_code": mcode,
            "material_name": mname,
            "scanned_by": operator,
        })
        sheet.scanned_count += 1
        await db.flush()
        return item

    @staticmethod
    async def finish_stocktake(db: AsyncSession, sheet_id: uuid.UUID) -> QualityStocktakeSheet:
        """结束盘点：计算盘亏（在库未扫到）与盘盈（扫到但不在库/不存在）。"""
        from app.modules.quality.repository import (
            get_stocktake_sheet,
            list_in_stock_containers,
            list_stocktake_items,
        )

        sheet = await get_stocktake_sheet(db, sheet_id)
        if sheet is None:
            raise AppException(status_code=404, detail="盘点单不存在")
        if sheet.status != "in_progress":
            raise AppException(status_code=400, detail=f"盘点单状态为 {sheet.status}，不可结束")
        expected = {c.container_no for c in await list_in_stock_containers(db, sheet.scope_material_code)}
        items = await list_stocktake_items(db, sheet_id)
        scanned = {i.container_no for i in items}
        sheet.expected_count = len(expected)
        sheet.missing_count = len(expected - scanned)
        sheet.extra_count = sum(1 for i in items if i.result == "out_of_scope")
        sheet.anomaly_count = sum(1 for i in items if i.result == "not_found")
        sheet.status = "completed"
        await db.flush()
        stmt = select(QualityStocktakeSheet).where(QualityStocktakeSheet.id == sheet_id)
        return (await db.execute(stmt)).scalar_one()
    # ── 物料请验 / 检验 / 放行 ──

    @staticmethod
    async def create_request(
        db: AsyncSession, payload: Any, operator: uuid.UUID | None = None
    ) -> QualityMaterialRequest:
        """创建请验单：MR+YYMMDD+序号；物料/供应商信息从字典带出快照。"""
        from app.modules.quality.repository import (
            create_material_request,
            get_material_by_code,
            get_supplier_by_code,
            max_material_request_seq,
        )

        code = payload.material_code.strip()
        material = await get_material_by_code(db, code)
        if material is None:
            raise AppException(status_code=404, detail=f"物料代码 {code} 不在字典中，请先维护物料字典")
        vendor_name = material.vendor_name
        if payload.vendor_code:
            supplier = await get_supplier_by_code(db, payload.vendor_code.strip())
            if supplier is not None:
                vendor_name = supplier.name
        date_str = datetime.now().strftime("%Y%m%d")
        prefix = f"MR-{date_str}-"
        seq = await max_material_request_seq(db, prefix)
        return await create_material_request(db, {
            "request_no": f"{prefix}{seq + 1:04d}",
            "material_code": code,
            "material_name": material.name,
            "vendor_code": payload.vendor_code,
            "vendor_name": vendor_name,
            "inbound_batch_no": payload.inbound_batch_no.strip(),
            "inbound_qty": payload.inbound_qty,
            "inbound_date": payload.inbound_date,
            "status": "pending_sample",
        })

    @staticmethod
    async def sample_request(
        db: AsyncSession, request_id: uuid.UUID, payload: Any, operator: uuid.UUID | None = None
    ) -> QualityMaterialRequest:
        from app.modules.quality.repository import (
            get_material_request,
            update_material_request,
        )

        req = await get_material_request(db, request_id)
        if req is None:
            raise AppException(status_code=404, detail="请验单不存在")
        if req.status != "pending_sample":
            raise AppException(status_code=400, detail=f"请验单状态为 {req.status}，不可取样")
        return await update_material_request(db, request_id, {
            "status": "sampled",
            "sampled_at": payload.sampled_at or datetime.now().strftime("%Y-%m-%d"),
            "sampled_qty": payload.sampled_qty,
            "sampled_by": operator,
        })

    @staticmethod
    async def create_material_task(
        db: AsyncSession, request_id: uuid.UUID, operator: uuid.UUID | None = None
    ) -> QualityTestTask:
        """从物料标准快照检验项目行建物料检验任务（复用任务链路）。

        标准匹配：物料+供应商精确 → 物料通用（vendor 空）→ 无标准报错。
        任务行判定复用 QualityTestResult（judge_mode=auto/manual 由 operator 推导）。
        """
        from app.modules.quality.repository import (
            create_test_results,
            create_test_task,
            get_material_request,
            get_material_standard_by_key,
            list_material_standard_items,
            update_material_request,
        )

        req = await get_material_request(db, request_id)
        if req is None:
            raise AppException(status_code=404, detail="请验单不存在")
        if req.status not in ("sampled", "in_test"):
            raise AppException(status_code=400, detail=f"请验单状态为 {req.status}，需先取样")
        if req.task_id:
            from app.modules.quality.repository import get_test_task

            existing = await get_test_task(db, req.task_id)
            if existing and not existing.is_deleted:
                raise AppException(status_code=409, detail=f"该请验单已建检验任务（{existing.batch_number}）")
        std = await get_material_standard_by_key(db, req.material_code, req.vendor_code)
        if std is None and req.vendor_code:
            std = await get_material_standard_by_key(db, req.material_code, None)
        if std is None:
            raise AppException(status_code=404, detail=f"物料 {req.material_code} 无检验标准，请先维护物料标准库")
        items = await list_material_standard_items(db, std.id)
        if not items:
            raise AppException(status_code=400, detail="物料标准为空，请先添加检验项目行")
        task = await create_test_task(
            db,
            product_name=req.material_name,
            batch_number=req.inbound_batch_no,
            production_date=req.inbound_date,
            expiry_date=None,
            specification=None,
            form_id=None,
            standard_document_id=None,
        )
        task.task_kind = "material"
        task.material_request_id = request_id
        task.status = "in_progress"
        await db.flush()
        rows = []
        for item in items:
            judge_mode = "auto" if item.operator else "manual"
            rows.append({
                "standard_item_id": None,
                "seq": item.seq,
                "category": item.category,
                "item_name": item.item_name,
                "sop_no": item.sop_no,
                "standard_text": item.standard_text,
                "operator": item.operator,
                "limit_min": item.limit_min,
                "limit_max": item.limit_max,
                "method_source": item.method_source,
                "remark": item.remark,
                "judge_mode": judge_mode,
                "source": "material",
                "result_text": None,
                "result_value": None,
                "is_pass": None,
            })
        await create_test_results(db, task.id, rows)
        await update_material_request(db, request_id, {"status": "in_test", "task_id": task.id})
        return task

    @staticmethod
    async def release_request(
        db: AsyncSession, request_id: uuid.UUID, payload: Any, operator: uuid.UUID | None = None
    ) -> QualityMaterialRequest:
        """放行结论：release/reject/concede，联动该请验单全部容器状态。

        release → 容器转 qualified（已赋码/在库均可直接合格）
        reject → 容器作废冻结（void）
        concede → 视同可用转 qualified，结论留痕
        """
        from app.modules.quality.repository import (
            get_material_request,
            list_containers_by_request,
            update_container_status,
            update_material_request,
        )

        req = await get_material_request(db, request_id)
        if req is None:
            raise AppException(status_code=404, detail="请验单不存在")
        if req.status in ("released", "rejected", "conceded", "void"):
            raise AppException(status_code=400, detail=f"请验单状态为 {req.status}，已放行过")
        status_map = {"release": "released", "reject": "rejected", "concede": "conceded"}
        container_status = {"release": "qualified", "reject": "void", "concede": "qualified"}[payload.verdict]
        for c in await list_containers_by_request(db, request_id):
            await update_container_status(db, c.id, container_status)
        return await update_material_request(db, request_id, {
            "status": status_map[payload.verdict],
            "verdict": payload.verdict,
            "verdict_remark": payload.remark,
            "released_by": operator,
            "released_at": datetime.now().strftime("%Y-%m-%d"),
        })

    # ── Excel 批量导入 ──

    _DICT_COLUMNS = ["code", "name", "category", "vendor_name", "pack_spec", "min_stock", "valid_months", "remark"]
    _CONTAINER_COLUMNS = ["container_no", "material_code", "material_name", "vendor_code", "inbound_batch_no", "inbound_date", "expiry_date", "location", "status"]
    _VALID_STATUSES = {"labeled", "in_warehouse", "qualified", "issued", "returned", "void"}

    @staticmethod
    def _read_import_rows(content: bytes) -> list[dict[str, Any]]:
        """读取导入 Excel：首行表头，逐行转 dict（空行跳过）。"""
        import io as _io

        import openpyxl

        from app.modules.quality import lc_template_parser

        wb = openpyxl.load_workbook(_io.BytesIO(content))
        ws = lc_template_parser.active_sheet(wb)
        rows_iter = ws.iter_rows(values_only=True)
        header = next(rows_iter, None)
        if not header:
            raise AppException(status_code=400, detail="Excel 为空或缺少表头")
        columns = [str(h).strip() if h is not None else "" for h in header]
        data = []
        for raw in rows_iter:
            if not raw or all(v is None or str(v).strip() == "" for v in raw):
                continue
            row: dict[str, Any] = {}
            for idx, col in enumerate(columns):
                if not col or idx >= len(raw):
                    continue
                value = raw[idx]
                if value is None:
                    continue
                if isinstance(value, float) and value.is_integer() and col in ("min_stock", "valid_months"):
                    value = int(value)
                elif col in ("inbound_date", "expiry_date", "qual_expiry_date") and hasattr(value, "strftime"):
                    value = value.strftime("%Y-%m-%d")
                row[col] = str(value).strip() if not isinstance(value, int) else value
            data.append(row)
        return data

    @staticmethod
    async def import_dict_rows(db: AsyncSession, content: bytes) -> dict[str, Any]:
        """导入物料字典：逐行校验，代码已存在则跳过（保存点隔离，失败不影响其余）。"""
        from app.modules.quality.repository import create_material, get_material_by_code

        created: list[str] = []
        skipped: list[str] = []
        for row in MaterialContainerService._read_import_rows(content):
            code = str(row.get("code") or "").strip()
            name = str(row.get("name") or "").strip()
            if not code or not name:
                skipped.append(f"{code or '(空代码)'}:代码/名称缺失")
                continue
            if "/" in code or " " in code:
                skipped.append(f"{code}:代码含空格/斜杠")
                continue
            if await get_material_by_code(db, code):
                skipped.append(f"{code}:已存在")
                continue
            try:
                async with db.begin_nested():
                    await create_material(db, {
                        "code": code,
                        "name": name,
                        "category": (row.get("category") or None),
                        "vendor_name": (row.get("vendor_name") or None),
                        "pack_spec": (row.get("pack_spec") or None),
                        "min_stock": row.get("min_stock"),
                        "valid_months": row.get("valid_months"),
                        "remark": (row.get("remark") or None),
                    })
                created.append(code)
            except Exception:
                skipped.append(f"{code}:入库失败")
        return {"created": created, "skipped": skipped}

    @staticmethod
    async def import_container_rows(db: AsyncSession, content: bytes) -> dict[str, Any]:
        """导入存量容器：容器号重复跳过、状态非法跳过（保存点隔离）。"""
        from app.modules.quality.repository import (
            create_material_containers,
            get_material_container_by_no,
        )

        created: list[str] = []
        skipped: list[str] = []
        for row in MaterialContainerService._read_import_rows(content):
            no = str(row.get("container_no") or "").strip()
            status = str(row.get("status") or "labeled").strip() or "labeled"
            if not no:
                skipped.append("(空容器号):缺失")
                continue
            if not no.startswith("MC-"):
                skipped.append(f"{no}:容器号须以 MC- 开头")
                continue
            if status not in MaterialContainerService._VALID_STATUSES:
                skipped.append(f"{no}:状态非法({status})")
                continue
            if await get_material_container_by_no(db, no):
                skipped.append(f"{no}:已存在")
                continue
            try:
                seq_text = no.rsplit("-", 1)[-1]
                seq = int(seq_text) if seq_text.isdigit() else 0
                async with db.begin_nested():
                    rows = await create_material_containers(db, [{
                        "container_no": no,
                        "material_code": str(row.get("material_code") or "").strip() or "IMPORT",
                        "material_name": str(row.get("material_name") or "").strip() or "导入物料",
                        "vendor_code": (row.get("vendor_code") or None),
                        "inbound_batch_no": str(row.get("inbound_batch_no") or "").strip() or "-",
                        "inbound_date": (row.get("inbound_date") or None),
                        "expiry_date": (row.get("expiry_date") or None),
                        "location": (row.get("location") or None),
                        "seq": seq,
                        "status": status,
                    }])
                    rows[0].id  # 确保 RETURNING 生效
                created.append(no)
            except Exception:
                skipped.append(f"{no}:入库失败")
        return {"created": created, "skipped": skipped}

    @staticmethod
    def build_import_template(kind: str) -> bytes:
        """下载导入模板：dict / containers 两种表头 + 示例行。"""
        import io as _io

        import openpyxl

        from app.modules.quality import lc_template_parser

        wb = openpyxl.Workbook()
        ws = lc_template_parser.active_sheet(wb)
        if kind == "dict":
            ws.append(MaterialContainerService._DICT_COLUMNS)
            ws.append(["VAN", "盐酸万古霉素原料", "原料", "示例供应商", "5kg/听", 3, 24, "示例"])
        else:
            ws.append(MaterialContainerService._CONTAINER_COLUMNS)
            ws.append(["MC-VAN-20261010-0001", "VAN", "盐酸万古霉素原料", "SUP-001", "IN-20261010-01", "2026-10-10", "2028-10-09", "A-01-03", "in_warehouse"])
        buf = _io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

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
