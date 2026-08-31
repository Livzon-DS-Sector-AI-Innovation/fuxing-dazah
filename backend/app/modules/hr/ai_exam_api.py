"""AI exam API endpoints."""

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import success_response
from app.modules.hr.ai_exam_schemas import ExamExportRequest
from app.modules.hr.ai_exam_service import export_exam, generate_exam
from app.modules.hr.deps import require_hr_basic

router = APIRouter(prefix="/exam", tags=["AI 出题"], dependencies=[Depends(require_hr_basic)])


@router.post("/generate", summary="生成考试题目")
async def api_generate_exam(
    file: UploadFile,
    choice_count: int = Form(5),
    true_false_count: int = Form(5),
    multi_choice_count: int = Form(0),
    fill_blank_count: int = Form(0),
    session: AsyncSession = Depends(get_db),
):
    """上传培训材料（docx/txt），AI 自动识别内容并按指定题型/题量生成试卷。

    生成结果同步写入共享题库（source=AI生成），后续考核矩阵/题库选题可复用。
    """
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")
    import logging
    logging.getLogger(__name__).info(f"Exam config: choice={choice_count} tf={true_false_count} multi={multi_choice_count} fill={fill_blank_count}")
    config = {
        "choice_count": choice_count,
        "true_false_count": true_false_count,
        "multi_choice_count": multi_choice_count,
        "fill_blank_count": fill_blank_count,
    }
    try:
        content = await file.read()
        result = await generate_exam(content, file.filename, config)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"AI 出题失败: {e}")
    # 写入共享题库（AI生成来源）；题库写入失败不连累出题结果
    from app.modules.hr.ai_exam_service import EXAM_QUESTION_KEYS, save_questions_to_bank

    questions: list[dict] = []
    for key in EXAM_QUESTION_KEYS:
        questions.extend(result.get(key, []))
    file_no = file.filename.rsplit(".", 1)[0] if "." in file.filename else file.filename
    try:
        bank_inserted = await save_questions_to_bank(session, questions, file_no)
    except Exception:
        logging.getLogger(__name__).warning("题库写入失败，不影响出题结果", exc_info=True)
        await session.rollback()
        bank_inserted = 0
    return success_response(data={**result, "bank_inserted": bank_inserted}, message=f"出题完成，{bank_inserted} 题已入题库")


@router.post("/export", summary="导出考试试卷")
async def api_export_exam(data: ExamExportRequest):
    """将试卷导出为 Word 文档。"""
    try:
        buffer = export_exam(data.model_dump())
    except Exception as e:
        raise HTTPException(500, f"导出失败: {e}")

    from urllib.parse import quote
    safe_name = quote(f"考试试卷_{data.title}.docx")
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{safe_name}"},
    )
