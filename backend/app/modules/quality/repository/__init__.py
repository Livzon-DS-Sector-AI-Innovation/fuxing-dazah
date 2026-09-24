"""Quality 数据访问包（repository.py 1033 行拆分）。对外 import 路径不变。"""

from app.modules.quality.repository._inspection import (  # noqa: F401
    create_impurities,
    create_inspection_record,
    delete_inspection_record,
    get_impurities_by_record,
    get_inspection_by_batch,
    get_inspection_record,
    list_inspection_records,
)
from app.modules.quality.repository._lc_templates import (  # noqa: F401
    get_lc_template_by_table_no,
    list_lc_template_configs,
)
from app.modules.quality.repository._reports import (  # noqa: F401
    count_report_records_since,
    create_report_record,
    get_latest_report_record_by_task,
    get_report_record,
    is_serial_unique_violation,
    list_report_records,
    list_report_records_between,
    list_report_records_by_date,
)
from app.modules.quality.repository._standards import (  # noqa: F401
    create_standard_document,
    create_standard_item,
    delete_coa_binding,
    delete_standard_document,
    delete_standard_item,
    get_coa_binding_by_template,
    get_standard_document,
    get_standard_document_by_file_no,
    get_standard_item_by_sop,
    list_coa_bindings,
    list_coa_bindings_by_docs,
    list_standard_documents,
    list_standard_documents_by_product,
    list_standard_items,
    update_standard_document,
    update_standard_item,
    upsert_coa_binding,
)
from app.modules.quality.repository._summary import (  # noqa: F401
    get_product_names,
    get_summary_by_product,
)
from app.modules.quality.repository._tasks import (  # noqa: F401
    create_task_attachment,
    create_task_review,
    create_test_results,
    create_test_task,
    delete_task_attachment,
    delete_test_result,
    delete_test_task,
    get_standard_item_doc_map,
    get_task_attachment,
    get_test_task,
    get_test_task_by_batch,
    get_test_task_by_batch_number,
    list_task_attachments,
    list_task_reviews,
    list_task_standard_document_ids,
    list_test_results,
    list_test_results_for_tasks,
    list_test_tasks,
    list_test_tasks_by_batch_fuzzy,
    list_test_tasks_by_report_date,
    soft_delete_task_reviews,
    update_test_results_fill,
    update_test_task,
    update_test_task_report_date,
)

__all__ = ['create_inspection_record', 'get_inspection_record', 'get_inspection_by_batch', 'list_inspection_records', 'delete_inspection_record', 'create_impurities', 'get_impurities_by_record', 'is_serial_unique_violation', 'create_report_record', 'list_report_records_between', 'count_report_records_since', 'list_report_records_by_date', 'get_latest_report_record_by_task', 'get_report_record', 'list_report_records', 'get_product_names', 'get_summary_by_product', 'list_standard_documents', 'get_standard_document_by_file_no', 'get_standard_document', 'create_standard_document', 'update_standard_document', 'delete_standard_document', 'list_standard_items', 'create_standard_item', 'update_standard_item', 'delete_standard_item', 'get_standard_item_by_sop', 'list_standard_documents_by_product', 'list_coa_bindings', 'get_coa_binding_by_template', 'upsert_coa_binding', 'delete_coa_binding', 'list_coa_bindings_by_docs', 'get_lc_template_by_table_no', 'list_lc_template_configs', 'create_test_task', 'get_test_task', 'get_test_task_by_batch_number', 'list_test_tasks_by_batch_fuzzy', 'list_test_tasks_by_report_date', 'get_test_task_by_batch', 'list_test_tasks', 'update_test_task', 'update_test_task_report_date', 'delete_test_task', 'create_test_results', 'list_test_results', 'list_test_results_for_tasks', 'list_task_standard_document_ids', 'create_task_attachment', 'list_task_attachments', 'get_task_attachment', 'delete_task_attachment', 'create_task_review', 'list_task_reviews', 'soft_delete_task_reviews', 'get_standard_item_doc_map', 'update_test_results_fill', 'delete_test_result']
