"""Generate training sign-in sheet (签到表) from marker-based Word template.

Uses the user-maintainable template (markers documented in
training_template_registry, key ``training_signin_sheet``).  Each page loads a
fresh copy of the template, fills metadata markers and clones the ``{姓名}``
template row for every employee; pages are combined into a single .docx with
page breaks in between.  Header markers ``{页码}`` / ``{总页数}`` are replaced
with Word PAGE / NUMPAGES fields so multi-page copies keep real page numbers.
"""

import copy
from datetime import datetime
from io import BytesIO

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.modules.hr.docx_markers import (
    clear_unused_markers,
    find_row_index_by_marker,
    remove_row,
    replace_markers,
    replace_markers_in_row,
)
from app.modules.hr.schemas import TrainingSignInSheetInput
from app.modules.hr.template_utils import find_hr_template_bytes

EMPLOYEES_PER_PAGE = 15

# 页眉页码标记（缺失时页码保持模板原样，不影响导出）
PAGE_MARKER = "{页码}"
TOTAL_MARKER = "{总页数}"

# 员工签到模板行定位标记与行内标记
NAME_MARKER = "{姓名}"
DEPT_MARKER = "{体现部门}"


def _compute_duration_hours(start: str | None, end: str | None) -> str:
    if not start or not end:
        return ""
    try:
        s = datetime.strptime(start, "%H:%M")
        e = datetime.strptime(end, "%H:%M")
        diff_hours = (e - s).total_seconds() / 3600
        if diff_hours <= 0:
            return ""
        rounded = round(diff_hours * 2) / 2
        if rounded == int(rounded):
            return f"{int(rounded)}小时"
        return f"{rounded}小时"
    except ValueError:
        return ""


def _dash(text: str | None) -> str:
    """没填的项写横杠，导出的签到表不留空白格（与培训通知同口径）."""
    return text if text and text.strip() else "—"


def _fmt_date(d, t_start: str | None, t_end: str | None, label: str) -> str:
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


def _compute_hours_text(data: TrainingSignInSheetInput) -> str:
    if data.time_slots:
        total_minutes = 0
        for s in data.time_slots:
            t_start = s.get("start", "")
            t_end = s.get("end", "")
            if t_start and t_end:
                try:
                    s_dt = datetime.strptime(t_start, "%H:%M")
                    e_dt = datetime.strptime(t_end, "%H:%M")
                    diff = (e_dt - s_dt).total_seconds() / 60
                    if diff > 0:
                        total_minutes += diff
                except ValueError:
                    pass
        total_hours = round(total_minutes / 30) / 2
        if total_hours <= 0:
            return ""
        return f"{int(total_hours)}小时" if total_hours == int(total_hours) else f"{total_hours}小时"
    face_start = getattr(data, "face_to_face_time_start", None) or data.training_time_start
    face_end = getattr(data, "face_to_face_time_end", None) or data.training_time_end
    return _compute_duration_hours(face_start, face_end)


def _compute_date_text(data: TrainingSignInSheetInput) -> str:
    if data.time_slots:
        slot_parts = []
        for s in data.time_slots:
            d = s.get("date", "")
            if d:
                slot_parts.append(_fmt_slot(d, s.get("start", ""), s.get("end", "")))
        return "；".join(slot_parts)
    face_date = getattr(data, "face_date", None) or data.training_date
    self_date = getattr(data, "self_study_date", None)
    self_start = getattr(data, "self_study_time_start", None)
    self_end = getattr(data, "self_study_time_end", None)
    face_start = getattr(data, "face_to_face_time_start", None) or data.training_time_start
    face_end = getattr(data, "face_to_face_time_end", None) or data.training_time_end
    parts = []
    # 面授必须有时间才写，自学只选了日期也要写
    face_part = _fmt_date(face_date, face_start, face_end, "面授") if face_start else ""
    if face_part:
        parts.append(face_part)
    if self_date:
        parts.append(_fmt_date(self_date, self_start, self_end, "自学"))
    date_text = "；".join(parts)
    return date_text or (str(data.training_date) if data.training_date else "")


def _compute_trainee_text(data: TrainingSignInSheetInput) -> str:
    """培训对象（「x部门 + 群体词」，缺省群体词=全体成员，与培训通知同口径；病假/产假人数可省略）。

    trainee_group / omit_leave_note 走 getattr：兼容各调用方的本地 Input 类。
    """
    group = (getattr(data, "trainee_group", None) or "").strip() or "全体成员"
    people = f"「{data.department}」{group}"
    if getattr(data, "omit_leave_note", False):
        return people
    sick = data.sick_count if data.sick_count is not None else 0
    maternity = data.maternity_count if data.maternity_count is not None else 0
    return people + f"（病假{sick}人、产假{maternity}人除外）"


