"""AI exam API endpoints."""

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.core.response import success_response
from app.modules.ai_exam.schemas import ExamExportRequest
from app.modules.ai_exam.service import export_exam, generate_exam

router = APIRouter(prefix="/exam", tags=["AI 出题"])


@router.post("/generate", summary="生成考试题目")
async def api_generate_exam(
    file: UploadFile,
    choice_count: int = Form(5),
    true_false_count: int = Form(5),
    multi_choice_count: int = Form(0),
    fill_blank_count: int = Form(0),
):
    """上传培训材料（docx/txt），AI 自动识别内容并按指定题型/题量生成试卷。"""
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
    return success_response(data=result, message="出题完成")


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
