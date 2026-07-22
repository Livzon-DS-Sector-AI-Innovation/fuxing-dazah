"""
Excel 标准化输出 — 通用模板填充 + PDF 导出插件。

给定一个 Excel 模板和一份数据，自动填充表格并导出为 PDF，保留模板的全部格式。

**核心能力**
- 📋 **模板自动检测**：``TemplateInspector`` 扫描模板，自动识别样本行、表头、
  列字母行、合并单元格、标题占位符，一键生成 ``TemplateConfig``
- 🎨 **格式保持**：字体 / 填充 / 对齐 / 边框 / 行高 完全克隆自样本行
- 🔴 **风险着色**：按关键字自动为风险等级列着色（红/橙/蓝/绿）
- 📄 **PDF 导出**：内置 LibreOffice 转换引擎，Windows 环境下自动降级 Excel COM
- 🔧 **零依赖部署**：仅需 ``openpyxl``（项目已有），LibreOffice 为推荐选项

**快速开始（零配置）**::

    from app.modules.safety.template_export import quick_export

    # 给模板 + 数据，自动检测结构并导出 PDF
    pdf_path = quick_export(
        template="危险源辨识管控清单模板.xlsx",
        data=hazard_records,      # list[dict]
        output="output.pdf",
    )

**自定义配置**::

    from app.modules.safety.template_export import (
        TemplateConfig, PageSetup, TemplateInspector,
        ExcelTemplateFiller, ExcelToPdfConverter,
    )

    # 方式 1: 自动检测 + 微调
    inspector = TemplateInspector()
    config = inspector.build_config("模板.xlsx", risk_label_column="o")
    config.page_setup = PageSetup(orientation="landscape", paper_size=8)

    # 方式 2: 手动配置
    config = TemplateConfig(
        sample_row=7, header_row_count=6, total_columns=24,
        column_mapping={"a": "field_a", "b": "field_b", ...},
    )

    filler = ExcelTemplateFiller(config)
    xlsx = filler.fill_and_save("模板.xlsx", data, "output.xlsx")
    pdf = ExcelToPdfConverter().convert(xlsx, "output.pdf")

**依赖**
    ================  ======  ==========================================
    依赖              状态    说明
    ================  ======  ==========================================
    ``openpyxl``      ✅      项目已有，Excel 读写
    LibreOffice       ⭐      PDF 导出（推荐，用 ``winget`` 安装）
    Excel 2007+ COM   🔻     Windows 降级方案（质量不如 LibreOffice）
    ================  ======  ==========================================

    LibreOffice 安装::

        winget install TheDocumentFoundation.LibreOffice
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from .config import (
    HAZARD_COLUMN_MAPPING,
    HAZARD_TEMPLATE_CONFIG,
    NUMERIC_COLUMNS,
    RISK_LABEL_COLORS,
    InspectionResult,
    PageSetup,
    TemplateConfig,
    TemplateInspector,
)
from .converter import (
    ExcelToPdfConverter,
    convert_xlsx_to_pdf,
)
from .filler import ExcelTemplateFiller

__all__ = [
    # 配置
    "TemplateConfig",
    "PageSetup",
    "HAZARD_TEMPLATE_CONFIG",
    "HAZARD_COLUMN_MAPPING",
    "NUMERIC_COLUMNS",
    "RISK_LABEL_COLORS",
    # 自动检测
    "TemplateInspector",
    "InspectionResult",
    # 引擎
    "ExcelTemplateFiller",
    "ExcelToPdfConverter",
    # 便捷函数
    "fill_and_export",
    "fill_template",
    "convert_xlsx_to_pdf",
    "quick_export",
    "inspect_template",
]


# ═══════════════════════════════════════════════════════════════════════════════
# 顶层便捷函数
# ═══════════════════════════════════════════════════════════════════════════════

async def fill_and_export(
    data: list[dict],
    template_path: str | Path,
    output_dir: str | Path | None = None,
    *,
    filename_stem: str | None = None,
    config: TemplateConfig | None = None,
    soffice_path: str | Path | None = None,
) -> Path:
    """填充模板 + 导出 PDF（一步完成）。

    Parameters
    ----------
    data:
        数据列表，每条记录是一个 dict，key 必须匹配 *config* 中的 column_mapping。
    template_path:
        Excel 模板文件路径。
    output_dir:
        输出目录，默认为模板所在目录。
    filename_stem:
        输出文件名（不含扩展名）。默认 ``hazard_ledger_<YYYYMMDD>``。
    config:
        模板结构描述。默认使用 ``HAZARD_TEMPLATE_CONFIG``。
    soffice_path:
        LibreOffice soffice.exe 路径，默认自动检测。

    Returns
    -------
    Path — 生成的 PDF 文件路径。
    """
    cfg = config or HAZARD_TEMPLATE_CONFIG
    out_dir = Path(output_dir) if output_dir else Path(template_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = filename_stem or f"hazard_ledger_{date.today().strftime('%Y%m%d')}"

    xlsx_path = out_dir / f"{stem}.xlsx"
    pdf_path = out_dir / f"{stem}.pdf"

    # Step 1 — 填充 Excel
    filler = ExcelTemplateFiller(cfg)
    filler.fill_and_save(template_path, data, xlsx_path)

    # Step 2 — 转 PDF
    ExcelToPdfConverter(soffice_path=soffice_path).convert(xlsx_path, pdf_path)

    return pdf_path


def fill_template(
    data: list[dict],
    template_path: str | Path,
    output_path: str | Path,
    *,
    config: TemplateConfig | None = None,
) -> Path:
    """填充模板并保存为 .xlsx（不转换 PDF）。

    Returns
    -------
    Path — 生成的 .xlsx 文件路径。
    """
    cfg = config or HAZARD_TEMPLATE_CONFIG
    return ExcelTemplateFiller(cfg).fill_and_save(
        template_path, data, output_path
    )


def inspect_template(
    template_path: str | Path,
    *,
    column_mapping: dict[str, str] | None = None,
) -> InspectionResult:
    """自动检测模板结构。

    Returns
    -------
    ``InspectionResult`` 含自动推断的 ``TemplateConfig``、
    合并单元格信息、列字母行位置等。
    """
    return TemplateInspector().inspect(template_path, column_mapping=column_mapping)


def quick_export(
    data: list[dict],
    template: str | Path,
    output: str | Path,
    *,
    column_mapping: dict[str, str] | None = None,
    title_resolver: Callable[[list[dict]], str] | None = None,
    risk_label_column: str = "",
    sequence_column: int = 1,
    page_setup: PageSetup | None = None,
    soffice_path: str | Path | None = None,
    **config_overrides,
) -> Path:
    """零配置快速导出：自动检测模板结构 → 填充数据 → 导出 PDF。

    无需手动创建 ``TemplateConfig``，只需提供模板、数据和输出路径。
    如需更精细的控制，使用 ``TemplateInspector.build_config()`` + ``fill_and_export()``。

    Parameters
    ----------
    data:
        数据列表，key 必须匹配 *column_mapping* 中的字段名。
    template:
        Excel 模板文件路径。
    output:
        输出 PDF 路径（.pdf）或 XLSX 路径（.xlsx）。
    column_mapping:
        ``{列字母: DB字段名}`` 映射。若省略，自动生成空映射（所有列留空）。
    title_resolver:
        标题占位符替换回调。默认按部门聚合。
    risk_label_column:
        需要风险着色的列字母，不需要则留空。
    sequence_column:
        序号列（1=A），设为 0 禁用。
    page_setup:
        页面设置，默认 A4 纵向。
    soffice_path:
        LibreOffice 路径。
    **config_overrides:
        传递给 ``TemplateConfig`` 的额外覆盖参数。

    Returns
    -------
    Path — 输出文件路径（.pdf 或 .xlsx）。

    Example
    -------
    >>> pdf = quick_export(
    ...     data=records,
    ...     template="危险源辨识管控清单模板.xlsx",
    ...     output="台账_20260617.pdf",
    ...     column_mapping={"a": "hazard_id_no", "b": "position", ...},
    ...     risk_label_column="o",
    ...     page_setup=PageSetup(orientation="landscape", paper_size=8),
    ... )
    """
    output_path = Path(output)

    # 自动检测模板
    inspector = TemplateInspector()
    result = inspector.inspect(template, column_mapping=column_mapping)
    config = result.config

    # 覆盖配置
    if title_resolver is not None:
        config.title_resolver = title_resolver
    if risk_label_column:
        config.risk_label_column = risk_label_column
    if sequence_column != 1:
        config.sequence_column = sequence_column
    if page_setup is not None:
        config.page_setup = page_setup

    for key, value in config_overrides.items():
        if hasattr(config, key):
            setattr(config, key, value)

    suffix = output_path.suffix.lower()

    if suffix == ".pdf":
        # 先生成 xlsx 再转 pdf
        xlsx_path = output_path.with_suffix(".xlsx")
        filler = ExcelTemplateFiller(config)
        filler.fill_and_save(template, data, xlsx_path)
        ExcelToPdfConverter(soffice_path=soffice_path).convert(xlsx_path, output_path)
        return output_path

    # 仅 xlsx
    filler = ExcelTemplateFiller(config)
    return filler.fill_and_save(template, data, output_path)

