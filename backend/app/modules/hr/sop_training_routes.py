"""SOP 培训文件登记表 + 各部二级表路由。

登记表（对齐 010版 Excel 模板）：每年一张，每行一个培训文件，按年归档、颜色标注、可导出。
提交登记时按「培训涉及部门」自动生成各部二级表记录，并飞书卡片通知各部门培训管理员。
二级表：培训管理员选择自定义分类人员后生成培训材料（生成即完成，自动带出部门当前培训师）；
支持多条 SOP 同场合并生成一套培训材料。
"""
import json
import logging
import zipfile
from datetime import UTC, date, datetime
from io import BytesIO
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.hr.deps import HrAccessContext, get_hr_scope

logger = logging.getLogger(__name__)

router = APIRouter(tags=["HR-SOP培训"])


# ─── 工具函数 ───


def _ensure_entry_in_scope(hr_scope: HrAccessContext, entry) -> None:
    """二级表记录数据范围校验：记录按部门归属，越界抛 403。"""
    if hr_scope.is_unrestricted:
        return
    if not hr_scope.scoped_departments:
        raise HTTPException(403, "数据范围限制：仅可访问本人相关数据")
    if entry.department not in hr_scope.scoped_departments:
        raise HTTPException(403, f"数据范围限制：仅可操作授权部门记录（{entry.department}）")


def _json_loads(raw) -> list:
    """解析 JSON 数组字段，兼容 list 与 str。"""
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else []
    except Exception:
        return []


async def _lookup_level1_trainer(session: AsyncSession, department: str) -> str | None:
    """查找部门的一级培训师（当前培训师）。

    口径统一：优先取部门培训人员配置表 dept_training_personnel.level1_trainer；
    未配置时兜底取内训师台账 trainers 中 is_level1 的该部门培训师。
    """
    from app.modules.hr.models import DeptTrainingPersonnel, HrTrainer
    result = (await session.execute(
        select(DeptTrainingPersonnel).where(
            DeptTrainingPersonnel.is_deleted == False,  # noqa: E712
            DeptTrainingPersonnel.display_department == department,
        )
    )).scalars().first()
    if result and result.level1_trainer:
        return result.level1_trainer
    trainer = (await session.execute(
        select(HrTrainer).where(
            HrTrainer.is_deleted == False,  # noqa: E712
            HrTrainer.department == department,
            # 「一级培训师」是页面新增/Excel 归一化后的取值；是/1/true 兼容历史存量值
            HrTrainer.is_level1.in_(["一级培训师", "是", "1", "true", "True"]),
        ).order_by(HrTrainer.created_at.asc())
    )).scalars().first()
    return trainer.name if trainer else None


async def _resolve_training_admins(
    session: AsyncSession, record, departments: list[str]
) -> list[str]:
    """解析涉及部门的培训管理员姓名（去重、排序）。"""
    from app.modules.hr.models import DeptTrainingPersonnel

    if not departments:
        return []
    result = (await session.execute(
        select(DeptTrainingPersonnel).where(
            DeptTrainingPersonnel.is_deleted == False,  # noqa: E712
            DeptTrainingPersonnel.display_department.in_(departments),
        )
    )).scalars().all()
    admins: set[str] = set()
    for r in result:
        if r.training_admin:
            for a in r.training_admin.split(","):
                a = a.strip()
                if a:
                    admins.add(a)
    return sorted(admins)


async def _notify_training_admins(
    session: AsyncSession, record, departments: list[str]
) -> list[str]:
    """发送飞书卡片通知各涉及部门的培训管理员，返回实际通知到的姓名列表。"""
    try:
        admins = await _resolve_training_admins(session, record, departments)
        if not admins:
            return []

        from app.core.config import get_settings
        from app.modules.hr.feishu_review_service import _lookup_open_id, _send_card
        dept_text = "、".join(departments)
        elements = [
            {"tag": "div", "text": {"tag": "lark_md", "content": (
                f"**文件**：{record.file_name}\n"
                f"**涉及部门**：{dept_text}\n"
                f"**发起部门**：{record.initiator_department or '-'}\n请在系统中查看并处理"
            )}},
        ]
        # 深链直达二级表页面（进入后按数据范围只显示本人相关部门内容）
        frontend_url = (get_settings().FRONTEND_URL or "").rstrip("/")
        if frontend_url:
            elements.append({"tag": "action", "actions": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": "查看培训内容"},
                "type": "primary",
                "url": f"{frontend_url}/hr/training/sop-secondary",
            }]})
        card = {
            "header": {"title": {"tag": "plain_text", "content": "📋 新的SOP培训文件登记"}, "template": "blue"},
            "elements": elements,
        }
        import asyncio

        async def _send_one(name: str) -> str | None:
            oid = await _lookup_open_id(name)
            if not oid:
                return None
            await _send_card(oid, card)
            return name

        # 并发发送，避免提交流程被多个外部请求串行阻塞
        results = await asyncio.gather(*(_send_one(n) for n in admins))
        return [n for n in results if n]
    except Exception:
        logger.exception("通知培训管理员失败: record_id=%s", getattr(record, "id", None))  # 记录失败，便于排查
        return []


async def _sync_entries(session: AsyncSession, record) -> None:
    """按登记记录的培训涉及部门同步二级表：新增缺失部门，移除已取消且未生成材料的部门。"""
    from app.modules.hr.models import SopTrainingEntry
    related = _json_loads(record.involved_departments)
    related = list(dict.fromkeys(str(d).strip() for d in related if str(d).strip()))
    existing_rows = (await session.execute(
        select(SopTrainingEntry).where(
            SopTrainingEntry.is_deleted == False,  # noqa: E712
            SopTrainingEntry.record_id == str(record.id),
        )
    )).scalars().all()
    existing_depts = {e.department for e in existing_rows}
    for dept in related:
        if dept not in existing_depts:
            session.add(SopTrainingEntry(record_id=str(record.id), department=dept))
    for e in existing_rows:
        if e.department not in related and e.status != "已生成":
            e.is_deleted = True


def _record_dict(r) -> dict:
    return {
        "id": str(r.id),
        "year": r.year,
        "training_date": r.training_date,
        "file_name": r.file_name,
        "file_no": r.file_no,
        "effective_date": r.effective_date,
        "method": r.method,
        "complete_time": r.complete_time,
        "trainer": r.trainer,
        "trainees": r.trainees,
        "involved_departments": _json_loads(r.involved_departments),
        "change_note": r.change_note,
        "color": r.color,
        "status": r.status,
        "assessment_method": r.assessment_method,
        "files": _record_files(r),
        "initiator_department": r.initiator_department,
        "created_by": r.created_by,
        "created_at": str(r.created_at),
        "updated_at": str(r.updated_at),
    }


# ─── 考核方式 ───
# 决定「生成一套材料」打包哪些文件：阅读并理解→通知+签到+评估；
# 问答→通知+签到+问答实操记录+评估；笔试→通知+签到+试卷（题库有题才含）+评估
SOP_ASSESSMENT_METHODS = ("阅读并理解", "问答", "笔试")
# 考核方式未填时按培训方式取默认（R=自学 / T=面授）
ASSESSMENT_DEFAULT_BY_METHOD = {"R": "阅读并理解", "T": "问答"}


