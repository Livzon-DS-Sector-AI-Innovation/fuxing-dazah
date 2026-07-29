"""简历 PDF 解析器 - 基于 pdfplumber 提取文本后用规则匹配字段。"""

import re
from io import BytesIO


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_resume_pdf(file_bytes: bytes) -> dict:
    """解析简历PDF，返回 {name,phone,email,school,education,major,gender}。"""
    import pdfplumber

    text = ""
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text += t + "\n"

    text = _clean(text)

    return {
        "name": _extract_name(text),
        "phone": _extract_phone(text),
        "email": _extract_email(text),
        "school": _extract_school(text),
        "education": _extract_education(text),
        "major": _extract_major(text),
        "gender": _extract_gender(text),
    }


def _extract_name(text: str) -> str:
    # 取首行或"姓名"后的2-4个汉字
    m = re.search(r"姓名[：:]\s*([一-鿿]{2,4})", text)
    if m:
        return m.group(1)
    # 取首行中可能的姓名
    first_line = text.split("\n")[0]
    m = re.search(r"([一-鿿]{2,4})", first_line)
    return m.group(1) if m else ""


def _extract_phone(text: str) -> str:
    m = re.search(r"1[3-9]\d{9}", text)
    return m.group(0) if m else ""


def _extract_email(text: str) -> str:
    m = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
    return m.group(0) if m else ""


def _extract_school(text: str) -> str:
    for pat in [r"毕业院校[：:]\s*(\S+)", r"学校[：:]\s*(\S+)"]:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    # 模糊匹配"大学/学院"
    m = re.search(r"([一-鿿]{2,}(?:大学|学院))", text)
    return m.group(1) if m else ""


def _extract_education(text: str) -> str:
    m = re.search(r"学历[：:]\s*(\S+)", text)
    if m:
        return m.group(1)
    for level in ["博士", "硕士", "本科", "大专", "高中"]:
        if level in text:
            return level
    return ""


def _extract_major(text: str) -> str:
    m = re.search(r"专业[：:]\s*([^\n]{1,20})", text)
    if m:
        return m.group(1).strip()
    # 退而求其次：常见专业名
    for major in ["药学", "化学", "生物工程", "计算机科学", "软件工程", "机械工程", "会计", "人力资源"]:
        if major in text:
            return major
    return ""


def _extract_gender(text: str) -> str:
    m = re.search(r"性别[：:]\s*(\S+)", text)
    if m:
        return m.group(1)
    return ""
