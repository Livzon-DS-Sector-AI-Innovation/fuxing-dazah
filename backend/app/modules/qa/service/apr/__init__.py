"""QA 年度产品回顾（PQR）业务编排：模板配置 / 批次录入 / 趋势 / 汇总 / 年度锁定。

按域拆成子模块（common/template/entry/analysis/export/excel_import/lock），
对外整包 re-export——api 层仍以 ``service.apr.X`` 方式调用，导入面由
test_package_surface 兜底。

领域口径（全模块一致）：
- 统计量（均值/极值/±3σ）一律本层查询时计算；数值列允许录入文字结果
  （未检出等），原始记录保留文字，统计口径由列定义 nd_policy 决定。
- 值保存为全量替换（硬删+插入）；Excel 导入另有 merge（非空覆盖）模式。
- 锁定口径：产品×年度 locked 后拦截批次与值的全部写操作；列定义的限度
  （spec/oot）在锁定年度已有录入值时同样冻结（防改写历史 OOS/OOT 判定），
  其余模板字段（名称/单位/排序等）不随年度锁定。
"""

from app.modules.qa.service.apr.analysis import (
    MIN_STATS_SAMPLES,
    build_trend_points,
    classify_point,
    compute_column_stats,
    get_cpk_level,
    summary,
    trend,
)
from app.modules.qa.service.apr.entry import (
    batch_values,
    create_batch,
    delete_batch,
    list_batches,
    save_batch_values,
    update_batch,
)
from app.modules.qa.service.apr.excel_import import (
    build_import_template,
    import_section_values,
)
from app.modules.qa.service.apr.export import (
    build_export_workbook,
    build_section_export,
)
from app.modules.qa.service.apr.lock import (
    list_annual_reviews,
    set_annual_review_lock,
)
from app.modules.qa.service.apr.report import (
    build_report_rows,
    build_section_report,
)
from app.modules.qa.service.apr.template import (
    bulk_create_items,
    copy_template,
    create_item,
    create_product,
    create_section,
    delete_item,
    delete_product,
    delete_section,
    list_products,
    list_sections,
    update_item,
    update_product,
    update_section,
)

__all__ = [
    "MIN_STATS_SAMPLES",
    "batch_values",
    "build_export_workbook",
    "build_import_template",
    "build_report_rows",
    "build_section_export",
    "build_section_report",
    "bulk_create_items",
    "build_trend_points",
    "classify_point",
    "compute_column_stats",
    "copy_template",
    "create_batch",
    "create_item",
    "create_product",
    "create_section",
    "delete_batch",
    "delete_item",
    "delete_product",
    "delete_section",
    "get_cpk_level",
    "import_section_values",
    "list_annual_reviews",
    "list_batches",
    "list_products",
    "list_sections",
    "save_batch_values",
    "set_annual_review_lock",
    "summary",
    "trend",
    "update_batch",
    "update_item",
    "update_product",
    "update_section",
]