def _effective_assessment(stored: str | None, method: str | None) -> str:
    """登记的考核方式优先；历史数据为空时按培训方式取默认。"""
    val = (stored or "").strip()
    if val:
        return val
    return ASSESSMENT_DEFAULT_BY_METHOD.get((method or "").strip(), "阅读并理解")


def _method_label(method: str | None) -> str:
    """R/T 转成 docx「培训方式」栏可读写法。"""
    m = (method or "").strip()
    return {"R": "自学", "T": "面授"}.get(m, m)


# ─── 合并登记（一条记录含多份培训文件） ───


def _normalize_files(raw) -> list[dict] | None:
    """登记的 files 载荷清洗：剔除空行；返回 [{file_name, file_no}] 或 None。"""
    if not isinstance(raw, list):
        return None
    files: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("file_name") or "").strip()
        if not name:
            continue
        no = str(item.get("file_no") or "").strip() or None
        files.append({"file_name": name, "file_no": no})
    return files or None


def _record_files(r) -> list[dict]:
    """登记的文件列表：files JSON 优先，回落单文件列（历史数据）。"""
    raw = _normalize_files(_json_loads(getattr(r, "files", None)))
    if raw:
        return raw
    return [{"file_name": r.file_name, "file_no": r.file_no}]


def _record_file_nos(r) -> list[str]:
    """题库匹配用的文件编号列表（合并登记取全部）。"""
    return [no for f in _record_files(r) if (no := f.get("file_no"))]


def _joined_file_fields(files: list[dict]) -> tuple[str, str | None]:
    """files → (file_name, file_no) 展示串（「；」连接），列表/导出/搜索沿用单列。"""
    return (
        "；".join(f["file_name"] for f in files),
        "；".join(no for f in files if (no := f.get("file_no"))) or None,
    )


# ─── 登记表 ───


@router.get("/sop-training-records/years", summary="登记年份列表")
async def list_sop_record_years(
    session: AsyncSession = Depends(get_db),
):
    from app.modules.hr.models import SopTrainingRecord
    rows = (await session.execute(
        select(SopTrainingRecord.year)
        .where(SopTrainingRecord.is_deleted == False)  # noqa: E712
        .distinct()
        .order_by(SopTrainingRecord.year.desc())
    )).scalars().all()
    years = [r for r in rows if r]
    if str(date.today().year) not in years:
        years.insert(0, str(date.today().year))
    return success_response(data=years)


@router.get("/sop-training-records/dept-trainers", summary="按部门查一级培训师（被培训人员）")
async def sop_record_dept_trainers(
    departments: list[str] = Query(..., description="部门列表"),
    session: AsyncSession = Depends(get_db),
):
    """选择培训涉及部门后，自动关联各对应部门的一级培训师（即被培训人员）。"""
    result = []
    for dept in departments:
        trainer = await _lookup_level1_trainer(session, dept)
        result.append({"department": dept, "trainer": trainer})
    return success_response(data=result)


@router.get("/sop-training-records", summary="培训文件登记表列表")
async def list_sop_records(
    year: str | None = Query(None, description="年份筛选"),
    color: str | None = Query(None, description="颜色状态：新增/撤销/修改"),
    keyword: str | None = Query(None, description="文件名称/编号关键词"),
    session: AsyncSession = Depends(get_db),
):
    from app.modules.hr.models import SopTrainingRecord
    stmt = select(SopTrainingRecord).where(SopTrainingRecord.is_deleted == False)  # noqa: E712
    if year:
        stmt = stmt.where(SopTrainingRecord.year == year)
    if color:
        stmt = stmt.where(SopTrainingRecord.color == color)
    if keyword:
        stmt = stmt.where(
            SopTrainingRecord.file_name.ilike(f"%{keyword}%")
            | SopTrainingRecord.file_no.ilike(f"%{keyword}%")
        )
    rows = (await session.execute(
        stmt.order_by(SopTrainingRecord.training_date, SopTrainingRecord.created_at)
    )).scalars().all()
    return success_response(data=[_record_dict(r) for r in rows])


