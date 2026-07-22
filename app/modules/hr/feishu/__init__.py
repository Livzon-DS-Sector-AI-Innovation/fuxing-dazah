"""HR module Feishu Bitable integration — self-contained within the HR module."""

from app.modules.hr.feishu.bitable import BitableClient, FeishuBitableSync
from app.modules.hr.feishu.client import FeishuClient
from app.modules.hr.feishu.datasource import BitableDataSource
from app.modules.hr.feishu.employee_datasource import (
    EmployeeBitableDataSource,
    EmployeeRecord,
)
from app.modules.hr.feishu.im import FeishuIM

__all__ = [
    "BitableClient",
    "BitableDataSource",
    "EmployeeBitableDataSource",
    "EmployeeRecord",
    "FeishuBitableSync",
    "FeishuClient",
    "FeishuIM",
]
