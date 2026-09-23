"""Quality 业务逻辑编排。"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.quality.models import (
    QualityTestResult,
    QualityTestTask,
)
from app.modules.quality.repository import (
    create_task_review,
    create_test_results,
    create_test_task,
    delete_test_result,
    delete_test_task,
    get_test_task,
    get_test_task_by_batch,
    list_standard_documents_by_product,
    list_standard_items,
    list_task_reviews,
    list_test_results,
    soft_delete_task_reviews,
    update_test_results_fill,
    update_test_task,
    update_test_task_report_date,
)
from app.modules.quality.schemas import (
    TestResultCreate,
    TestResultOut,
    TestResultsUpdate,
    TestTaskCreate,
    TestTaskDetail,
    TestTaskReportDateUpdate,
    TestTaskStatusUpdate,
)
from app.modules.quality.service.helpers import _norm_date_str, spawn_background
from app.modules.quality.service.task_core import _TaskCore

logger = logging.getLogger(__name__)


class _TaskLifecycle(_TaskCore):
    """检验任务生命周期：建任务/填报/复核/状态流转/删除。"""
    @staticmethod
    async def create_task(db: AsyncSession, payload: TestTaskCreate) -> TestTaskDetail:
        existing = await get_test_task_by_batch(db, payload.product_name, payload.batch_number)
        if existing:
            raise AppException(
                status_code=409,
                detail=f"该产品+批号已存在检验任务（任务ID: {existing.id}），请直接进入该任务继续填报",
            )
        # 批号必然含产品代号：先按批号开头收敛到该代号的标准文档，再快照项目行
        product_docs = await list_standard_documents_by_product(db, payload.product_name)
        if not product_docs:
            raise AppException(
                status_code=400,
                detail=f"未找到产品「{payload.product_name}」的质量标准文档，请先在产品标准中导入",
            )
        code, docs = _TaskLifecycle._match_docs_by_batch_code(product_docs, payload.batch_number)
        if not docs:
            known = "、".join(
                sorted({(d.product_code or "").strip() for d in product_docs if (d.product_code or "").strip()})
            ) or "未配置"
            raise AppException(
                status_code=400,
                detail=f"批号「{payload.batch_number}」开头未匹配到产品「{payload.product_name}」的产品代号"
                f"（标准库代号：{known}），请核对批号",
            )
        # 标准文件可多选（一个批号可开多份报告单）；全部必须属于批号识别的代号
        requested_ids: list[uuid.UUID] = list(payload.standard_document_ids or [])
        if not requested_ids and payload.standard_document_id:
            requested_ids = [payload.standard_document_id]
        if requested_ids:
            valid_ids = {d.id for d in docs}
            if any(rid not in valid_ids for rid in requested_ids):
                raise AppException(
                    status_code=400,
                    detail=f"选中的标准文件与批号代号「{code}」不匹配，请勿混用其他代号的标准",
                )
            docs = [d for d in docs if d.id in requested_ids]
        std_items = []
        for d in docs:
            std_items.extend(await list_standard_items(db, d.id))
        if not std_items:
            raise AppException(status_code=400, detail="该产品标准文档没有项目行，无法创建任务")
        # 指定了选中项目时只快照选中的（检阅当日要用的具体 SOP）
        if payload.standard_item_ids:
            wanted = set(payload.standard_item_ids)
            valid_ids = {it.id for it in std_items}
            missing = wanted - valid_ids
            if missing:
                raise AppException(
                    status_code=400,
                    detail=f"有 {len(missing)} 个标准行不属于产品「{payload.product_name}」代号「{code}」的标准，请重新勾选",
                )
            std_items = [it for it in std_items if it.id in wanted]
            if not std_items:
                raise AppException(status_code=400, detail="未选中任何检验项目")

        # 日期分隔符归一化：支持 2026.01.01 / 2026/01/01 等写法
        production_date = _norm_date_str(payload.production_date)
        report_date = _norm_date_str(payload.report_date)
        # 效期：未显式指定时按主标准文档有效期自动计算（生产日期+x年-1天）
        expiry_date = _norm_date_str(payload.expiry_date) or _TaskLifecycle._calc_expiry(
            production_date, docs[0].valid_years
        )
        task = await create_test_task(
            db,
            product_name=payload.product_name,
            batch_number=payload.batch_number,
            production_date=production_date,
            expiry_date=expiry_date,
            specification=payload.specification,
            form_id=payload.form_id,
            standard_document_id=docs[0].id,
            report_date=report_date,
        )
        # 按 (sop_no, item_name) 去重（多个子项目可共用同一 SOP 号；防跨文档重复）
        seen_keys: set[tuple[str, str]] = set()
        snapshot = []
        for it in std_items:
            key = (it.sop_no or "", it.item_name)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            snapshot.append({
                "standard_item_id": it.id,
                "seq": it.seq,
                "category": it.category,
                "item_name": it.item_name,
                "sop_no": it.sop_no,
                "standard_text": it.standard_text,
                "operator": it.operator,
                "limit_min": it.limit_min,
                "limit_max": it.limit_max,
                "method_source": it.method_source,
                "remark": it.remark,
                "judge_mode": _TaskLifecycle._infer_judge_mode(it.operator, it.limit_min, it.limit_max),
                "source": "manual",
            })
        rows = await create_test_results(db, task.id, snapshot)
        # 默认判定规则：文字呈现项目（细菌内毒素→符合规定）与默认未检出（EDTA→未检出）自动填好
        for r in rows:
            default_text = _TaskLifecycle._DEFAULT_FILL_RULES.get(
                _TaskLifecycle._norm_name(r.item_name)
            )
            if default_text and r.is_pass is None:
                r.result_text = default_text
                r.is_pass = True
                r.source = "manual"
                r.filled_at = datetime.now(UTC)
        if rows:
            await db.flush()
        # 飞书推送：仅当出报日期为今天时推送提醒+填报卡片（门控在 notify_task_created 内）
        try:
            from app.modules.quality.feishu.fill_service import notify_task_created

            spawn_background(notify_task_created(str(task.id)))
        except Exception:
            logger.exception("飞书任务推送失败")
        return _TaskLifecycle._to_detail(task, rows)

    # ─── 批量填报 ───

    @staticmethod
    async def update_results(
        db: AsyncSession,
        task_id: uuid.UUID,
        payload: TestResultsUpdate,
        filled_by: uuid.UUID | None = None,
    ) -> TestTaskDetail:
        task = await get_test_task(db, task_id)
        if not task:
            raise AppException(status_code=404, detail="检验任务不存在")
        if task.status != "in_progress":
            raise AppException(status_code=400, detail=f"任务状态为 {task.status}，不可填报")

        rows = await list_test_results(db, task_id)
        by_id = {r.id: r for r in rows}
        now = datetime.now(UTC)
        updates: list[dict[str, Any]] = []
        for fill in payload.results:
            row = by_id.get(fill.result_id)
            if row is None:
                raise AppException(status_code=400, detail=f"结果行不存在或不属于该任务：{fill.result_id}")
            if row.judge_mode == "auto":
                if fill.result_value is None:
                    raise AppException(status_code=400, detail=f"项目「{row.item_name}」为数值型，请填写结果值")
                verdict = _TaskLifecycle._judge_value(
                    row.operator, row.limit_min, row.limit_max, fill.result_value
                )
                if verdict is None:
                    if fill.is_pass is None:
                        raise AppException(
                            status_code=400,
                            detail=f"项目「{row.item_name}」标准限度缺失，无法自动判定，请人工判定 is_pass",
                        )
                    verdict = fill.is_pass
                updates.append({
                    "result_id": row.id,
                    "result_text": fill.result_text,
                    "result_value": fill.result_value,
                    "is_pass": verdict,
                    "filled_by": filled_by,
                    "filled_at": now,
                })
            else:  # manual：文字型人工判定
                if fill.is_pass is None:
                    raise AppException(status_code=400, detail=f"项目「{row.item_name}」为文字型，请人工判定（is_pass）")
                updates.append({
                    "result_id": row.id,
                    "result_text": fill.result_text,
                    "result_value": fill.result_value,
                    "is_pass": fill.is_pass,
                    "filled_by": filled_by,
                    "filled_at": now,
                })
        await update_test_results_fill(db, updates)
        # 全部判定完成后自动进入待复核
        await _TaskLifecycle.auto_advance_pending_review(db, task_id)
        return _TaskLifecycle._to_detail(task, await list_test_results(db, task_id))

    # ── 待复核自动流转 ──

    @staticmethod
    async def auto_advance_pending_review(db: AsyncSession, task_id: uuid.UUID) -> bool:
        """填报中的任务全部结果行已判定时，自动流转为待复核（专员审核）。"""
        task = await get_test_task(db, task_id)
        if not task or task.status != "in_progress":
            return False
        rows = await list_test_results(db, task_id)
        # 默认判定规则先自动补填（细菌内毒素→符合规定、EDTA→未检出）
        changed = False
        for r in rows:
            default_text = _TaskLifecycle._DEFAULT_FILL_RULES.get(
                _TaskLifecycle._norm_name(r.item_name)
            )
            if default_text and r.is_pass is None:
                r.result_text = default_text
                r.is_pass = True
                r.source = "manual"
                r.filled_at = datetime.now(UTC)
                changed = True
        if changed:
            await db.flush()
            rows = await list_test_results(db, task_id)
        if not rows or any(r.is_pass is None for r in rows):
            return False
        # 新一轮复核：清空上一轮复核记录
        await soft_delete_task_reviews(db, task_id)
        await update_test_task(db, task_id, status="pending_review")
        try:
            from app.modules.quality.feishu.fill_service import notify_pending_review

            spawn_background(notify_pending_review(str(task_id)))
        except Exception:
            logger.exception("待复核提醒推送失败")
        return True

    # ── 双人复核 ──

    REVIEW_REQUIRED_COUNT = 2

    @staticmethod
    async def add_review(
        db: AsyncSession,
        task_id: uuid.UUID,
        reviewer_id: uuid.UUID,
        comment: str | None = None,
    ) -> tuple[TestTaskDetail, int, bool]:
        """复核通过：记录复核人；两名不同复核人通过后任务自动完成。

        返回 (任务详情, 已通过人数, 是否已转为完成)。
        """
        task = await get_test_task(db, task_id)
        if not task:
            raise AppException(status_code=404, detail="检验任务不存在")
        if task.status != "pending_review":
            raise AppException(status_code=400, detail=f"任务状态为 {task.status}，不可复核")
        reviews = await list_task_reviews(db, task_id)
        if any(r.reviewer_id == reviewer_id for r in reviews):
            raise AppException(status_code=400, detail="你已复核过该任务，请等待另一位复核人复核")
        await create_task_review(db, task_id, reviewer_id, comment)
        reviews = await list_task_reviews(db, task_id)
        approved = len({r.reviewer_id for r in reviews})
        advanced = False
        if approved >= _TaskLifecycle.REVIEW_REQUIRED_COUNT:
            await update_test_task(db, task_id, status="completed")
            advanced = True
        fresh = await get_test_task(db, task_id)
        return _TaskLifecycle._to_detail(fresh, await list_test_results(db, task_id)), approved, advanced

    # ── P1 液相解析映射 ──

    @staticmethod
    async def add_result(
        db: AsyncSession, task_id: uuid.UUID, payload: TestResultCreate
    ) -> TestResultOut:
        task = await get_test_task(db, task_id)
        if not task:
            raise AppException(status_code=404, detail="检验任务不存在")
        if task.status != "in_progress":
            raise AppException(status_code=400, detail=f"任务状态为 {task.status}，不可追加项目")
        rows = await list_test_results(db, task_id)
        if payload.sop_no and any(
            r.sop_no == payload.sop_no and r.item_name == payload.item_name for r in rows
        ):
            raise AppException(
                status_code=400,
                detail=f"该任务已存在同 SOP 号同名称的项目行（{payload.sop_no} {payload.item_name}）",
            )
        next_seq = max((r.seq or 0 for r in rows), default=0) + 1
        created = await create_test_results(db, task_id, [{
            "standard_item_id": None,
            "seq": next_seq,
            "category": payload.category,
            "item_name": payload.item_name,
            "sop_no": payload.sop_no,
            "standard_text": payload.standard_text,
            "operator": payload.operator,
            "limit_min": payload.limit_min,
            "limit_max": payload.limit_max,
            "method_source": payload.method_source,
            "remark": payload.remark,
            "judge_mode": _TaskLifecycle._infer_judge_mode(payload.operator, payload.limit_min, payload.limit_max),
            "source": "manual",
        }])
        return _TaskLifecycle._to_result_out(created[0])

    # ── 状态流转 ──

    @staticmethod
    async def update_status(
        db: AsyncSession, task_id: uuid.UUID, payload: TestTaskStatusUpdate
    ) -> TestTaskDetail:
        task = await get_test_task(db, task_id)
        if not task:
            raise AppException(status_code=404, detail="检验任务不存在")
        target = payload.status
        if task.status == "void":
            raise AppException(status_code=400, detail="任务已作废，不可变更状态")
        if target == "void":
            pass  # 任何非 void 状态可作废
        elif task.status == target:
            raise AppException(status_code=400, detail=f"任务已处于 {target} 状态")
        elif task.status == "in_progress" and target == "pending_review":
            # 手动转待复核：必须全部判定完成（正常路径为填报后自动流转）；
            # 与自动流转一致，清空上一轮复核记录（新一轮双人复核重新计数）
            rows = await list_test_results(db, task_id)
            unfilled = [r.item_name for r in rows if r.is_pass is None]
            if unfilled:
                raise AppException(
                    status_code=400,
                    detail=f"存在 {len(unfilled)} 项未判定，无法进入待复核：{'、'.join(unfilled[:5])}",
                )
            await soft_delete_task_reviews(db, task_id)
        elif task.status == "pending_review" and target == "completed":
            # 双人复核：完成只能经复核接口（add_review）达成，禁止直接改状态
            raise AppException(
                status_code=400,
                detail="请通过复核流程完成（需两名不同复核人通过）",
            )
        elif task.status == "completed" and target == "in_progress":
            pass  # completed → in_progress 重新打开
        else:
            raise AppException(status_code=400, detail=f"非法状态流转：{task.status} → {target}")
        updated = await update_test_task(db, task_id, status=target)
        if not updated:
            raise AppException(status_code=404, detail="检验任务不存在")
        return _TaskLifecycle._to_detail(updated, await list_test_results(db, task_id))

    # ── 出报日期补录（关联当日机器人任务推送）──

    @staticmethod
    async def update_report_date(
        db: AsyncSession, task_id: uuid.UUID, payload: TestTaskReportDateUpdate
    ) -> TestTaskDetail:
        task = await get_test_task(db, task_id)
        if not task:
            raise AppException(status_code=404, detail="检验任务不存在")
        report_date = _norm_date_str(payload.report_date)
        updated = await update_test_task_report_date(db, task_id, report_date)
        if not updated:
            raise AppException(status_code=404, detail="检验任务不存在")
        # 补录出报日期为「今天」→ 即刻触发机器人推送（门控在 notify_task_created 内）
        if payload.report_date:
            try:
                from app.modules.quality.feishu.fill_service import notify_task_created

                spawn_background(notify_task_created(str(task_id)))
            except Exception:
                logger.exception("出报日期补录推送失败")
        return _TaskLifecycle._to_detail(updated, await list_test_results(db, task_id))

    # ── 删除 ──

    @staticmethod
    async def delete_task(db: AsyncSession, task_id: uuid.UUID) -> QualityTestTask | None:
        return await delete_test_task(db, task_id)

    @staticmethod
    async def delete_result(
        db: AsyncSession, task_id: uuid.UUID, result_id: uuid.UUID
    ) -> QualityTestResult | None:
        task = await get_test_task(db, task_id)
        if not task:
            raise AppException(status_code=404, detail="检验任务不存在")
        if task.status != "in_progress":
            raise AppException(status_code=400, detail=f"任务状态为 {task.status}，不可删除项目")
        row = await delete_test_result(db, result_id)
        if row is None or row.task_id != task_id:
            raise AppException(status_code=404, detail="结果行不存在")
        return row

    # ── P2 任务驱动 COA ──
