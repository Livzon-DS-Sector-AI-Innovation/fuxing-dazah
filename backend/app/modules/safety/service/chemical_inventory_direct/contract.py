"""风险列回写契约（chemical_inventory-direct Ticket 02）。

本域与 cert 相反：回写真实存在且保留（§4.3）。写面**只允许**总表的两个风险列，
写请求 fields 键集合必须等于 ``WRITEBACK_FIELD_NAMES``（ticket 05/08 探针断言口径）。

探针（2026-09-22）实证生产表两列已在且选项与契约一致；ensure 脚本只对新环境兜底。
"""

from __future__ import annotations

# 回写目标列（Bitable 中文字段名）
RISK_FLAG_FIELD = "风险标记"
RISK_NOTE_FIELD = "风险说明"

# 写请求 fields 键集合白名单（sync_record_flags_to_bitable 断言/探针共用）
WRITEBACK_FIELD_NAMES: frozenset[str] = frozenset({RISK_FLAG_FIELD, RISK_NOTE_FIELD})

# 列选项契约（select / multi-select，探针实测生产表选项全集）
RISK_FLAG_OPTIONS: tuple[str, ...] = ("正常", "预警")
RISK_NOTE_OPTIONS: tuple[str, ...] = (
    "正常", "超量", "临限", "高占比", "未分类", "单位异常", "专库违规",
)

# 总表字段契约（registry INVENTORY_BITABLE_TO_MODEL 的键集合，供核账脚本核对）
EXPECTED_BITABLE_FIELDS: tuple[str, ...] = (
    "部门", "存放部位", "物料名称", "包装规格", "库存数量", "单位",
    "现场物料总量(T)", "库存上限", "上限单位", "危险性", "品类",
    "最后更新时间", "备注", RISK_FLAG_FIELD, RISK_NOTE_FIELD,
)
