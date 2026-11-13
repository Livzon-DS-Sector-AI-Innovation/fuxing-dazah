"""简历 PDF 解析器 - 基于 pdfplumber 提取文本后用规则匹配字段。"""

import re
from datetime import date
from io import BytesIO


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_resume_pdf(file_bytes: bytes) -> dict:
    """解析简历PDF，返回字段字典。"""
    import pdfplumber

    raw_text = ""
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                raw_text += t + "\n"

    text = _clean(raw_text)

    # 工作经历信息（用原始文本解析，保留换行）
    company_info = _extract_company_info(raw_text)

    return {
        "name": _extract_name(text),
        "phone": _extract_phone(text),
        "email": _extract_email(text),
        "school": _extract_school(text),
        "education": _extract_education(text),
        "major": _extract_major(text),
        "gender": _extract_gender(text),
        "current_company": company_info["current_company"],
        "work_years": company_info["work_years"],
        "expected_salary": _extract_expected_salary(text),
        "source": _extract_source(text),
    }


# 简历文档中常见的标题词（不是姓名，不能作为候选名）
_NAME_BLOCKLIST = {
    "个人简历", "个人简介", "基本信息", "个人资料", "求职意向", "求职简历",
    "应聘登记", "简历模板", "联系电话", "教育背景", "工作经历",
    # 平台导出模板的基本信息区标签（兜底窗口会扫到）
    "姓名", "性别", "出生年月", "籍贯", "现居", "民族", "婚姻状况",
    "政治面貌", "身高", "体重", "手机", "电话", "电子邮箱", "邮箱",
}


def _extract_name(text: str) -> str:
    # 常规简历：标签与姓名均无空格
    m = re.search(r"姓名[：:]\s*([一-鿿]{2,4})", text)
    if m:
        return m.group(1)
    # 招聘平台导出的 PDF 常因字距排版插入空格：「姓 名： 练 珊 出生年月：…」
    # 键容忍空格；值捕获 2-4 个中文（字间可有空格），以「非中文非空格字符 /
    # 下一个中文标签带冒号 / 行尾」为界，防止把后续标签吞进姓名
    m = re.search(
        r"姓\s*名\s*[：:]\s*((?:[一-鿿]\s*){2,4}?)"
        r"(?=\s*[^\s一-鿿]|\s+(?:[一-鿿]\s*){2,}[：:]|\s*$)",
        text,
    )
    if m:
        return re.sub(r"\s+", "", m.group(1))
    # 兜底：文档开头无姓名标签时，取前 60 字符窗口内的首个姓名候选。
    # （窗口 30→60：平台导出 PDF 开头常有一段水印/单字竖排噪声先占十几个字符）
    # 按空白切 token 扫描，支持两种形态：
    # - 连续 2-4 字中文 token（常规简历：首行就是名字）
    # - 相邻单字中文 token 游程拼接（字距排版把姓名拆成「翁 甜」）
    tokens = text[:60].split()
    run: list[str] = []  # 当前相邻单字中文游程
    for tok in tokens:
        if len(tok) == 1 and "一" <= tok <= "鿿":
            run.append(tok)
            if len(run) > 4:  # 超长游程不是姓名（如竖排水印整列）
                run = run[-4:]
            continue
        # 游程结束：2-4 个单字拼成候选
        if 2 <= len(run) <= 4:
            return "".join(run)
        run = []
        # 连续 2-4 字纯中文 token
        if 2 <= len(tok) <= 4 and all("一" <= ch <= "鿿" for ch in tok) and tok not in _NAME_BLOCKLIST:
            return tok
    if 2 <= len(run) <= 4:
        return "".join(run)
    return ""


def _extract_phone(text: str) -> str:
    m = re.search(r"1[3-9]\d{9}", text)
    return m.group(0) if m else ""


def _extract_email(text: str) -> str:
    m = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
    return m.group(0) if m else ""


def _extract_school(text: str) -> str:
    for pat in [r"毕\s*业\s*院\s*校\s*[：:]\s*(\S+)", r"学\s*校\s*[：:]\s*(\S+)"]:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    m = re.search(r"([一-鿿]{2,}(?:大学|学院))", text)
    return m.group(1) if m else ""


def _extract_education(text: str) -> str:
    """解析学历，优先返回已毕业的最高学历（"至今"标记的视为在读）。"""
    m = re.search(r"学\s*历\s*[：:]\s*(\S+)", text)
    if m:
        return m.group(1)

    # 截取教育经历段落
    edu_section = ""
    m_sec = re.search(r"教育经历(.*?)(?:工作经历|项目经历|相关技能|荣誉证书|$)", text, re.DOTALL)
    if m_sec:
        edu_section = m_sec.group(1)
    else:
        edu_section = text

    # 按日期+学历块匹配：判断每条教育经历是否"至今"
    LEVEL_RANK = {"博士": 5, "硕士": 4, "本科": 3, "大专": 2, "专科": 2, "高中": 1}
    best_completed = ""  # 已毕业的最高学历
    best_completed_rank = 0
    best_any = ""  # 包括在读的最高学历
    best_any_rank = 0

    for level_name, rank in LEVEL_RANK.items():
        # 找该学历名出现的位置
        for lm in re.finditer(re.escape(level_name), edu_section):
            pos = lm.start()
            # 往前面一段文本找日期，看是否包含"至今"
            before = edu_section[max(0, pos - 60):pos]
            is_ongoing = "至今" in before and re.search(r"\d{4}\.\d{2}\s*[-~—至]\s*至今", before)
            if is_ongoing:
                if rank > best_any_rank:
                    best_any_rank = rank
                    best_any = level_name
            else:
                if rank > best_completed_rank:
                    best_completed_rank = rank
                    best_completed = level_name
                if rank > best_any_rank:
                    best_any_rank = rank
                    best_any = level_name

    if best_completed:
        return best_completed
    if best_any:
        return best_any

    # 兜底
    for level in ["博士", "硕士", "本科", "大专", "专科", "高中"]:
        if level in text:
            return level
    return ""


def _extract_major(text: str) -> str:
    # 标签后贪婪取中文段（容忍字间空格），以首个非中文非空白字符为界——
    # 直聘 PDF 值后紧跟的水印噪声（「专业：生物制药 9 1 1f 1f c c b」中的
    # 数字/字母碎片）与「药学类（方向）」的括号说明都会自然截断
    m = re.search(r"专\s*业\s*[：:]\s*([一-鿿](?:[\s]?[一-鿿]){1,19})", text)
    if m:
        # 先合并字间空格，再截掉粘连的下一栏标签词（如「学 历：」→「学历」）
        val = re.sub(r"\s+", "", m.group(1))
        for tail in ("毕业院校", "求职意向", "求职方向", "工作经历", "教育经历", "专业技能",
                     "专业证书", "学历", "学校", "电话", "手机", "邮箱", "性别", "出生年月", "政治面貌"):
            idx = val.find(tail)
            if idx > 0:
                val = val[:idx]
                break
        return val
    for major in ["药学", "化学", "生物工程", "计算机科学", "软件工程", "机械工程", "会计", "人力资源",
                  "制药工程", "生物技术", "药物分析", "分析化学", "临床医学"]:
        if major in text:
            return major
    return ""


def _extract_gender(text: str) -> str:
    m = re.search(r"性别[：:]\s*(\S+)", text)
    if m:
        return m.group(1)
    # 字距空格版：「性 别： 女 籍 贯：…」——键容忍空格，值限定 1-2 字中文
    # （后随空格/非中文即止，防止吞掉下一标签）
    m = re.search(r"性\s*别\s*[：:]\s*([一-鿿]{1,2})(?=[^\s一-鿿]|\s|$)", text)
    if m:
        return m.group(1)
    return ""


def _extract_expected_salary(text: str) -> str:
    """提取期望薪资，如 8k-10k、8000-10000、8-10K 等。"""
    for pat in [
        r"期\s*望\s*薪\s*资\s*[：:]\s*([^\n]{2,20}?)(?:\s|$|，|。|\n)",
        r"薪\s*资\s*要\s*求\s*[：:]\s*([^\n]{2,20}?)(?:\s|$|，|。|\n)",
    ]:
        m = re.search(pat, text)
        if m:
            return m.group(1).strip().rstrip("，。")
    # 模糊匹配
    m = re.search(r"(\d+[kKwW]\s*[-~—]\s*\d+[kKwW])", text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"(\d+[-~—]\d+[kKwW])", text, re.IGNORECASE)
    if m:
        return m.group(1)
    return ""


def _extract_source(text: str) -> str:
    """从简历文本推断来源渠道。"""
    if "BOSS" in text or "直聘" in text:
        return "BOSS直聘"
    if "智联" in text:
        return "智联招聘"
    if "前程无忧" in text or "51job" in text.lower():
        return "前程无忧"
    if "猎聘" in text:
        return "猎聘"
    if "内推" in text:
        return "内推"
    return "自主上传"


def _extract_company_info(text: str) -> dict:
    """提取当前公司和工作年限。

    只在"工作经历"段落中查找，严格排除教育经历。
    """
    # 截取工作经历段落：从"工作经历"到"教育经历/项目经历/技能/证书"
    exp_section = ""
    m = re.search(
        r"工作经历(.*?)(?:教育经历|项目经历|相关技能|荣誉证书|技能证书|自我评价|求职意向|$)",
        text, re.DOTALL,
    )
    if m:
        exp_section = m.group(1).strip()

    # 逐行解析：日期行格式如 "2026.06 - 至今 公司名" 或日期行后紧跟独立公司名行
    lines = [l.strip() for l in exp_section.split("\n") if l.strip()]
    date_pattern = re.compile(r"^(\d{4}\.\d{2})\s*[-~—至]\s*(至今|\d{4}\.\d{2})\s*(.*)")

    experiences: list[tuple[str, str, str]] = []  # (start, end, company)
    for i, line in enumerate(lines):
        dm = date_pattern.match(line)
        if dm:
            start_date = dm.group(1)
            end_date = dm.group(2)
            # 公司名：同行日期之后的文本（最多取到一个分隔符）
            rest = dm.group(3).strip()
            if rest:
                # 截断：取到 | / · / 空格为止的关键部分
                company = re.split(r"\s*[|/·]\s*", rest, maxsplit=1)[0].strip()
                # 限制长度，避免吞掉整段描述
                if len(company) > 30:
                    company = company[:30]
            elif i + 1 < len(lines):
                # 公司名在下一行单独出现
                company = lines[i + 1].strip().rstrip("|").strip()
                if len(company) > 30:
                    company = company[:30]
            else:
                continue

            # 过滤空值或学校名
            if not company or len(company) < 2:
                continue
            if _is_school(company):
                continue
            experiences.append((start_date, end_date, company))

    # 找当前公司（最早的"至今"）
    current_company = ""
    earliest_year = None

    for start_date, end_date, company in experiences:
        if end_date == "至今":
            if not current_company:
                current_company = f"{company}({start_date}-至今)"
        try:
            year = int(start_date.split(".")[0])
            if earliest_year is None or year < earliest_year:
                earliest_year = year
        except (ValueError, IndexError):
            pass

    # 计算工作年限
    work_years = None
    if earliest_year:
        this_year = date.today().year
        work_years = this_year - earliest_year

    return {
        "current_company": current_company,
        "work_years": work_years,
    }


# 常见学校关键词，用于排除误匹配
_SCHOOL_KEYWORDS = {"大学", "学院", "学校", "中学", "小学", "幼儿园", "职业技术", "education"}


def _is_school(name: str) -> bool:
    """判断名称是否为学校而非公司。"""
    for kw in _SCHOOL_KEYWORDS:
        if kw in name:
            return True
    return False
