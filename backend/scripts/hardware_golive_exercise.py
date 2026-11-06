"""五金库上线演练脚本（A1/A2/A4，2026-11-06）：真库真链三连。

子命令（backend/ 下运行，写 dev 库并 commit——演练数据留库供 UI 查看）：

- match       A1 stocked 四级匹配真库验证：492 项真主数据 × 口语/变体/同义词弹仓
- requisition A2 manual 领料全链 3 单：备库存→常规(通过发料)/超额/驳回释放+超卖闸
- erp         A4 ERP A 档全链：造导出 xlsx→导入→OCR 对账 verified/差异→防双计→重复导入幂等

用法：./.venv/bin/python -m scripts.hardware_golive_exercise match|requisition|erp
"""

from __future__ import annotations

import asyncio
import io
import sys
from decimal import Decimal

from sqlalchemy import select


def _fmt(res) -> str:
    if not res.material:
        return "MISS"
    return f"{res.method}({float(res.score):.2f})→{res.material.name[:18]}|{(res.material.spec or '')[:16]}"


async def ex_match() -> None:
    from app.modules.warehouse.hardware.matcher import match_one
    from app.modules.warehouse.hardware.receipt_pipeline import load_active_materials
    from app.core.database import async_session_factory

    cases = [
        # (说明, code, name, spec) —— 期望命中
        ("精确名+规格(球阀)", None, "304不锈钢球阀", "Q11F-16P DN8"),
        ("全称串(车间念法)", None, "304不锈钢球阀 Q11F-16P DN8", None),
        ("口语省品牌", None, "球阀", "DN8"),
        ("规格分隔符变体", None, "304不锈钢管", "φ8×2"),
        ("轴承逗号原样", None, "轴承,1305", "1305"),
        ("轴承纯型号", None, "轴承", "1305"),
        ("UPVC长规格截断", None, "UPVC管道", "dn20*2.0mm"),
        ("法兰口语", None, "304不锈钢法兰片", "DN15 PN16"),
        ("跨品类护栏(清单无止回阀)", None, "304不锈钢止回阀", "DN25"),
        ("垫片简称", None, "食品级硅胶快接垫片", "φ38"),
    ]
    async with async_session_factory() as db:
        materials = await load_active_materials(db)
        print(f"主数据 {len(materials)} 项（code 空=编码表未回填，L1 代码级命中暂不可测）")
        hit = guard_ok = 0
        for label, code, name, spec in cases:
            res = match_one(code=code, name=name, spec=spec, materials=materials)
            if label.startswith("跨品类护栏"):
                ok = res.material is None  # 护栏用例：期望拒配（清单无该品类）
                guard_ok += ok
            else:
                ok = res.material is not None
                hit += ok
            print(f"  [{'✓' if ok else '✗'}] {label}: {_fmt(res)}")
        expect_hit = sum(1 for c in cases if not c[0].startswith("跨品类护栏"))
        print(f"命中 {hit}/{expect_hit}；护栏拒配 {guard_ok}/{len(cases) - expect_hit}")


