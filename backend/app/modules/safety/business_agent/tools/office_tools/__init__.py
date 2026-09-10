"""办公工具（包）。

从原单文件 office_tools.py 拆分而来；__init__ 仅 re-export 全部对外 office_* 函数，
保证 registry / tests / bot_handler 的既有 import 路径稳定。
"""

from app.modules.safety.business_agent.tools.office_tools.office_read_tools import (
    office_read_base,
    office_read_docx,
    office_read_drive_file,
    office_read_sheet,
    office_search_files,
)
from app.modules.safety.business_agent.tools.office_tools.office_scenarios import (
    build_report_docx_blocks,
)
from app.modules.safety.business_agent.tools.office_tools.office_write_tools import (
    office_create_base,
    office_create_docx,
    office_create_sheet,
    office_create_slides,
    office_generate_docx_pdf,
    office_set_permission,
    office_upload_file,
    office_write_sheet,
    rollback_office_file,
)

__all__ = [
    "office_search_files",
    "office_read_docx",
    "office_read_sheet",
    "office_read_base",
    "office_read_drive_file",
    "office_create_docx",
    "office_create_sheet",
    "office_write_sheet",
    "office_create_base",
    "office_create_slides",
    "office_generate_docx_pdf",
    "office_upload_file",
    "office_set_permission",
    "rollback_office_file",
    "build_report_docx_blocks",
]