def _fill_metadata(doc: Document, data: TrainingSignInSheetInput) -> None:
    """Fill metadata markers (whole document scope; employee row markers untouched)."""
    replace_markers(doc, {
        "{培训内容}": _dash(data.topic),
        "{培训对象}": _compute_trainee_text(data),
        "{培训方式}": _dash(data.training_method),
        "{课时}": _dash(_compute_hours_text(data)),
        "{考核方式}": _dash(data.assessment_method),
        "{实施日期}": _dash(_compute_date_text(data)),
    })


def _fill_employee_rows(table, employee_names: list[str], employee_departments: dict[str, str], default_department: str) -> None:
    """Clone the ``{姓名}`` template row for each employee and fill name + department."""
    tpl_idx = find_row_index_by_marker(table, NAME_MARKER)
    if tpl_idx is None:
        return

    tpl_row = table.rows[tpl_idx]
    footer_tr = table.rows[-1]._tr  # 培训师签字行固定是最后一行
    if not employee_names:
        # 无人员：移除模板行（与历史行为一致，不保留空白签到行）
        remove_row(table, tpl_idx)
        return
    # 先从干净模板行克隆出其余数据行，再逐行填充（第一人直接填模板行）
    for _ in range(len(employee_names) - 1):
        footer_tr.addprevious(copy.deepcopy(tpl_row._tr))
    for offset, name in enumerate(employee_names):
        replace_markers_in_row(table.rows[tpl_idx + offset], {
            NAME_MARKER: name,
            DEPT_MARKER: employee_departments.get(name, default_department),
        })


def _set_word_field(run, instr: str) -> None:
    """把静态页码 run 换成 Word 域（PAGE / NUMPAGES），多页共用页眉也能显示各自页码。"""
    run.text = ""
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), instr)
    inner_r = OxmlElement("w:r")
    inner_t = OxmlElement("w:t")
    inner_t.text = "1"
    inner_r.append(inner_t)
    fld.append(inner_r)
    run._r.addnext(fld)


def _update_section_header_page_numbers(doc: Document) -> None:
    """把页眉中的 {页码} / {总页数} 标记替换为 Word 页码域；缺失时保持模板原样。"""
    for section in doc.sections:
        header = section.header
        if header is None:
            continue
        for paragraph in header.paragraphs:
            for run in paragraph.runs:
                if PAGE_MARKER in run.text:
                    _set_word_field(run, " PAGE ")
                elif TOTAL_MARKER in run.text:
                    _set_word_field(run, " NUMPAGES ")


# ─── public API ───

def _build_page_doc(template_bytes: bytes, data: TrainingSignInSheetInput,
                    names: list[str], *, is_last_page: bool) -> Document:
    doc = Document(BytesIO(template_bytes))
    _fill_metadata(doc, data)

    table = doc.tables[0]
    _fill_employee_rows(table, names, data.employee_departments, data.department)

    # Remove trainer signature row for non-last pages (it only appears on the final page)
    if not is_last_page and len(table.rows) > 0:
        remove_row(table, len(table.rows) - 1)

    _update_section_header_page_numbers(doc)
    clear_unused_markers(doc)
    return doc


def generate_training_sign_in_sheet(
    data: TrainingSignInSheetInput,
    template_bytes: bytes | None = None,
) -> BytesIO:
    """Generate sign-in sheet from template, matching the preview layout.

    Page 1 is built directly in the template document (preserves header images).
    Pages 2+ are built in fresh template loads, then their tables are inserted
    into the output document with page breaks before each.
    """
    raw = template_bytes or find_hr_template_bytes("training_signin_sheet")
    total = len(data.employee_names)
    total_pages = max(1, (total + EMPLOYEES_PER_PAGE - 1) // EMPLOYEES_PER_PAGE)

    # Page 1: build directly in template (preserves header with logo)
    output_doc = _build_page_doc(raw, data, data.employee_names[:EMPLOYEES_PER_PAGE],
                                 is_last_page=total_pages == 1)

    # Pages 2+: build new tables in fresh template loads, then append with page breaks.
    for page_idx in range(1, total_pages):
        start = page_idx * EMPLOYEES_PER_PAGE
        end = min(start + EMPLOYEES_PER_PAGE, total)
        page_doc = _build_page_doc(raw, data, data.employee_names[start:end],
                                   is_last_page=page_idx == total_pages - 1)

        output_doc.add_page_break()
        body = output_doc.element.body
        sect_pr = body.find(qn("w:sectPr"))
        imported = copy.deepcopy(page_doc.tables[0]._tbl)
        if sect_pr is not None:
            body.insert(list(body).index(sect_pr), imported)
        else:
            body.append(imported)

    buf = BytesIO()
    output_doc.save(buf)
    buf.seek(0)
    return buf