async def ex_requisition() -> None:
    from app.modules.warehouse.hardware import service as hw
    from app.modules.warehouse.hardware.models import HardwareMaterial
    from app.modules.warehouse.hardware.schemas import (
        ReceiptCreate,
        ReceiptItemIn,
        RequisitionCreate,
        RequisitionItemIn,
    )
    from app.core.database import async_session_factory

    async with async_session_factory() as db:
        mat = (
            await db.execute(
                select(HardwareMaterial)
                .where(HardwareMaterial.name == "304不锈钢球阀")
                .limit(1)
            )
        ).scalar_one_or_none()
        if not mat:
            sys.exit("未找到 304不锈钢球阀 主数据")
        mid = str(mat.id)

        async def stock_view() -> dict:
            s = await hw.get_material_stock(db, mat.id)
            return {k: str(v) for k, v in s.items() if k in ("on_hand", "reserved", "available")}

        # ── 备库存：manual 单 ×50 入账 ──
        rc = await hw.create_receipt(db, ReceiptCreate(
            source="manual", mode="stocked", supplier_name="上线演练供应商",
            delivery_note_no="GL-EX-001", remark="golive-exercise 演练数据",
            items=[ReceiptItemIn(material_id=mid, name="304不锈钢球阀", spec="Q11F-16P DN8", unit="台", quantity=Decimal("50"))],
        ))
        await hw.accept_receipt(db, rc.id, inspected_by_warehouse="演练仓管", inspected_by_dept="演练经办")
        await db.commit()
        print(f"备库存 {rc.receipt_no} 入账后: {await stock_view()}")

        # ── 单1 常规：提交(预扣)→主管批准→发料实扣 ──
        r1 = await hw.create_requisition(db, RequisitionCreate(
            dept_name="发酵", applicant="演练甲", purpose="golive 常规链",
            items=[RequisitionItemIn(material_id=mid, need_qty=Decimal("10"))],
        ))
        await hw.submit_requisition(db, r1.id)
        print(f"单1 {r1.req_no} 提交预扣后: {await stock_view()}")
        await hw.approve_requisition(db, r1.id, approver="演练主管")
        await hw.issue_requisition(db, r1.id, issued_by="演练仓管", received_by="演练甲")
        await db.commit()
        print(f"单1 发料实扣后:      {await stock_view()}（期望 on_hand=40 available=40）")

        # ── 单2 超额：excess 类型走完链（审批备注含生产总监提示） ──
        r2 = await hw.create_requisition(db, RequisitionCreate(
            dept_name="动力机修", applicant="演练乙", req_type="excess", purpose="golive 超额链",
            items=[RequisitionItemIn(material_id=mid, need_qty=Decimal("5"))],
        ))
        await hw.submit_requisition(db, r2.id)
        await hw.approve_requisition(db, r2.id, approver="演练主管", note="超额已报生产总监（演练）")
        await hw.issue_requisition(db, r2.id, issued_by="演练仓管", received_by="演练乙")
        await db.commit()
        print(f"单2 {r2.req_no} 超额全链后: {await stock_view()}（期望 on_hand=35）")

        # ── 单3 驳回：提交预扣→驳回释放 ──
        r3 = await hw.create_requisition(db, RequisitionCreate(
            dept_name="精制机修", applicant="演练丙", purpose="golive 驳回链",
            items=[RequisitionItemIn(material_id=mid, need_qty=Decimal("8"))],
        ))
        await hw.submit_requisition(db, r3.id)
        held = await stock_view()
        await hw.reject_requisition(db, r3.id, approver="演练主管", reason="演练驳回")
        await db.commit()
        released = await stock_view()
        print(f"单3 {r3.req_no} 驳回释放: {held} → {released}（期望 reserved 回落 8）")

        # ── 超卖闸：available=35 时申请 100 ──
        r4 = await hw.create_requisition(db, RequisitionCreate(
            dept_name="提炼一期", applicant="演练丁", purpose="golive 超卖闸",
            items=[RequisitionItemIn(material_id=mid, need_qty=Decimal("100"))],
        ))
        try:
            await hw.submit_requisition(db, r4.id)
            print("✗ 超卖闸未拦截！")
        except Exception as exc:
            await db.rollback()
            print(f"✓ 超卖闸拦截: {type(exc).__name__}: {str(exc)[:60]}")


