"""培训通知 Word 文档生成器 — 基于 {标记} 模板（模板可由用户自维护）。

模板标记清单见 training_template_registry（键 training_notification）。
填充口径（自学只记日期、空值写横杠等）与历史版本一致：本模块只负责
「计算填充值 → 替换模板标记」，模板结构与样式由模板文件决定。
"""

from datetime import date, datetime
from io import BytesIO

from docx import Document
from pydantic import BaseModel

from app.modules.hr.docx_markers import clear_unused_markers, replace_markers
from app.modules.hr.template_utils import find_hr_template_bytes


class TrainingNotificationInput(BaseModel):
    department: str
    training_date: date
    subject: str
    training_time_start: str | None = None
    training_time_end: str | None = None
    face_to_face_time_start: str | None = None
    face_to_face_time_end: str | None = None
    self_study_time_start: str | None = None
    self_study_time_end: str | None = None
    face_date: date | None = None
    self_study_date: date | None = None
    time_slots: list[dict] | None = None
    location: str | None = None
    trainer: str | None = None
    training_method: str | None = None
    assessment_method: str | None = None
    content: str | None = None
    trainee_names: list[str] = []
    sick_count: int | None = None
    maternity_count: int | None = None
    issuer_department: str | None = None
    issue_date: date | None = None


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
        if rounded == int(rounded):
            return f"{int(rounded)}小时"
        return f"{rounded}小时"
    except ValueError:
        return ""


def _dash(text: str | None) -> str:
    """没填的项写横杠，导出的通知不留空白格."""
    return text if text and text.strip() else "—"


def _fmt_date(d: date | None, t_start: str | None, t_end: str | None, label: str) -> str:
    """「标签：日期 起止时间」；没有起止时间（自学）时只写「标签：日期」."""
    if not d:
        return ""
    ds = f"{d.year}年{d.month}月{d.day}日"
    if t_start and t_end:
        return f"{label}：{ds} {t_start}—{t_end}"
    if t_start:
        return f"{label}：{ds} {t_start}"
    return f"{label}：{ds}"


def _fmt_slot(d: str, t_start: str, t_end: str) -> str:
    """「日期 起止时间」；没有起止时间（自学）时只写日期."""
    if not d:
        return ""
    if t_start and t_end:
        return f"{d} {t_start}—{t_end}"
    if t_start:
        return f"{d} {t_start}"
    return d


def _compute_date_and_hours(data: TrainingNotificationInput) -> tuple[str, str]:
    """培训日期与时段文本、课时文本（多时段优先，否则回退旧字段）。"""
    if data.time_slots:
        slot_parts = []
        total_minutes = 0
        for s in data.time_slots:
            d = s.get("date", "")
            t_start = s.get("start", "")
            t_end = s.get("end", "")
            if d:
                slot_parts.append(_fmt_slot(d, t_start, t_end))
            if t_start and t_end:
                try:
                    s_dt = datetime.strptime(t_start, "%H:%M")
                    e_dt = datetime.strptime(t_end, "%H:%M")
                    diff = (e_dt - s_dt).total_seconds() / 60
                    if diff > 0:
                        total_minutes += diff
                except ValueError:
                    pass
        date_text = "；".join(slot_parts)
        total_hours = round(total_minutes / 30) / 2
        hours_text = "" if total_hours <= 0 else (
            f"{int(total_hours)}小时" if total_hours == int(total_hours) else f"{total_hours}小时"
        )
        return date_text, hours_text

    face_start = getattr(data, "face_to_face_time_start", None) or data.training_time_start
    face_end = getattr(data, "face_to_face_time_end", None) or data.training_time_end
    self_start = getattr(data, "self_study_time_start", None)
    self_end = getattr(data, "self_study_time_end", None)
    face_date = getattr(data, "face_date", None) or data.training_date
    self_date = getattr(data, "self_study_date", None)
    parts = []
    # 格式化中文日期；面授必须有时间才写，自学只选了日期也要写
    face_part = _fmt_date(face_date, face_start, face_end, "面授") if face_start else ""
    if face_part:
        parts.append(face_part)
    if self_date:
        parts.append(_fmt_date(self_date, self_start, self_end, "自学"))
    date_text = "；".join(parts) if parts else (str(data.training_date) if data.training_date else "")
    # 课时仅按面授时间计算
    return date_text, _compute_hours(face_start, face_end)


def _compute_trainee_text(data: TrainingNotificationInput) -> str:
    """培训对象统一以「x部门 全体成员」展示，不再列人名；附病假/产假人数。"""
    if data.trainee_names:
        people = f"「{data.department}」全体成员（{len(data.trainee_names)}人）"
    else:
        people = f"「{data.department}」全体成员"
    sick = data.sick_count if data.sick_count is not None else 0
    maternity = data.maternity_count if data.maternity_count is not None else 0
    people += f"（病假{sick}人、产假{maternity}人除外）"
    return people


def _compute_issue_date_str(data: TrainingNotificationInput) -> str:
    """落款日期优先使用显式 issue_date；否则取首个 time_slot / 培训日期。"""
    issue_d = data.issue_date or data.training_date
    if data.issue_date is None and data.time_slots:
        first_slot_date = data.time_slots[0].get("date", "")
        if first_slot_date:
            try:
                issue_d = datetime.strptime(first_slot_date, "%Y-%m-%d").date()
            except ValueError:
                pass
    d = issue_d
    if not d:
        return ""
    return f"{d.year}年{d.month:02d}月{d.day:02d}日"


def generate_training_notification(
    data: TrainingNotificationInput,
    template_bytes: bytes | None = None,
) -> BytesIO:
    """Generate training notification docx from template (marker-based)."""
    raw = template_bytes or find_hr_template_bytes("training_notification")
    doc = Document(BytesIO(raw))

    date_text, hours_text = _compute_date_and_hours(data)
    topic_parts = [data.subject]
    if data.content:
        topic_parts.append(data.content)

    mapping = {
        # 页眉：部门/Dept 行与落款日期行
        "{体现部门}": data.issuer_department or data.department or "",
        "{签发日期}": _compute_issue_date_str(data),
        # 表格
        "{培训内容}": _dash(" — ".join(topic_parts)),
        "{实施日期}": _dash(date_text),
        "{课时}": _dash(hours_text),
        "{培训方式}": _dash(data.training_method),
        "{授课单位_培训师}": _dash(data.trainer),
        "{培训对象}": _compute_trainee_text(data),
        "{培训地点}": _dash(data.location),
        "{考核方式}": _dash(data.assessment_method),
    }
    # 长标记优先（防御性：若模板里出现包含其他标记的组合标记不会被截断）
    mapping = dict(sorted(mapping.items(), key=lambda kv: -len(kv[0])))
    replace_markers(doc, mapping)
    # 用户模板里多写的不支持标记清理掉，避免字面量出现在导出文件
    clear_unused_markers(doc)

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf
