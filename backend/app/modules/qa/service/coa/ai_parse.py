"""COA docx → 结构化草稿：DeepSeek OCR + deepseek-flash 提取 + 确定性复判。

客户 COA 模板多达数百份、版式各异，锚定规则无法泛化 → 版式理解交给模型：
docx 先经 /v1/tools/ocr（purpose=text_recognition）识别为文本——无图 Word
走文档层直接抽取，输出 HTML 表格且保留 rowspan/colspan 跨行合并标记；
再由 deepseek-flash 按固定 schema 提取 JSON（中英分列，治字段粘英文的
问题）。数值语义不信任模型——parse_number/parse_spec/parse_date_text
逐字段重算覆盖（防「＜1cfu/g → 1」丢比较符）。输出仅作草稿预览，正式
落库走人工确认，与 qa 域「AI 只产提案」同口径。

弃用 /files 文件解析 + file_id 引用链路的原因：flash 引用 file_id 时
reasoning 消耗不稳定（实测 6 跑 3 次 finish_reason=length 撞输出上限），
OCR 纯文本输入 completion 稳定在 3~5k 且识别更快、token 更省。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from io import BytesIO
from typing import Any

import httpx
from docx import Document

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.modules.qa.service.coa.docx_parse import (
    CoaDocxParse,
    CoaParsedField,
    CoaParsedItem,
    normalize,
    parse_date_text,
    parse_number,
    parse_spec,
    parse_unit,
    split_bilingual,
)

logger = logging.getLogger(__name__)

# 两个提取场景各自演进：结构版（模板导入→产品字段配置+标准定义）/
# 值版（报告导入→批次值+结果，阶段二按配置动态渲染 schema）
COA_AI_PROMPT_VERSION_STRUCTURE = "coa-docx-structure-v1"
COA_AI_PROMPT_VERSION_VALUES = "coa-docx-values-v4"

# 实测（万古/达托/达巴模板）：OCR 识别 ~4s、提取 ~13s。OCR 服务端总时长
# 限 180s（上传+识别+返回），客户端放宽到 200s 防慢文档偶发超时
_OCR_TIMEOUT = 200.0
_EXTRACT_TIMEOUT = 300.0
# reasoning 占 5~6k token、30 项正文 ~2.5k——留足余量防 finish_reason=length
_MAX_TOKENS = 16384

# 结果含比较符时模型给的 value_num 不可信（＜1 ≠ 1），一律作废
_CMP_RE = re.compile(r"[<>≤≥]")

_PROMPT_STRUCTURE = """你是制药 QA 系统的数据抽取器。文档是一份产品检验报告单（COA, Certificate of Analysis）的标准模板，版式可能各不相同。模板通常只有结构（字段标签、检测项目与标准）没有填写数据，请只提取结构信息，输出一个 json 对象，不要输出任何其他文字。

json 结构（字段名固定，所有字段必须出现，没有的用 null）：
{
  "report_no": "报告编号：以 No. / 编号 / Report No. 标签引导的编号串，写法可能是 No.、No:、No.:、No：等；常见形态 COA-产品码-编号码-版本码（如 COA-DA-3310-006）",
  "batch_info_fields": [
    {"label_cn": "批次信息区字段的中文标签", "label_en": "对应英文标签或 null"}
  ],
  "batch_info": {
    "product": "品名（中英文原文）"
  },
  "items": [
    {
      "name_cn": "检测项目中文名",
      "name_en": "英文译名",
      "unit": "检测项目的单位",
      "spec_text": "标准列中文原文",
      "spec_text_en": "标准列英文原句",
      "spec_min": "数值下限",
      "spec_max": "数值上限"
    }
  ]
}

