"""翻译后校验与报告生成。

环境约束：交付机无 Word，全部校验必须程序化——
1. 结构校验：输出文件能被 python-docx 重新打开；段落数符合模式预期
2. 完整性：每个应翻段落都有译文且已回写
3. 占位符/数字：异常在回写前已拦截，此处汇总
4. 术语一致性：术语表命中情况
报告按"待人工复核清单"输出，人工只看例外，不通读全文。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Flag:
    category: str  # 分类（用于汇总计数）
    detail: str    # 具体描述（含段落定位与摘要）


@dataclass
class VerifyContext:
    input_path: str
    output_path: str
    mode: str
    direction: str
    doc_type: str
    mock: bool = False
    source_kind: str = "docx"       # docx=原格式回写 / pdf=重排式输出
    profile: str = ""               # （PDF）领域档案全文，单独成节写入报告
    total_paragraphs_before: int = 0
    inserted_copies: int = 0
    stats: dict = field(default_factory=dict)   # extract/翻译阶段统计
    flags: list[Flag] = field(default_factory=list)

    def add(self, category: str, detail: str) -> None:
        self.flags.append(Flag(category, detail))


HARD_CATEGORIES = {"无译文", "占位符异常", "翻译失败", "结构校验失败"}


def check_structure(ctx: VerifyContext, output_doc) -> bool:
    """重新解析输出文件并核对段落数。"""
    from docx.oxml.ns import qn

    try:
        after = len(list(output_doc.element.body.iter(qn("w:p"))))
    except Exception as e:  # noqa: BLE001
        ctx.add("结构校验失败", f"输出文件无法重新解析: {e}")
        return False
    if ctx.mode == "bilingual":
        expected = ctx.total_paragraphs_before + ctx.inserted_copies
    else:
        expected = ctx.total_paragraphs_before
    if after != expected:
        ctx.add("结构校验失败", f"段落数不符：预期 {expected}，实际 {after}")
        return False
    return True


def write_report(ctx: VerifyContext, path: str) -> None:
    by_cat: dict[str, list[Flag]] = {}
    for f in ctx.flags:
        by_cat.setdefault(f.category, []).append(f)

    hard = [c for c in by_cat if c in HARD_CATEGORIES]
    status = "❌ 存在必须处理的问题" if hard else ("⚠️ 仅有提示项" if by_cat else "✅ 全部通过")

    if ctx.source_kind == "pdf":
        mode_text = "中英对照（段后对照，重排式）" if ctx.mode == "bilingual" else "仅译文（重排式）"
    else:
        mode_text = "中英对照（一行中文一行英文）" if ctx.mode == "bilingual" else "整段替换"

    lines = [
        "# 翻译校验报告",
        "",
        f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
        f"- 输入文件：{ctx.input_path}",
        f"- 输出文件：{ctx.output_path}",
        f"- 模式：{mode_text}",
        f"- 方向：{ctx.direction}　|　文档类型：{ctx.doc_type}"
        + ("　|　⚠️ MOCK 模式（译文为原文回显，仅验证流程）" if ctx.mock else ""),
        "",
        "## 总体结论",
        "",
        f"**{status}**",
        "",
        "## 统计",
        "",
    ]
    for k, v in ctx.stats.items():
        lines.append(f"- {k}：{v}")

    if ctx.profile:
        lines += ["", "## 领域档案（翻译前自动分析，供人工确认）", "", ctx.profile]

    if not by_cat:
        lines += ["", "## 待人工复核清单", "", "（无）"]
    else:
        lines += ["", "## 待人工复核清单", ""]
        for cat in sorted(by_cat):
            flags = by_cat[cat]
            mark = "🔴" if cat in HARD_CATEGORIES else "🟡"
            lines.append(f"### {mark} {cat}（{len(flags)} 处）")
            lines.append("")
            for f in flags:
                lines.append(f"- {f.detail}")
            lines.append("")

    if ctx.source_kind == "pdf":
        lines += [
            "## 说明",
            "",
            "- 🟡 提示项：格式已被安全处理，建议抽查。",
            "- 🔴 必须处理项：该单元未按预期翻译/回写，请单独处理。",
            "- PDF 为重排式输出：标题层级/段落/表格已重建，原版式（分栏、行内粗斜体、页眉页脚）不保留。",
            "- 图片不翻译，按原页面位置居中嵌入（区域渲染 200 DPI）。",
            "- 草案行号（征询意见定位用）已剥离；目录页已跳过（重排版中页码引用无意义）。",
        ]
    else:
        lines += [
            "## 说明",
            "",
            "- 🟡 提示项：格式已被安全处理（如段内混合格式拉平、域静态化），建议抽查。",
            "- 🔴 必须处理项：该段落未按预期翻译/回写，请单独处理该段落。",
            "- 输出文件首次用 Word 打开时，请在提示『是否更新域』时选择**是**，以刷新目录与页码。",
        ]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