async def ex_erp() -> None:
    import openpyxl

    from app.modules.warehouse.hardware import service as hw
    from app.modules.warehouse.hardware.erp_import import import_erp_file
    from app.modules.warehouse.hardware.models import HardwareMaterial, HardwareReceipt
    from app.modules.warehouse.hardware.schemas import ReceiptCreate, ReceiptItemIn
    from app.core.database import async_session_factory
    from sqlalchemy import func, select as sa_select

    async with async_session_factory() as db:
        # 备一个已入账 OCR 侧单（对账匹配目标）：球阀 ×12
        mat = (
            await db.execute(
                sa_select(HardwareMaterial).where(HardwareMaterial.name == "304不锈钢球阀").limit(1)
            )
        ).scalar_one()
        rc = await hw.create_receipt(db, ReceiptCreate(
            source="manual", mode="stocked", supplier_name="演练ERP对账供应商",
            delivery_note_no="GL-ERP-001", remark="golive-exercise erp 对账目标",
            items=[ReceiptItemIn(material_id=str(mat.id), name="304不锈钢球阀", spec="Q11F-16P DN8", unit="台", quantity=Decimal("12"))],
        ))
        await hw.accept_receipt(db, rc.id, inspected_by_warehouse="演练仓管", inspected_by_dept="演练经办")
        await db.commit()

        # 造导出文件：A=镜像单（应 verified）；B=孤行（应差异）
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["单据号", "日期", "供应商", "物料编码", "品名", "规格型号", "数量", "单位", "部门"])
        ws.append(["GL-ERP-DOC-A", "2026-11-06", "演练ERP对账供应商", None, "304不锈钢球阀", "Q11F-16P DN8", 12, "台", "发酵"])
        ws.append(["GL-ERP-DOC-B", "2026-11-06", "从未到货供应商", None, "304不锈钢弯头", "DN25", 6, "个", "提炼一期"])
        buf = io.BytesIO(); wb.save(buf); data = buf.getvalue()

        result = await import_erp_file(db, data=data, filename="演练ERP导出.xlsx", operator="golive")
        await db.commit()
        rec = result.get("reconcile", {})
        print(f"导入: 新建 {result.get('created', '?')} 单 / 跳过 {result.get('skipped', '?')}；"
              f"对账 matched={rec.get('matched')} unmatched={rec.get('unmatched')}（期望 1/1）")

        # 防双计：verified ERP 草稿禁止再入账
        erp_a = (
            await db.execute(
                sa_select(HardwareReceipt).where(HardwareReceipt.erp_doc_no == "GL-ERP-DOC-A")
            )
        ).scalar_one()
        try:
            await hw.accept_receipt(db, erp_a.id, inspected_by_warehouse="x", inspected_by_dept="y")
            print("✗ 防双计未拦截！")
        except Exception as exc:
            await db.rollback()
            print(f"✓ 防双计拦截: {str(exc)[:70]}")

        # 重复导入幂等
        again = await import_erp_file(db, data=data, filename="演练ERP导出.xlsx", operator="golive")
        await db.commit()
        print(f"重复导入: created={again.get('created')} skipped={again.get('skipped')}（期望 0/2）")

        n = (await db.execute(sa_select(func.count()).select_from(HardwareReceipt).where(HardwareReceipt.erp_doc_no == "GL-ERP-DOC-A"))).scalar_one()
        print(f"库内 GL-ERP-DOC-A 行数={n}（期望 1）")


async def ex_cleanup() -> None:
    """清理演练提交数据（按标识符精准删：GL-EX/GL-ERP 单号 + 演练申请人）。

    ⚠️ 只删本脚本 requisition/erp 子命令产生的行；四张真实送货单冒烟草稿
    （created_by=smoke-*）不在此列，保留供入库台复核。
    """
    from sqlalchemy import delete, select
    from app.modules.warehouse.hardware.models import (
        HardwareMovement,
        HardwareReceipt,
        HardwareReceiptItem,
        HardwareRequisition,
        HardwareRequisitionItem,
    )
    from app.core.database import async_session_factory

    async with async_session_factory() as db:
        rec_ids = (
            await db.execute(
                select(HardwareReceipt.id).where(
                    HardwareReceipt.delivery_note_no.in_(["GL-EX-001", "GL-ERP-001"])
                    | HardwareReceipt.erp_doc_no.like("GL-ERP-DOC-%")
                )
            )
        ).scalars().all()
        req_ids = (
            await db.execute(
                select(HardwareRequisition.id).where(
                    HardwareRequisition.applicant.like("演练%")
                )
            )
        ).scalars().all()
        if rec_ids:
            await db.execute(delete(HardwareMovement).where(
                HardwareMovement.lot_id.in_(
                    select(HardwareReceiptItem.id).where(
                        HardwareReceiptItem.receipt_id.in_(rec_ids)
                    )
                )
            ))
            await db.execute(delete(HardwareMovement).where(
                HardwareMovement.ref_id.in_(rec_ids)
            ))
            await db.execute(delete(HardwareReceiptItem).where(
                HardwareReceiptItem.receipt_id.in_(rec_ids)
            ))
            await db.execute(delete(HardwareReceipt).where(HardwareReceipt.id.in_(rec_ids)))
        if req_ids:
            await db.execute(delete(HardwareMovement).where(
                HardwareMovement.ref_id.in_(req_ids)
            ))
            await db.execute(delete(HardwareRequisitionItem).where(
                HardwareRequisitionItem.requisition_id.in_(req_ids)
            ))
            await db.execute(delete(HardwareRequisition).where(
                HardwareRequisition.id.in_(req_ids)
            ))
        await db.commit()
        print(f"已清理：入库单 {len(rec_ids)} 张 / 领料单 {len(req_ids)} 张（流水/明细随删）")


async def main(cmd: str) -> None:
    fn = {
        "match": ex_match,
        "requisition": ex_requisition,
        "erp": ex_erp,
        "cleanup": ex_cleanup,
    }.get(cmd)
    if not fn:
        sys.exit(f"未知子命令 {cmd}（match|requisition|erp|cleanup）")
    await fn()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else ""))