@router.post("/sop-training-records", summary="登记培训文件（保存为草稿）")
async def create_sop_record(
    payload: dict,
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    """登记培训文件，默认保存为草稿；点「提交/通知」后才生成二级表并通知各部门培训管理员。

    带 files（[{file_name, file_no}]）时为合并登记：一条记录含多份文件，
    file_name/file_no 存「；」连接的展示串，结构化访问走 files。
    """
    from app.modules.hr.models import SopTrainingRecord
    files = _normalize_files(payload.get("files"))
    if not payload.get("file_name") and not files:
        raise HTTPException(400, "请填写文件名称")
    # 列宽校验：非法值直接 400，而不是落库时 PG DataError 500
    year_val = str(payload.get("year") or date.today().year).strip()
    if len(year_val) != 4 or not year_val.isdigit():
        raise HTTPException(400, "年份格式不正确（应为 4 位数字年份）")
    if payload.get("method") and len(str(payload["method"]).strip()) > 4:
        raise HTTPException(400, "培训方式应为 R / T")
    assessment = str(payload.get("assessment_method") or "").strip() or None
    if assessment and assessment not in SOP_ASSESSMENT_METHODS:
        raise HTTPException(400, "考核方式应为 阅读并理解 / 问答 / 笔试")
    if payload.get("color") and len(str(payload["color"]).strip()) > 8:
        raise HTTPException(400, "标记颜色值过长")
    if not files:
        files = [{"file_name": str(payload["file_name"]).strip(), "file_no": payload.get("file_no")}]
    file_name, file_no = _joined_file_fields(files)
    if len(file_name) > 512:
        raise HTTPException(400, "合并后的文件名称过长，请拆分登记")
    involved = list(dict.fromkeys(
        str(d).strip() for d in _json_loads(payload.get("involved_departments")) if str(d).strip()
    ))
    initiator = payload.get("initiator_department") or ""
    r = SopTrainingRecord(
        year=year_val,
        training_date=payload.get("training_date"),
        file_name=file_name,
        file_no=file_no,
        files=json.dumps(files, ensure_ascii=False),
        effective_date=payload.get("effective_date"),
        method=payload.get("method"),
        assessment_method=assessment,
        complete_time=payload.get("complete_time"),
        trainer=payload.get("trainer"),
        trainees=payload.get("trainees") or (f"「{initiator}」全体员工及相关部门培训师" if initiator else None),
        involved_departments=json.dumps(involved, ensure_ascii=False),
        change_note=payload.get("change_note"),
        color=payload.get("color") or "新增",
        # 状态由提交流程控制：创建一律草稿，不允许客户端直接指定状态绕过状态机
        status="草稿",
        initiator_department=initiator or None,
        created_by=hr_scope.user.name or "",
    )
    session.add(r)
    await session.commit()
    return success_response(data={"id": str(r.id)}, message="已保存草稿", status_code=201)


@router.post("/sop-training-records/{record_id}/submit", summary="提交并通知")
async def submit_sop_record(
    record_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    """转培训：自动收录到相关部门二级表，并飞书通知对应培训管理员（返回通知名单）。"""
    from app.modules.hr.models import SopTrainingRecord
    r = await session.get(SopTrainingRecord, record_id)
    if not r or r.is_deleted:
        raise HTTPException(404, "记录不存在")
    involved = _json_loads(r.involved_departments)
    if not involved:
        raise HTTPException(400, "请先填写培训涉及部门")
    was_submitted = r.status == "已提交"
    r.status = "已提交"
    await session.commit()
    await _sync_entries(session, r)
    await session.commit()
    if not was_submitted:
        notified = await _notify_training_admins(session, r, involved)
        return success_response(
            data={"notified_admins": notified},
            message="已转培训，二级表已生成" + (f"并通知：{'、'.join(notified)}" if notified else "（未配置培训管理员，仅收录二级表）"),
        )
    return success_response(message="已转培训过，二级表已同步")


@router.get("/sop-training-records/{record_id}/training-admins", summary="登记记录涉及的培训管理员预览")
async def get_record_training_admins(
    record_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    """转培训前的确认清单：返回涉及部门的培训管理员姓名列表。"""
    from app.modules.hr.models import SopTrainingRecord
    r = await session.get(SopTrainingRecord, record_id)
    if not r or r.is_deleted:
        raise HTTPException(404, "记录不存在")
    involved = _json_loads(r.involved_departments)
    admins = await _resolve_training_admins(session, r, involved)
    return success_response(data={"admins": admins})


@router.put("/sop-training-records/{record_id}", summary="编辑登记记录")
async def update_sop_record(
    record_id: UUID,
    payload: dict,
    session: AsyncSession = Depends(get_db),
):
    from app.modules.hr.models import SopTrainingRecord
    r = await session.get(SopTrainingRecord, record_id)
    if not r or r.is_deleted:
        raise HTTPException(404, "记录不存在")
    if "file_name" in payload and not str(payload.get("file_name") or "").strip():
        raise HTTPException(400, "请填写文件名称")
    # 合并登记：带 files 时重算展示串（file_name/file_no 存「；」连接）
    if "files" in payload:
        files = _normalize_files(payload.get("files"))
        if files:
            joined_name, joined_no = _joined_file_fields(files)
            if len(joined_name) > 512:
                raise HTTPException(400, "合并后的文件名称过长，请拆分登记")
            payload["files"] = json.dumps(files, ensure_ascii=False)
            payload["file_name"] = joined_name
            payload["file_no"] = joined_no
        else:
            payload.pop("files")  # 空 files 不清历史数据
    if "color" in payload and not payload.get("color"):
        payload.pop("color")
    # 列宽校验：非法值直接 400，而不是落库时 PG DataError 500
    if "year" in payload:
        year_val = str(payload["year"]).strip()
        if len(year_val) != 4 or not year_val.isdigit():
            raise HTTPException(400, "年份格式不正确（应为 4 位数字年份）")
        payload["year"] = year_val
    if payload.get("method") and len(str(payload["method"]).strip()) > 4:
        raise HTTPException(400, "培训方式应为 R / T")
    if "assessment_method" in payload:
        assessment = str(payload.get("assessment_method") or "").strip() or None
        if assessment and assessment not in SOP_ASSESSMENT_METHODS:
            raise HTTPException(400, "考核方式应为 阅读并理解 / 问答 / 笔试")
        payload["assessment_method"] = assessment
    if payload.get("color") and len(str(payload["color"]).strip()) > 8:
        raise HTTPException(400, "标记颜色值过长")
    for key in ("year", "training_date", "file_name", "file_no", "files", "effective_date",
                "method", "assessment_method", "complete_time", "trainer", "trainees",
                "change_note", "color", "initiator_department"):
        if key in payload:
            setattr(r, key, payload[key])
    # status 由提交/生成材料流程控制，不允许客户端直接改写
    added_departments: list[str] = []
    if "involved_departments" in payload:
        old_departments = set(_json_loads(r.involved_departments))
        involved = list(dict.fromkeys(
            str(d).strip() for d in _json_loads(payload["involved_departments"]) if str(d).strip()
        ))
        r.involved_departments = json.dumps(involved, ensure_ascii=False)
        # 已提交记录新增了部门 → 新部门的培训管理员需要补发通知
        if r.status == "已提交":
            added_departments = [d for d in involved if d not in old_departments]
    await session.commit()
    # 已提交的记录编辑后同步二级表；草稿不生成二级表
    if r.status == "已提交":
        await _sync_entries(session, r)
        await session.commit()
        if added_departments:
            notified = await _notify_training_admins(session, r, added_departments)
            if notified:
                logger.info(
                    "登记记录 %s 新增部门 %s 已补发通知: %s",
                    r.id, added_departments, notified,
                )
    return success_response(message="已更新")


@router.delete("/sop-training-records/{record_id}", summary="删除登记记录")
async def delete_sop_record(
    record_id: UUID,
    session: AsyncSession = Depends(get_db),
):
    from app.modules.hr.models import SopTrainingEntry, SopTrainingRecord
    r = await session.get(SopTrainingRecord, record_id)
    if not r or r.is_deleted:
        raise HTTPException(404, "记录不存在")
    r.is_deleted = True
    entries = (await session.execute(
        select(SopTrainingEntry).where(
            SopTrainingEntry.is_deleted == False,  # noqa: E712
            SopTrainingEntry.record_id == str(record_id),
        )
    )).scalars().all()
    for e in entries:
        if e.status != "已生成":
            e.is_deleted = True
    await session.commit()
    return success_response(message="已删除")


@router.get("/sop-training-records/export", summary="导出培训文件登记表（对齐模板）")
async def export_sop_records(
    year: str | None = Query(None, description="年份筛选"),
    session: AsyncSession = Depends(get_db),
):
    """导出对齐 010版 登记表版式的 Excel（含颜色标注：黄=新增/灰=撤销/红=修改）。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    from app.modules.hr.models import SopTrainingRecord
    stmt = select(SopTrainingRecord).where(SopTrainingRecord.is_deleted == False)  # noqa: E712
    if year:
        stmt = stmt.where(SopTrainingRecord.year == year)
    rows = (await session.execute(
        stmt.order_by(SopTrainingRecord.year, SopTrainingRecord.training_date, SopTrainingRecord.created_at)
    )).scalars().all()

    wb = Workbook()
    ws = wb.active
    ws.title = f"{year}年" if year else "登记表"
    headers = ["培训日期", "文件名称", "文件编号", "生效日期", "培训方式\n（R/T）",
               "R：培训完成时间\nT：培训课时", "培训师", "培训对象", "培训涉及部门", "变更内容"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    fills = {
        "新增": PatternFill("solid", fgColor="FFF2CC"),
        "撤销": PatternFill("solid", fgColor="D9D9D9"),
        "修改": PatternFill("solid", fgColor="FFC7CE"),
    }

    def _fmt_dot(v: str | None) -> str:
        if not v:
            return ""
        return v.replace("-", ".")

    for r in rows:
        depts = "/".join(_json_loads(r.involved_departments))
        train_date = _fmt_dot(r.training_date)
        # 培训日期显示为月.日（如 01.05）；生效日期显示为 年.月.日
        if len(train_date) >= 8:
            train_date = train_date[5:]
        ws.append([
            train_date, r.file_name or "", r.file_no or "",
            _fmt_dot(r.effective_date), r.method or "", r.complete_time or "",
            r.trainer or "", r.trainees or "", depts, r.change_note or "",
        ])
        fill = fills.get(r.color)
        if fill:
            for cell in ws[ws.max_row]:
                cell.fill = fill
    for col, width in zip("ABCDEFGHIJ", (12, 44, 20, 12, 10, 22, 10, 30, 32, 30)):
        ws.column_dimensions[col].width = width
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"培训文件登记表_{year}年.xlsx" if year else f"培训文件登记表_{date.today().year}年.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{quote(filename)}"},
    )


# ─── 各部二级表 ───


async def _records_by_ids(session: AsyncSession, ids: list[str]) -> dict[str, object]:
    from app.modules.hr.models import SopTrainingRecord
    try:
        uuids = [UUID(i) for i in ids]
    except ValueError:
        return {}
    rows = (await session.execute(
        select(SopTrainingRecord).where(
            SopTrainingRecord.id.in_(uuids),
            SopTrainingRecord.is_deleted == False,  # noqa: E712
        )
    )).scalars().all()
    return {str(r.id): r for r in rows}


def _entry_dict(e, record_map: dict[str, object]) -> dict:
    rec = record_map.get(e.record_id or "")
    personnel = _json_loads(e.personnel)
    return {
        "id": str(e.id),
        "record_id": e.record_id,
        "department": e.department,
        "file_name": rec.file_name if rec else None,
        "file_no": rec.file_no if rec else None,
        "method": rec.method if rec else None,
        "trainer": e.trainer,
        "status": e.status,
        "complete_time": e.complete_time,
        "classification": e.classification,
        "personnel": personnel,
        "personnel_count": len(personnel),
        "generated_by": e.generated_by,
        "generated_at": str(e.generated_at) if e.generated_at else None,
        "created_at": str(e.created_at),
        "updated_at": str(e.updated_at),
    }


@router.get("/sop-training-entries", summary="SOP培训二级表列表")
async def list_sop_entries(
    record_id: str | None = Query(None, description="登记记录筛选"),
    department: str | None = Query(None, description="部门筛选"),
    status: str | None = Query(None, description="状态筛选：待生成/已生成"),
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    from app.modules.hr.models import SopTrainingEntry
    stmt = select(SopTrainingEntry).where(SopTrainingEntry.is_deleted == False)  # noqa: E712
    if hr_scope.is_unrestricted:
        if department:
            stmt = stmt.where(SopTrainingEntry.department == department)
    else:
        scoped = hr_scope.scoped_departments
        if not scoped:
            return success_response(data=[])
        stmt = stmt.where(SopTrainingEntry.department.in_(scoped))
        if department:
            if department not in scoped:
                raise HTTPException(403, "无权查看该部门二级表")
            stmt = stmt.where(SopTrainingEntry.department == department)
    if record_id:
        stmt = stmt.where(SopTrainingEntry.record_id == record_id)
    if status:
        stmt = stmt.where(SopTrainingEntry.status == status)
    rows = (await session.execute(stmt.order_by(SopTrainingEntry.created_at.desc()))).scalars().all()
    record_ids = list({e.record_id for e in rows if e.record_id})
    record_map = await _records_by_ids(session, record_ids)
    return success_response(data=[_entry_dict(e, record_map) for e in rows])


@router.put("/sop-training-entries/{entry_id}", summary="编辑二级表（分类/人员/培训师/完成时间）")
async def update_sop_entry(
    entry_id: UUID,
    payload: dict,
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    from app.modules.hr.models import SopTrainingEntry
    e = await session.get(SopTrainingEntry, entry_id)
    if not e or e.is_deleted:
        raise HTTPException(404, "记录不存在")
    _ensure_entry_in_scope(hr_scope, e)
    # 分类可多选，前端以「；」连接存储；单个名称 ≤64 字，合计 ≤256 字
    if "classification" in payload:
        raw = str(payload.get("classification") or "")
        parts = [p.strip() for p in raw.split("；") if p.strip()]
        if any(len(p) > 64 for p in parts):
            raise HTTPException(400, "单个分类名称过长（最多 64 字）")
        joined = "；".join(dict.fromkeys(parts))
        if len(joined) > 256:
            raise HTTPException(400, "分类名称过长（多选合计最多 256 字）")
        payload["classification"] = joined or None
    for key in ("classification", "trainer", "complete_time"):
        if key in payload:
            setattr(e, key, payload[key])
    if "personnel" in payload:
        e.personnel = json.dumps(payload["personnel"], ensure_ascii=False)
    await session.commit()
    return success_response(message="已更新")


async def _mark_generated(session: AsyncSession, e, operator: str) -> None:
    """生成材料即完成：自动带出该部门当前培训师，并把涉及人员自动关联到该条分类标签。"""
    if e.status == "已生成":
        return
    trainer = await _lookup_level1_trainer(session, e.department)
    e.trainer = trainer or e.trainer
    e.status = "已生成"
    e.generated_by = operator
    e.generated_at = datetime.now(UTC)
    await _link_classification_tags(session, e, operator)


async def _link_classification_tags(session: AsyncSession, e, operator: str) -> None:
    """生成材料自动关联分类：二级表涉及人员的自定义分类写入员工标签（幂等）。

    分类可多选（「；」连接）：每位涉及人员写入全部所选分类的标签，
    之后「员工档案-分类」与「二级表按分类拉人」会自动包含这些人。
    """
    import json as _json

    from app.modules.hr.models import EmployeeTag

    tags = [t.strip() for t in (e.classification or "").split("；") if t.strip()]
    if not tags:
        return
    personnel = e.personnel or []
    if isinstance(personnel, str):
        try:
            personnel = _json.loads(personnel)
        except ValueError:
            return
    if not isinstance(personnel, list):
        return
    numbers = {
        str(p.get("employee_number") or "").strip()
        for p in personnel
        if isinstance(p, dict) and (p.get("employee_number") or "").strip()
    }
    if not numbers:
        return
    # ON CONFLICT DO NOTHING：与活跃行部分唯一索引配合，并发生成/批量打标不 500
    # （部分索引推断必须显式给出 index_where）
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    for tag in tags:
        for num in numbers:
            await session.execute(
                pg_insert(EmployeeTag)
                .values(employee_number=num, tag_name=tag, created_by=operator)
                .on_conflict_do_nothing(
                    index_elements=["employee_number", "tag_name"],
                    index_where=text("is_deleted = false"),
                ),
            )
    await session.flush()


async def _query_leave_counts(session: AsyncSession, department: str) -> tuple[int, int]:
    """统计部门病假/产假人数（无则 0）；与员工查询口径一致：只认体现部门。"""
    sick = maternity = 0
    try:
        result = await session.execute(
            text(
                "SELECT status, count(*) FROM hr.training_roster_profiles "
                "WHERE department = :dept "
                "AND is_deleted = false AND status IN ('病假', '产假') GROUP BY status"
            ),
            {"dept": department},
        )
        for row in result.fetchall():
            if row[0] == "病假":
                sick = row[1]
            elif row[0] == "产假":
                maternity = row[1]
    except Exception:
        pass
    return sick, maternity


def _evaluation_stats_kwargs(
    stats: dict, expected: int, sick: int, maternity: int
) -> dict:
    """评估表统计预填：校验弹窗传来的统计并换算成 TrainingEvaluationInput kwargs。

    口径（用户拍板）：不合格恒为 0（优秀+合格=参加考核）；事假=应到-实到-病产假（负则 0）；
    参与率=实到/应到、合格率恒 100%。expected 为 0 时（名单为空）不预填，原样返回 {}。
    """
    def _int(key: str) -> int:
        try:
            return int(stats.get(key) or 0)
        except (TypeError, ValueError):
            raise HTTPException(400, f"评估表统计的「{key}」不是有效数字")

    actual = _int("actual_count")
    exam = _int("exam_count")
    excellent = _int("excellent_count")
    qualified = _int("qualified_count")
    if min(actual, exam, excellent, qualified) < 0:
        raise HTTPException(400, "评估表统计不能为负数")
    if excellent + qualified != exam:
        raise HTTPException(400, "优秀人数 + 合格人数 必须等于 参加考核人数（不合格恒为 0）")
    if expected <= 0:
        return {}
    if actual > expected:
        raise HTTPException(400, f"实到人数（{actual}）不能超过应到人数（{expected}）")
    if exam > actual:
        raise HTTPException(400, f"参加考核人数（{exam}）不能超过实到人数（{actual}）")
    personal_leave = max(expected - actual - sick - maternity, 0)
    participation = f"{round(actual / expected * 100)}%" if expected else None
    return {
        "actual_count": actual,
        "exam_count": exam,
        "excellent_count": excellent,
        "qualified_count": qualified,
        "unqualified_count": 0,
        "personal_leave": personal_leave,
        "participation_rate": participation,
        "pass_rate": "100%" if exam else None,
    }


async def _lookup_exam_questions(session, file_nos: list[str]) -> list[dict]:
    """按 SOP 编号查找题库题目（试卷打包用），返回 [{file_no, question, answer, score}]。"""
    if not file_nos:
        return []
    from app.modules.hr.models import QuestionBank

    rows = (
        await session.execute(
            select(QuestionBank).where(
                QuestionBank.is_deleted == False,  # noqa: E712
                QuestionBank.file_no.in_(file_nos),
            )
        )
    ).scalars().all()
    return [
        {"file_no": q.file_no or "", "question": q.question, "answer": q.answer, "score": q.score or 0}
        for q in rows
    ]


def _generate_exam_docx(subject: str, questions: list[dict]) -> BytesIO:
    """从零生成培训试卷 docx（题目+参考答案）。"""
    from docx import Document

    doc = Document()
    doc.add_heading(f"培训试卷 — {subject}", level=1)
    total = 0
    for i, q in enumerate(questions, start=1):
        doc.add_paragraph(f"{i}. {q['question']}（{q['score']}分）")
        total += int(q.get("score") or 0)
    if total:
        doc.add_paragraph(f"满分：{total} 分")
    doc.add_heading("参考答案", level=2)
    for i, q in enumerate(questions, start=1):
        doc.add_paragraph(f"{i}. {q.get('answer') or '（无参考答案）'}")
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf




@router.post("/sop-training-records/{record_id}/materials", summary="统筹总表一键生成全套培训材料")
async def generate_record_materials(
    record_id: UUID,
    payload: dict | None = Body(default=None),
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    """按登记表涉及部门生成全套材料 zip：通知+签到表+评估，考核记录按考核方式加（问答→问答实操记录表，笔试→试卷，题库有题才含）。

    培训对象统一写「发起部门 全体成员及相关一级培训师」。
    """
    from app.modules.hr.models import SopTrainingRecord

    record = (
        await session.execute(
            select(SopTrainingRecord).where(
                SopTrainingRecord.id == record_id,
                SopTrainingRecord.is_deleted == False,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if not record:
        raise HTTPException(404, "登记记录不存在")
    departments = _json_loads(record.involved_departments) or []
    if not departments:
        raise HTTPException(400, "该记录未配置涉及部门")
    # 数据范围：涉及部门必须全部在授权范围内（防止导出其他部门员工名单）
    if not hr_scope.is_unrestricted:
        if not hr_scope.scoped_departments:
            raise HTTPException(403, "数据范围限制：仅可访问本人相关数据")
        out_of_scope = [d for d in departments if d not in hr_scope.scoped_departments]
        if out_of_scope:
            raise HTTPException(403, f"数据范围限制：涉及部门超出授权范围（{', '.join(map(str, out_of_scope))}）")

    from app.modules.hr.notification_document_generator import (
        generate_training_notification,
    )
    from app.modules.hr.schemas import (
        TrainingNotificationInput,
        TrainingSignInSheetInput,
    )
    from app.modules.hr.signin_document_generator import generate_training_sign_in_sheet

    today = date.today()
    subject = record.file_name or "SOP培训"
    trainer = record.trainer
    initiator = (record.initiator_department or "").strip()
    if not initiator:
        # 历史记录未填发起部门：兜底取第一个涉及部门作为主办部门
        initiator = str(departments[0]).strip()
        logger.warning("登记记录 %s 未配置发起部门，兜底使用涉及部门「%s」", record.id, initiator)
    if not initiator:
        raise HTTPException(400, "该记录未配置发起部门（主办部门）")

    # ── 人员口径：主办部门名单内人员（只认体现部门）+ 各涉及部门的一级培训师（去重）──
    emp_rows = (await session.execute(
        text(
            "SELECT name, status FROM hr.training_roster_profiles "
            "WHERE department = :dept "
            "AND is_deleted = false AND status NOT IN ('离职', '待审批', '病假', '产假') "
            "ORDER BY name"
        ),
        {"dept": initiator},
    )).fetchall()
    # 姓名 → 显示部门：主办部门员工显示主办部门，涉及部门培训师显示其实际部门
    name_depts: dict[str, str] = {r[0]: initiator for r in emp_rows}
    trainer_map: dict[str, str] = {}
    for dept in departments:
        dept = str(dept).strip()
        level1 = await _lookup_level1_trainer(session, dept)
        if level1:
            trainer_map.setdefault(level1, dept)
    # 主办部门一级培训师作为授课讲师（涉及部门有则取其一；兜底登记表填写的培训师）
    initiator_trainer = await _lookup_level1_trainer(session, initiator)
    lead_trainer = initiator_trainer or (sorted(trainer_map)[0] if trainer_map else (trainer or ""))
    for t, tdept in sorted(trainer_map.items()):
        if t not in name_depts:
            name_depts[t] = tdept or initiator
    names = list(name_depts.keys())
    sick, maternity = await _query_leave_counts(session, initiator)

    questions = await _lookup_exam_questions(session, _record_file_nos(record))
    assessment = _effective_assessment(record.assessment_method, record.method)
    # 培训对象口径：总表材料 = 发起部门全体成员 + 相关一级培训师（病产假附注按主办部门统计，保留）
    trainee_group = "全体成员及相关一级培训师"
    # 模板字节一次取齐（DB 自定义版优先，无则回退仓库默认模板）
    from app.modules.hr.training_template_store import load_training_template_bytes

    tpl_notification, _ = await load_training_template_bytes(session, "training_notification")
    tpl_signin, _ = await load_training_template_bytes(session, "training_signin_sheet")
    tpl_evaluation, _ = await load_training_template_bytes(session, "training_evaluation")
    tpl_qa, _ = await load_training_template_bytes(session, "qa_record")
    buf = BytesIO()
    try:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            notif_buf = generate_training_notification(TrainingNotificationInput(
                department=initiator, training_date=today, subject=subject,
                trainer=lead_trainer, content=record.change_note or "",
                trainee_names=names, issuer_department=initiator,
                issue_date=today, sick_count=sick, maternity_count=maternity,
                training_method=_method_label(record.method),
                assessment_method=assessment,
                trainee_group=trainee_group,
            ), template_bytes=tpl_notification)
            sign_buf = generate_training_sign_in_sheet(TrainingSignInSheetInput(
                training_date=today, department=initiator, training_subject=subject,
                topic=record.change_note or subject, instructor=lead_trainer,
                employee_names=names, employee_departments=name_depts,
                sick_count=sick, maternity_count=maternity,
                assessment_method=assessment,
                trainee_group=trainee_group,
            ), template_bytes=tpl_signin)
            zf.writestr("培训通知.docx", notif_buf.getvalue())
            zf.writestr("培训签到表.docx", sign_buf.getvalue())
            # 考核记录按考核方式：问答→问答实操记录表（题库按文件编号出题，无题留空白行手写）
            if assessment == "问答":
                from app.modules.hr.qa_record_generator import generate_qa_record

                zf.writestr(
                    "问答实操记录表.docx",
                    generate_qa_record(
                        training_content=subject, training_date=today,
                        training_method=_method_label(record.method),
                        training_department=initiator,
                        questions=questions, trainee_names=names,
                        trainer_name=lead_trainer or "",
                        trainee_group=trainee_group,
                        template_bytes=tpl_qa,
                    ).getvalue(),
                )
            elif assessment == "笔试" and questions:
                zf.writestr("培训试卷.docx", _generate_exam_docx(subject, questions).getvalue())
            # 培训效果评估表（7.11 模板）
            from app.modules.hr.evaluation_document_generator import (
                TrainingEvaluationInput,
                generate_training_evaluation,
            )

            zf.writestr(
                "培训效果评估表.docx",
                generate_training_evaluation(TrainingEvaluationInput(
                    subject=subject, training_date=today, department=initiator,
                    trainer=lead_trainer or None,
                    training_method=_method_label(record.method) or None,
                    assessment_method=assessment,
                    trainee_names=names,
                    expected_count=len(names),
                    # 病产假与通知/签到表同口径（主办部门在职名单状态统计）
                    sick_leave=sick, maternity_leave=maternity,
                    # 弹窗预填的评估表统计（可选）：校验与比率换算见 _evaluation_stats_kwargs
                    **_evaluation_stats_kwargs(
                        (payload or {}).get("evaluation_stats") or {},
                        expected=len(names), sick=sick, maternity=maternity,
                    ),
                    trainee_group=trainee_group,
                ), template_bytes=tpl_evaluation).getvalue(),
            )
    except FileNotFoundError as e:
        raise HTTPException(400, f"生成失败（模板缺失）: {e}")
    buf.seek(0)
    filename = f"SOP全套培训材料_{today.isoformat()}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{quote(filename)}"},
    )
@router.get("/sop-training-records/{record_id}/materials-preview", summary="全套材料·评估表统计基数预览")
async def preview_record_materials(
    record_id: UUID,
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    """弹窗预填用：返回单条材料导出时的应到人数（主办部门名单∪涉及部门一级培训师）与病产假数。

    口径与 materials 接口的人员查询一致（两处同步改）。
    """
    from app.modules.hr.models import SopTrainingRecord

    record = (
        await session.execute(
            select(SopTrainingRecord).where(
                SopTrainingRecord.id == record_id,
                SopTrainingRecord.is_deleted == False,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if not record:
        raise HTTPException(404, "登记记录不存在")
    departments = _json_loads(record.involved_departments) or []
    initiator = (record.initiator_department or "").strip() or (str(departments[0]).strip() if departments else "")
    if initiator:
        if not hr_scope.is_unrestricted:
            if not hr_scope.scoped_departments or initiator not in hr_scope.scoped_departments:
                raise HTTPException(403, "数据范围限制：仅可访问本人相关数据")
    name_set: set[str] = set()
    sick = maternity = 0
    if initiator:
        emp_rows = (await session.execute(
            text(
                "SELECT name FROM hr.training_roster_profiles "
                "WHERE department = :dept "
                "AND is_deleted = false AND status NOT IN ('离职', '待审批', '病假', '产假') "
                "ORDER BY name"
            ),
            {"dept": initiator},
        )).fetchall()
        trainer_map: dict[str, str] = {}
        for dept in departments:
            dept = str(dept).strip()
            level1 = await _lookup_level1_trainer(session, dept)
            if level1:
                trainer_map.setdefault(level1, dept)
        name_set = {r[0] for r in emp_rows} | set(trainer_map)
        sick, maternity = await _query_leave_counts(session, initiator)
    return success_response(data={
        "expected_count": len(name_set),
        "sick_leave": sick,
        "maternity_leave": maternity,
    })


@router.post("/sop-training-entries/materials-preview", summary="一套材料·评估表统计基数预览")
async def preview_batch_materials(
    payload: dict,
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    """弹窗预填用：返回勾选条目一套材料的应到人数（分类人员并集）与部门病产假数。

    未选分类人员时 expected_count 返回 0（导出接口会拦，弹窗先提示）。
    """
    from app.modules.hr.models import SopTrainingEntry

    ids = payload.get("ids") or []
    if not ids:
        raise HTTPException(400, "请选择记录")
    try:
        entry_ids = [UUID(i) for i in ids]
    except (TypeError, ValueError):
        raise HTTPException(400, "记录 ID 格式不正确")
    rows = (await session.execute(
        select(SopTrainingEntry).where(
            SopTrainingEntry.is_deleted == False,  # noqa: E712
            SopTrainingEntry.id.in_(entry_ids),
        )
    )).scalars().all()
    if not rows:
        raise HTTPException(404, "记录不存在")
    for row in rows:
        _ensure_entry_in_scope(hr_scope, row)
    names: list[str] = []
    for e in rows:
        for p in _json_loads(e.personnel) or []:
            nm = str(p.get("name", "")).strip()
            if nm and nm not in names:
                names.append(nm)
    dept = str(rows[0].department or "").strip()
    sick, maternity = await _query_leave_counts(session, dept) if dept else (0, 0)
    return success_response(data={
        "expected_count": len(names),
        "sick_leave": sick,
        "maternity_leave": maternity,
    })


@router.post("/sop-training-entries/batch-materials", summary="多条SOP生成一套培训材料")
async def batch_generate_materials(
    payload: dict,
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    """勾选二级表记录（1..n 条）生成**一套**培训材料。

    生成即完成：成功生成后条目状态置「已生成」，自动带出本部门一级培训师并关联分类标签
    （重复生成幂等，状态不回退）。
    人员 = 各选中条目「分类人员」的并集（条目未选分类人员时直接 400 提示先选人）；
    选中多条时培训内容并列体现多个文件名称，共用同一套通知/签到表/考核记录/评估表
    （考核记录按登记的考核方式：问答→问答实操记录表、笔试→试卷（有题才含）、阅读并理解→无）。
    培训对象：默认「xx部门 全体成员」；条目按标签选人时写「xx部门 标签名」（如「xx部门 班组长」），
    此时省略全部门口径的病产假附注。
    """
    from app.modules.hr.models import SopTrainingEntry
    ids = payload.get("ids") or []
    if not ids:
        raise HTTPException(400, "请选择记录")
    try:
        entry_ids = [UUID(i) for i in ids]
    except (TypeError, ValueError):
        raise HTTPException(400, "记录 ID 格式不正确")
    rows = (await session.execute(
        select(SopTrainingEntry).where(
            SopTrainingEntry.is_deleted == False,  # noqa: E712
            SopTrainingEntry.id.in_(entry_ids),
        )
    )).scalars().all()
    if not rows:
        raise HTTPException(404, "记录不存在")
    # 数据范围：逐条校验（防止受限用户导出其他部门员工名单）
    for row in rows:
        _ensure_entry_in_scope(hr_scope, row)
    record_map = await _records_by_ids(session, [e.record_id for e in rows if e.record_id])

    # 每条记录必须先选好分类人员（材料人员口径 = 分类人员）
    file_names: list[str] = []
    file_nos: list[str] = []
    names: list[str] = []
    emp_nos: list[str] = []
    for e in rows:
        rec = record_map.get(e.record_id or "")
        fname = (rec.file_name if rec else None) or e.file_name or "SOP培训"
        if fname not in file_names:
            file_names.append(fname)
        if rec:
            for no in _record_file_nos(rec):
                if no and no not in file_nos:
                    file_nos.append(no)
        personnel = _json_loads(e.personnel)
        if not personnel:
            raise HTTPException(400, f"「{fname}」尚未选择分类人员，请先在该条目选择分类人员后再生成材料")
        for p in personnel:
            nm = str(p.get("name", "")).strip()
            no = str(p.get("employee_number", "")).strip()
            if nm and nm not in names:
                names.append(nm)
                emp_nos.append(no)

    dept = str(rows[0].department or "").strip()
    subject = file_names[0] if len(file_names) == 1 else "；".join(file_names)
    content = "；".join(file_names)

    from app.modules.hr.notification_document_generator import (
        generate_training_notification,
    )
    from app.modules.hr.schemas import (
        TrainingNotificationInput,
        TrainingSignInSheetInput,
    )
    from app.modules.hr.signin_document_generator import generate_training_sign_in_sheet

    today = date.today()
    # 培训方式/考核方式在登记记录上（二级表无该列），取第一条有值的记录
    method_val = ""
    for e in rows:
        rec = record_map.get(e.record_id or "")
        if rec and rec.method:
            method_val = rec.method
            break
    assessment_val = ""
    for e in rows:
        rec = record_map.get(e.record_id or "")
        if rec and rec.assessment_method:
            assessment_val = rec.assessment_method
            break
    assessment = _effective_assessment(assessment_val, method_val)
    # 培训对象口径：二级表材料默认「该部门 全体成员」；条目按标签选人时写「xx部门 标签名」
    # （多条不同标签按「、」连接），如「xx部门 班组长」。标签选人已排除病产假，
    # 全部门口径的「（病假x人、产假y人除外）」附注不适用，随之省略。
    # 分类可多选（「；」连接），拆开参与去重
    groups = list(dict.fromkeys(
        part.strip()
        for e in rows
        for part in (e.classification or "").split("；")
        if part.strip()
    ))
    trainee_group = "、".join(groups) or None
    # 该部门培训师
    trainer = next((e.trainer for e in rows if e.trainer), None) or await _lookup_level1_trainer(session, dept)
    # 分类人员并集（过滤病假/产假/离职/待审批）
    if emp_nos:
        leave_rows = (await session.execute(
            text(
                "SELECT employee_number, status FROM hr.training_roster_profiles "
                "WHERE employee_number = ANY(:nos) AND is_deleted = false "
                "AND status IN ('病假', '产假', '离职', '待审批')"
            ),
            {"nos": emp_nos},
        )).fetchall()
        excluded = {r[0] for r in leave_rows}
        keep = [(no, nm) for no, nm in zip(emp_nos, names) if no not in excluded]
        names = [nm for _, nm in keep]
    sick, maternity = await _query_leave_counts(session, dept)

    # 模板字节一次取齐（DB 自定义版优先，无则回退仓库默认模板）
    from app.modules.hr.training_template_store import load_training_template_bytes

    tpl_notification, _ = await load_training_template_bytes(session, "training_notification")
    tpl_signin, _ = await load_training_template_bytes(session, "training_signin_sheet")
    tpl_evaluation, _ = await load_training_template_bytes(session, "training_evaluation")
    tpl_qa, _ = await load_training_template_bytes(session, "qa_record")
    buf = BytesIO()
    try:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            notif_buf = generate_training_notification(TrainingNotificationInput(
                department=dept, training_date=today, subject=subject,
                trainer=trainer or "", content=content, trainee_names=names,
                issuer_department=dept, issue_date=today,
                sick_count=sick, maternity_count=maternity,
                training_method=_method_label(method_val),
                assessment_method=assessment,
                trainee_group=trainee_group,
                omit_leave_note=bool(groups),
            ), template_bytes=tpl_notification)
            sign_buf = generate_training_sign_in_sheet(TrainingSignInSheetInput(
                training_date=today, department=dept, training_subject=subject,
                topic=content, instructor=trainer or "",
                employee_names=names, employee_departments={n: dept for n in names},
                sick_count=sick, maternity_count=maternity,
                assessment_method=assessment,
                trainee_group=trainee_group,
                omit_leave_note=bool(groups),
            ), template_bytes=tpl_signin)
            zf.writestr("培训通知.docx", notif_buf.getvalue())
            zf.writestr("培训签到表.docx", sign_buf.getvalue())
            # 考核记录按考核方式：问答→问答实操记录表（按 SOP 编号匹配题库，无题留空白行手写）；笔试→试卷（有题才含）
            questions = await _lookup_exam_questions(session, file_nos)
            if assessment == "问答":
                from app.modules.hr.qa_record_generator import generate_qa_record

                zf.writestr(
                    "问答实操记录表.docx",
                    generate_qa_record(
                        training_content=subject, training_date=today,
                        training_method=_method_label(method_val),
                        training_department=dept,
                        questions=questions, trainee_names=names,
                        trainer_name=trainer or "",
                        trainee_group=trainee_group,
                        template_bytes=tpl_qa,
                    ).getvalue(),
                )
            elif assessment == "笔试" and questions:
                zf.writestr("培训试卷.docx", _generate_exam_docx(subject, questions).getvalue())
            # 培训效果评估表（7.11 模板）
            from app.modules.hr.evaluation_document_generator import (
                TrainingEvaluationInput,
                generate_training_evaluation,
            )

            zf.writestr(
                "培训效果评估表.docx",
                generate_training_evaluation(TrainingEvaluationInput(
                    subject=subject, training_date=today, department=dept,
                    trainer=trainer or None,
                    training_method=(_method_label(method_val) or None),
                    assessment_method=assessment,
                    trainee_names=names,
                    expected_count=len(names),
                    # 病产假与通知/签到表同口径（部门在职名单状态统计）
                    sick_leave=sick, maternity_leave=maternity,
                    # 弹窗预填的评估表统计（可选）：校验与比率换算见 _evaluation_stats_kwargs
                    **_evaluation_stats_kwargs(
                        payload.get("evaluation_stats") or {},
                        expected=len(names), sick=sick, maternity=maternity,
                    ),
                    trainee_group=trainee_group,
                ), template_bytes=tpl_evaluation).getvalue(),
            )
    except FileNotFoundError as e:
        raise HTTPException(400, f"生成失败（模板缺失）: {e}")
    # 生成即完成：带出培训师、关联分类标签、状态置已生成（模板缺失 400 时不落状态）
    operator = hr_scope.user.name or ""
    for e in rows:
        await _mark_generated(session, e, operator)
    await session.commit()
    buf.seek(0)
    filename = f"SOP培训材料_{today.isoformat()}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{quote(filename)}"},
    )


@router.get("/sop-training-entries/classifications", summary="部门自定义分类选项")
async def sop_entry_classifications(
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    """二级表分类选项 = 当前用户在员工档案里的分类（清单 + 打过的标签）。

    员工档案「分类管理」建的清单即使尚未打标签（0 人）也展示；
    直接在员工行上打的标签（如「分类1/分类2」）同样出现——都是本人创建的
    分类，按创建人过滤，看不到别人的分类/测试数据。
    人数按标签全量统计（分类人员跨部门联动，不按二级表记录的部门过滤）；
    受限用户只统计授权部门内的人员。
    """
    creator = hr_scope.user.name or hr_scope.user.employee_no or ""
    # 数据范围：受限用户只能看授权部门内的人员（员工标签/分类属于员工 PII）
    dept_filter = ""
    tag_params: dict = {"creator": creator}
    if not hr_scope.is_unrestricted:
        if not hr_scope.scoped_departments:
            raise HTTPException(403, "数据范围限制：仅可访问本人相关数据")
        dept_filter = "AND p.department = ANY(:scoped)"
        tag_params["scoped"] = sorted(hr_scope.scoped_departments)
    # ① 本人的分类清单（员工档案「分类管理」）
    catalog = (await session.execute(
        text(
            "SELECT name FROM hr.employee_classifications "
            "WHERE is_deleted = false AND created_by = :creator ORDER BY created_at"
        ),
        {"creator": creator},
    )).fetchall()
    # ② 本人打过的标签计数（直接打标签没建清单的分类也在这里）
    # 人员口径 = 培训人员名单（脱敏独立数据集），不再读员工总表
    tag_rows = (await session.execute(
        text(f"""
            SELECT t.tag_name, count(DISTINCT t.employee_number)
            FROM hr.employee_tags t
            JOIN hr.training_roster_profiles p ON p.employee_number = t.employee_number
            WHERE t.is_deleted = false AND p.is_deleted = false
              AND t.created_by = :creator
              AND p.status NOT IN ('离职', '待审批', '病假', '产假')
              {dept_filter}
            GROUP BY t.tag_name
        """),
        tag_params,
    )).fetchall()
    counts = {r[0]: r[1] for r in tag_rows}
    result: list[dict] = []
    seen: set[str] = set()
    for r in catalog:
        name = r[0]
        if name in seen:
            continue
        seen.add(name)
        result.append({"tag_name": name, "count": counts.get(name, 0)})
    for name, cnt in sorted(counts.items()):
        if name in seen:
            continue
        seen.add(name)
        result.append({"tag_name": name, "count": cnt})
    return success_response(data=result)


@router.get("/sop-training-entries/personnel", summary="分类人员查询")
async def sop_entry_personnel(
    classification: list[str] = Query(..., description="自定义分类（可多选，取并集）"),
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    """按自定义分类拉取人员（可传多个分类取并集；标签可多打，人员可重复分类）。

    分类人员跨部门联动：只认本人打的标签，不按二级表记录的部门过滤；
    受限用户只返回授权部门内的人员。排除离职/待审批/病假/产假。
    """
    # 数据范围：受限用户只能查授权部门（员工姓名/工号/岗位/状态属于 PII）
    creator = hr_scope.user.name or hr_scope.user.employee_no or ""
    dept_filter = ""
    params: dict = {"tags": [c for c in classification if c.strip()], "creator": creator}
    if not params["tags"]:
        raise HTTPException(400, "请至少选择一个分类")
    if not hr_scope.is_unrestricted:
        if not hr_scope.scoped_departments:
            raise HTTPException(403, "数据范围限制：仅可访问本人相关数据")
        dept_filter = "AND p.department = ANY(:scoped)"
        params["scoped"] = sorted(hr_scope.scoped_departments)
    # 人员口径 = 培训人员名单（脱敏独立数据集，状态由培训管理独立维护）；
    # 与分类选项一致，只看本人打的标签，避免同名分类串到别人的测试数据
    rows = (await session.execute(
        text(f"""
            SELECT DISTINCT p.employee_number, p.name, p.position, p.status
            FROM hr.training_roster_profiles p
            JOIN hr.employee_tags t ON t.employee_number = p.employee_number
            WHERE t.is_deleted = false AND p.is_deleted = false
              AND t.tag_name = ANY(:tags) AND t.created_by = :creator
              AND p.status NOT IN ('离职', '待审批', '病假', '产假')
              {dept_filter}
            ORDER BY p.employee_number
        """),
        params,
    )).fetchall()
    return success_response(data=[
        {"employee_number": r[0], "name": r[1], "position": r[2], "status": r[3]}
        for r in rows
    ])


@router.get("/sop-training-entries/export", summary="导出培训清单")
async def export_sop_entries(
    record_id: str | None = Query(None, description="登记记录筛选"),
    department: str | None = Query(None, description="部门筛选"),
    status: str | None = Query(None, description="状态筛选：待生成/已生成"),
    session: AsyncSession = Depends(get_db),
    hr_scope: HrAccessContext = Depends(get_hr_scope),
):
    """导出二级表培训清单（xlsx）。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    from app.modules.hr.models import SopTrainingEntry
    stmt = select(SopTrainingEntry).where(SopTrainingEntry.is_deleted == False)  # noqa: E712
    if hr_scope.is_unrestricted:
        if department:
            stmt = stmt.where(SopTrainingEntry.department == department)
    else:
        scoped = hr_scope.scoped_departments
        if not scoped:
            raise HTTPException(403, "数据范围限制：无可见部门")
        stmt = stmt.where(SopTrainingEntry.department.in_(scoped))
        if department:
            if department not in scoped:
                raise HTTPException(403, "无权导出该部门清单")
            stmt = stmt.where(SopTrainingEntry.department == department)
    if record_id:
        stmt = stmt.where(SopTrainingEntry.record_id == record_id)
    if status:
        stmt = stmt.where(SopTrainingEntry.status == status)
    rows = (await session.execute(
        stmt.order_by(SopTrainingEntry.department, SopTrainingEntry.created_at)
    )).scalars().all()
    record_map = await _records_by_ids(session, [e.record_id for e in rows if e.record_id])

    wb = Workbook()
    ws = wb.active
    ws.title = "SOP培训清单"
    headers = ["部门", "文件名称", "文件编号", "培训方式", "培训师", "状态", "完成时间/课时", "自定义分类", "分类人员", "生成人", "生成时间"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")
    for e in rows:
        rec = record_map.get(e.record_id or "")
        names = "、".join(str(p.get("name", "")) for p in _json_loads(e.personnel) if p.get("name"))
        ws.append([
            e.department,
            rec.file_name if rec else "",
            rec.file_no if rec else "",
            rec.method if rec else "",
            e.trainer or "", e.status, e.complete_time or "",
            e.classification or "", names, e.generated_by or "",
            str(e.generated_at)[:19] if e.generated_at else "",
        ])
    for col, width in zip("ABCDEFGHIJK", (18, 44, 20, 10, 14, 10, 20, 16, 40, 12, 20)):
        ws.column_dimensions[col].width = width
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"SOP培训清单_{date.today().isoformat()}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{quote(filename)}"},
    )