抽取规则：
1. batch_info_fields 按文档出现顺序列出批次信息区的全部字段标签（如 品名/批号/包装规格/生产日期/复验期/储存条件），只提取标签本身，不提取值（模板中值通常为空）；
2. items 按检测项目表逐行输出，不遗漏、不合并；跨行的大类分组标签（如 性状/鉴别/检查）不是检测项目，不要输出；
3. 项目名列跨行合并（多行共享同一名称）而标准列各不相同的，必须逐行输出，并把标准列开头的限定语合入项目名使名称唯一（合入后 spec_text 不再重复限定语）。例：名称列「在万古霉素B之前洗脱的其他任意杂质」、标准列「任意单个杂质≤0.8%」→ name_cn「在万古霉素B之前洗脱的任意单个杂质」、spec_text「≤0.8%」；标准列「＞0.30%的杂质不得超过5个」→ name_cn「在万古霉素B之前洗脱的＞0.30%的杂质」、spec_text「不得超过5个」；
4. name_cn 只含中文与必要代号（RS1、万古霉素B 中的代号是中文名的一部分）；英文译名进 name_en；
5. spec_text 只保留中文部分；纯数值/单位（如 ≤3.0%）原样保留；对应英文原句进 spec_text_en；
6. unit：该检测项目的计量单位，取标准中的单位原文（如 %、ppm、cfu/g、µg/mg、EU/mg）；无量纲（pH、吸光度）与文字型项目为 null；
7. spec_min / spec_max：≥/大于 形式取下限，≤/小于 形式取上限，区间 a～b 两者都给；无数值限则 null；
8. 所有文本照抄原文，保留全角字符与原文标点（～、℃、＜），禁止规范化改写。"""

_PROMPT_VALUES = """你是制药 QA 系统的数据抽取器。文档是一份产品检验报告单（COA, Certificate of Analysis），版式可能各不相同，请抽取结构化数据，只输出一个 json 对象，不要输出任何其他文字。

json 结构（字段名固定，所有字段必须出现，没有的用 null）：
{
  "serial_no": "标题或右上角的印刷流水号（纯数字占位，如 XXXXXXXX 不是编号）",
  "report_no": "报告编号：以 No. / 编号 / Report No. 标签引导的编号串，写法可能是 No.、No:、No.:、No：等；常见形态 COA-产品码-编号码-版本码（如 COA-DA-3310-006）",
  "batch_info": {
    "product": "品名（中英文原文）",
    "batch_no": "批号",
    "packaging": "包装规格",
    "batch_size": "批量",
    "mfg_date": "生产日期（原文照抄）",
    "exp_date": "有效期（原文照抄）",
    "storage": "储存条件（中文原文）"
  },
  "batch_info_fields": [
    {"label_cn": "上面 batch_info 未覆盖的其余批次信息字段中文标签（如 复验期）", "label_en": "英文标签", "value": "对应值原文"}
  ],
  "conclusion": "结论（中文原文）",
  "items": [
    {
      "name_cn": "检测项目中文名",
      "name_en": "英文译名",
      "unit": "检测项目的单位",
      "spec_text": "标准列中文原文",
      "spec_text_en": "标准列英文原句",
      "result": "结果列中文原文",
      "result_en": "结果列英文",
      "spec_min": "数值下限",
      "spec_max": "数值上限",
      "value_num": "结果数值"
    }
  ]
}

抽取规则：
1. items 按检测项目表逐行输出，不遗漏、不合并；跨行的大类分组标签（如 性状/鉴别/检查）不是检测项目，不要输出；
2. 项目名列跨行合并（多行共享同一名称）而标准列各不相同的，必须逐行输出，并把标准列开头的限定语合入项目名使名称唯一（合入后 spec_text 不再重复限定语）。例：名称列「在万古霉素B之前洗脱的其他任意杂质」、标准列「任意单个杂质≤0.8%」→ name_cn「在万古霉素B之前洗脱的任意单个杂质」、spec_text「≤0.8%」；标准列「＞0.30%的杂质不得超过5个」→ name_cn「在万古霉素B之前洗脱的＞0.30%的杂质」、spec_text「不得超过5个」；
3. name_cn 只含中文与必要代号（RS1、万古霉素B、N-亚硝基-万古霉素 中的代号是中文名的一部分）；英文译名进 name_en；
4. spec_text / result 只保留中文部分；纯数值/单位（如 ≤3.0%、0.63%）原样保留；对应英文原句进 spec_text_en / result_en；
5. unit：该检测项目的计量单位，取标准或结果中的单位原文（如 %、ppm、cfu/g、µg/mg、EU/mg）；无量纲（pH、吸光度）与文字型项目为 null；
6. spec_min / spec_max：≥/大于 形式取下限，≤/小于 形式取上限，区间 a～b 两者都给；无数值限则 null；
7. value_num：结果中的纯数值（去掉单位与 %）；结果含比较符（如 ＜1）或为判定词（如 符合规定）时必须 null；
8. batch_info_fields 只列上面 7 个固定键未覆盖的其余批次信息（如 复验期/Re-test Date），逐项给出标签与值；没有这类字段时返回空数组；
9. 所有文本照抄原文，保留全角字符与原文标点（～、℃、＜），禁止规范化改写；日期保留原文格式。"""


def _require_ai() -> None:
    settings = get_settings()
    if not settings.QA_AI_ENABLED or not settings.QA_AI_API_KEY:
        raise AppException(
            status_code=503, message="AI 服务未配置，COA 导入需要启用 QA_AI_* 配置"
        )


def _ocr_path(base_url: str) -> str:
    """OCR 端点固定在 /v1 下：base 已带 /v1 时不再重复前缀。"""
    return "/tools/ocr" if base_url.rstrip("/").endswith("/v1") else "/v1/tools/ocr"


async def _ocr_recognize(
    client: httpx.AsyncClient, filename: str, content: bytes
) -> str:
    """OCR 识别 docx（表单 purpose 字段必须在 file 之前），返回分页拼接文本。

    text_recognition 对无图 Word 走文档层直接抽取：输出 HTML 表格且保留
    rowspan/colspan，跨行合并结构对 flash 显式可见。注意 rich_layout_
    recognition 是渲染逐页视觉识别，会丢跨行合并细节、偶丢编号行，勿用。
    """
    resp = await client.post(
        _ocr_path(str(client.base_url)),
        data={"purpose": "text_recognition"},
        files={"file": (filename, content)},
        timeout=_OCR_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"OCR 识别失败 HTTP {resp.status_code}: {resp.text[:200]}"
        )
    pages = resp.json().get("pages") or []
    text = "\n\n".join(str(page.get("text") or "") for page in pages)
    if not text.strip():
        raise RuntimeError("OCR 未识别到文本（pages 为空）")
    return text


async def _chat_extract(
    client: httpx.AsyncClient, document_text: str, prompt: str
) -> dict[str, Any]:
    """deepseek-flash 按 schema 提取 OCR 文本，返回 JSON 载荷。"""
    resp = await client.post(
        "/chat/completions",
        json={
            "model": get_settings().QA_AI_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": f"{prompt}\n\n<document>\n{document_text}\n</document>",
                }
            ],
            "temperature": 0,
            "max_tokens": _MAX_TOKENS,
            "response_format": {"type": "json_object"},
        },
        timeout=_EXTRACT_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"模型提取失败 HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if data["choices"][0].get("finish_reason") != "stop":
        raise RuntimeError("模型输出被截断（finish_reason != stop）")
    content = str(data["choices"][0]["message"]["content"])
    try:
        payload: dict[str, Any] = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"模型输出不是合法 JSON: {exc}") from exc
    if not isinstance(payload.get("items"), list):
        raise RuntimeError("模型输出缺少 items 数组")
    return payload


# ─────────────────────── 载荷装配 + 确定性复判 ───────────────────────


def _text(value: Any) -> str | None:
    """非空字符串规整；其余（None/数字/空串）→ None。"""
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _num(value: Any) -> float | None:
    """模型数值字段容错转换（bool 排除，字符串数字接受）。"""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _suggest_codes(parse: CoaDocxParse) -> None:
    """从报告编号拆建议：COA-HAF-3205-006 → 产品码 HAF / 模板码 HAF-3205-006。"""
    if not parse.report_no:
        return
    segs = re.split(r"[-_/]", parse.report_no)
    # 排除报告类型前缀（COA）——它是编号格式的一部分，不是产品码
    alpha = [s for s in segs if s.isalpha() and s.upper() != "COA"]
    if alpha:
        parse.suggested_product_code = alpha[0].upper()
    # 模板码 = 去 COA 前缀后的整段（产品码-编号码-版本码）；无前缀时整段即模板码
    body = segs[1:] if segs[0].upper() == "COA" else segs
    if body:
        parse.suggested_standard_code = "-".join(body)


_DATE_HINT_RE = re.compile(r"日期|date", re.I)


def _field_key(label_en: str | None, label_cn: str) -> str:
    """字段键（产品内唯一，阶段二渲染 schema 的锚点）：英文标签 snake_case
    优先（Retest Date → retest_date），无英文或归一为空用中文原文。"""
    if label_en:
        key = re.sub(r"[^0-9a-z]+", "_", normalize(label_en).lower()).strip("_")
        if key:
            return key
    return label_cn.strip()


def _field_type(label_cn: str, label_en: str | None) -> str:
    """标签含「日期/date」判定为 date（阶段二解析路由），其余 text。"""
    if _DATE_HINT_RE.search(f"{label_cn}{label_en or ''}"):
        return "date"
    return "text"


def _build_batch_fields(payload: dict[str, Any]) -> list[CoaParsedField]:
    """载荷的 batch_info_fields → 域模型（key/type 系统生成不靠模型）。

    值版载荷带 value（报告导入用），结构版不带值。
    """
    fields: list[CoaParsedField] = []
    for raw in payload.get("batch_info_fields") or []:
        if not isinstance(raw, dict):
            continue
        label_cn = _text(raw.get("label_cn"))
        label_en = _text(raw.get("label_en"))
        if not label_cn and not label_en:
            continue  # 空标签行丢弃
        if not label_cn:  # 只有英文标签：中文位回退英文（label_cn 非空约束）
            label_cn = label_en or ""
        fields.append(
            CoaParsedField(
                label_cn=label_cn,
                label_en=label_en,
                key=_field_key(label_en, label_cn),
                field_type=_field_type(label_cn, label_en),
                value=_text(raw.get("value")),
            )
        )
    return fields


def _build_parse(payload: dict[str, Any]) -> CoaDocxParse:
    """AI 载荷 → CoaDocxParse；数值/日期逐字段确定性复判覆盖。"""
    parse = CoaDocxParse()
    info = payload.get("batch_info")
    if isinstance(info, dict):
        parse.batch_info = {
            k: v for k, v in info.items() if isinstance(v, str) and v.strip()
        }
    parse.serial_no = _text(payload.get("serial_no"))
    parse.report_no = _text(payload.get("report_no"))
    parse.conclusion = _text(payload.get("conclusion"))

    for raw in payload.get("items") or []:
        if not isinstance(raw, dict):
            continue
        name_cn = _text(raw.get("name_cn"))
        if not name_cn:  # 无名行（残留分组标签等）丢弃
            continue
        spec_text = _text(raw.get("spec_text"))
        result = _text(raw.get("result"))
        # 标准限：确定性解析优先；解析不动（无数值限的描述）时保留模型结果
        dmin, dmax = parse_spec(spec_text)
        if dmin is None and dmax is None:
            dmin, dmax = _num(raw.get("spec_min")), _num(raw.get("spec_max"))
        # 结果数值：确定性优先；结果含比较符时模型值一律作废（＜1 ≠ 1）
        value_num = parse_number(result)
        if value_num is None and (
            result is None or not _CMP_RE.search(normalize(result))
        ):
            value_num = _num(raw.get("value_num"))
        value_type = (
            "number"
            if dmin is not None or dmax is not None or value_num is not None
            else "text"
        )
        # 单位：从标准/结果原文剥取优先；剥不出时仅数值型项目采信模型
        unit = parse_unit(spec_text) or parse_unit(result)
        if unit is None and value_type == "number":
            unit = _text(raw.get("unit"))
        parse.items.append(
            CoaParsedItem(
                name_cn=name_cn,
                name_en=_text(raw.get("name_en")),
                unit=unit,
                spec_text=spec_text,
                spec_en=_text(raw.get("spec_text_en")),
                spec_min=dmin,
                spec_max=dmax,
                result=result,
                result_en=_text(raw.get("result_en")),
                value_num=value_num,
                value_type=value_type,
            )
        )

    cn, en = split_bilingual(parse.batch_info.get("product"))
    parse.product_cn, parse.product_en = cn or None, en
    parse.mfg_date = parse_date_text(parse.batch_info.get("mfg_date"))
    parse.exp_date = parse_date_text(parse.batch_info.get("exp_date"))
    parse.batch_fields = _build_batch_fields(payload)
    _suggest_codes(parse)
    return parse


# ─────────────────────── report_no 确定性兜底 ───────────────────────

# No. 标签引导的编号串（No / No. / No: / No.: / No：…）；批号引导词排除。
# re.I：大写的 BATCH NO. / LOT NO. 同样要排除；\b 防 "piano" 里的 no 误命中
_NO_RE = re.compile(
    r"\b(?<!batch\s)(?<!lot\s)No[.．]?[:：]?\s*([A-Za-z0-9][A-Za-z0-9_/\-.]*)",
    re.I,
)


def _fallback_report_no(data: bytes) -> str | None:
    """AI 漏提 report_no 时的确定性兜底：段落+表格全文找 No. 引导的编号串。

    「No. 标签 + 编号串」写法跨模板高度一致，值得一行正则兜底（版式无关的
    例外锚点）；Batch/Lot No. 是批号（大小写都排除），过短命中（Page No. 1）
    也丢弃。解析失败不影响主流程。
    """
    try:
        doc = Document(BytesIO(data))
    except Exception:  # noqa: BLE001 — 兜底尽力而为，失败保持 None 走原口径
        return None
    texts = [p.text for p in doc.paragraphs]
    for table in doc.tables:  # 段落在前：报告编号通常在标题区而非表格
        for row in table.rows:
            for cell in row.cells:
                texts.append(cell.text)
    for text in texts:
        for m in _NO_RE.finditer(text):
            code = m.group(1).rstrip(".")
            if len(code) >= 4:  # 真实编号至少 4 位；滤掉 Page No. 1 之类
                return code
    return None


# ─────────────────────── 对外入口 ───────────────────────


async def parse_docx_ai(
    data: bytes, filename: str = "coa.docx", *, mode: str = "values"
) -> CoaDocxParse:
    """COA docx 字节流 → 结构化草稿（OCR 一次 → 提取按配置重试 → 确定性复判）。

    mode="structure"：模板导入——提字段标签清单+品名+编号+项目定义（无值）；
    mode="values"：报告导入——提批次值+检测结果（现行口径）。
    """
    if mode not in ("structure", "values"):
        raise ValueError(f"未知 COA 解析模式: {mode}")
    prompt = _PROMPT_STRUCTURE if mode == "structure" else _PROMPT_VALUES
    _require_ai()
    settings = get_settings()
    last_error: Exception | None = None
    async with httpx.AsyncClient(
        base_url=settings.QA_AI_BASE_URL.rstrip("/"),
        headers={"Authorization": f"Bearer {settings.QA_AI_API_KEY}"},
    ) as client:
        # OCR 只做一次（重跑同一份长文档没有意义）；失败即 502，不占重试额度
        try:
            document_text = await _ocr_recognize(client, filename, data)
        except Exception as exc:  # noqa: BLE001 — 边界统一转 502
            logger.warning("COA 文档识别失败: %s", exc)
            raise AppException(
                status_code=502, message=f"COA 文档识别失败，请稍后重试（{exc}）"
            ) from exc
        try:
            # 总时限兜底：模型侧一直超时时不再按次数叠满 3×300s
            async with asyncio.timeout(_EXTRACT_TIMEOUT * 2):
                for _ in range(max(1, int(settings.QA_AI_MAX_RETRIES) + 1)):
                    try:
                        payload = await _chat_extract(client, document_text, prompt)
                        parse = _build_parse(payload)
                        if not parse.report_no:
                            # AI 漏提时确定性兜底；拿到编号后重跑建议链
                            parse.report_no = _fallback_report_no(data)
                            if parse.report_no:
                                _suggest_codes(parse)
                        return parse
                    except Exception as exc:  # noqa: BLE001 — 逐次记日志再重试
                        last_error = exc
                        logger.warning("COA AI 提取尝试失败: %s", exc)
        except TimeoutError as exc:
            raise AppException(
                status_code=502, message="COA AI 解析超时，请稍后重试"
            ) from exc
    raise AppException(
        status_code=502, message=f"COA AI 解析失败，请稍后重试（{last_error}）"
    )
