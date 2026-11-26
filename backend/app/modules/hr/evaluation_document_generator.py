"""培训效果评估表 Word 文档生成器 — 基于 {标记} 模板（模板可由用户自维护）。

模板标记清单见 training_template_registry（键 training_evaluation）。
统计类标记未提供数据时写空；参与率与合格率都为空时整句评价隐藏。
"""

from datetime import date, datetime
from io import BytesIO

from docx import Document
from pydantic import BaseModel, Field

from app.modules.hr.docx_markers import clear_unused_markers, replace_markers
from app.modules.hr.template_utils import find_hr_template_bytes


class TrainingEvaluationInput(BaseModel):
    subject: str = Field(..., max_length=256, description="培训主题")
    training_date: date | None = Field(None)
    training_time_start: str | None = Field(None, max_length=32)
    training_time_end: str | None = Field(None, max_length=32)
    duration_hours: float | None = Field(None)
    training_method: str | None = Field(None, max_length=32)
    trainer: str | None = Field(None, max_length=64)
    trainee_names: list[str] = Field(default_factory=list)
    assessment_method: str | None = Field(None, max_length=32)
    department: str | None = Field(None, max_length=64, description="培训部门（培训对象以「x部门 全体成员」展示）")
    # Post-training fields
    expected_count: int | None = Field(None, description="应到人数（模板标记 {部门总人数}）")
    actual_count: int | None = Field(None, description="实到人数（模板标记 {参与人数}）")
    absent_count: int | None = Field(None)
    sick_leave: int | None = Field(None)
    personal_leave: int | None = Field(None)
    maternity_leave: int | None = Field(None)
    exam_count: int | None = Field(None, description="参加考核人数（模板标记 {参加考核人数}）")
    excellent_count: int | None = Field(None)
    qualified_count: int | None = Field(None)
    unqualified_count: int | None = Field(None)
    participation_rate: str | None = Field(None, max_length=16)
    pass_rate: str | None = Field(None, max_length=16)
    conclusion: str | None = Field(None, max_length=1024)
    organizer: str | None = Field(None, max_length=64)
    organizer_date: date | None = Field(None)


# 模板 row15 的评价句原文（参与率与合格率都缺时整句替换为空）
_RATE_SENTENCE = (
    "参训人员参与率{#考核统计}{答题参与率}{/考核统计}，"
    "合格率{#考核统计}{答题及格率}{/考核统计}，达到培训效果。"
)


def _compute_hours(start: str | None, end: str | None) -> str:
    if not start or not end:
        return ""
    try:
        s = datetime.strptime(start, "%H:%M")
        e = datetime.strptime(end, "%H:%M")
        diff = (e - s).total_seconds() / 3600
        if diff <= 0:
            return ""
        rounded = round(diff * 2) / 2
        return f"{int(rounded)}h" if rounded == int(rounded) else f"{rounded}h"
    except ValueError:
        return ""


def _num(value: int | None) -> str:
    return "" if value is None else str(value)


def generate_training_evaluation(
    data: TrainingEvaluationInput,
    template_bytes: bytes | None = None,
) -> BytesIO:
    """Generate evaluation form from template (marker-based)."""
    raw = template_bytes or find_hr_template_bytes("training_evaluation")
    doc = Document(BytesIO(raw))

    date_str = data.training_date.strftime("%Y.%m.%d") if data.training_date else ""
    hours_str = _compute_hours(data.training_time_start, data.training_time_end)
    if not hours_str and data.duration_hours:
        h = data.duration_hours
        hours_str = f"{int(h)}h" if h == int(h) else f"{h}h"

    # 培训对象 — 统一「x部门 全体成员」
    if data.department:
        people = f"「{data.department}」全体成员"
        if data.trainee_names:
            people += f"（{len(data.trainee_names)}人）"
    else:
        people = "、".join(data.trainee_names) if data.trainee_names else ""

    mapping = {
        "{培训内容}": data.subject or "",
        "{实施日期}": date_str,
        "{课时}": hours_str,
        "{培训方式}": data.training_method or "",
        "{授课单位_培训师}": data.trainer or "",
        "{培训对象}": people,
        "{考核方式}": data.assessment_method or "",
        "{部门总人数}": _num(data.expected_count),
        "{参与人数}": _num(data.actual_count),
        "{事假}": _num(data.personal_leave),
        "{病假}": _num(data.sick_leave),
        "{产假}": _num(data.maternity_leave),
        "{参加考核人数}": _num(data.exam_count),
        "{优秀人数}": _num(data.excellent_count),
        "{合格人数}": _num(data.qualified_count),
        "{不合格人数}": _num(data.unqualified_count),
    }
    if data.participation_rate or data.pass_rate:
        mapping["{答题参与率}"] = data.participation_rate or ""
        mapping["{答题及格率}"] = data.pass_rate or ""
    else:
        # 两个比率都没有：整句评价隐藏（模板措辞被用户改过时句子键失配，
        # 退化为标记清空后的原句残留，可接受）
        mapping[_RATE_SENTENCE] = ""
    # 长标记优先（句子键包含比率标记，必须先替换）
    mapping = dict(sorted(mapping.items(), key=lambda kv: -len(kv[0])))
    replace_markers(doc, mapping)
    clear_unused_markers(doc)

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf
