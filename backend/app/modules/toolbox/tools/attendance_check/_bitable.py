"""打卡核对工具：结果扁平化、多维表写入与旧记录清除。

扁平化与写入逻辑原样迁移自 attendance-checking 项目 scripts/write_to_bitable.py；
delete_all_records 为新增：写入前清空结果表全部旧记录（lark batch_delete）。
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from lark_oapi.api.bitable.v1 import (
    AppTableRecord,
    BatchCreateAppTableRecordRequest,
    BatchCreateAppTableRecordRequestBody,
    BatchDeleteAppTableRecordRequest,
    BatchDeleteAppTableRecordRequestBody,
    ListAppTableRecordRequest,
)

# 中国时区
CHINA_TZ = timezone(timedelta(hours=8))

BATCH_SIZE = 500


def date_to_timestamp_ms(date_str: str) -> int:
    """'2026-05-03' -> Unix timestamp in ms (midnight China time)"""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=CHINA_TZ)
    return int(dt.timestamp() * 1000)


def flatten_check_result(check_result: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将嵌套的 check_result 扁平化为多维表记录字段列表"""
    records = []
    for employee in check_result:
        name = employee["员工姓名"]
        emp_id = employee["工号"]
        for anomaly in employee["异常"]:
            date_str = anomaly["日期"]
            month = int(date_str.split("-")[1])
            raw_fields = {
                "姓名": name,
                "工号": emp_id,
                "异常日期": date_to_timestamp_ms(date_str),
                "异常类型": anomaly["异常类型"],
                "缺卡类型": anomaly.get("缺卡") or [],
                "迟到分钟": anomaly.get("迟到"),
                "早退分钟": anomaly.get("早退"),
                "应上班时间": anomaly.get("应上班时间"),
                "应下班时间": anomaly.get("应下班时间"),
                "月份": month,
            }
            records.append({k: v for k, v in raw_fields.items() if v is not None})
    return records


def _list_record_ids(client: Any, app_token: str, table_id: str) -> list[str]:
    """分页获取多维表全部 record_id"""
    ids: list[str] = []
    page_token = ""
    while True:
        builder = (
            ListAppTableRecordRequest.builder()
            .app_token(app_token)
            .table_id(table_id)
            .page_size(500)
        )
        if page_token:
            builder = builder.page_token(page_token)
        resp = client.bitable.v1.app_table_record.list(builder.build())
        if not resp.success():
            raise RuntimeError(f"获取多维表记录失败: code={resp.code}, msg={resp.msg}")
        if resp.data is None or resp.data.items is None:
            break
        ids.extend(item.record_id for item in resp.data.items)
        if not resp.data.has_more:
            break
        page_token = resp.data.page_token
    return ids


def delete_all_records(client: Any, app_token: str, table_id: str) -> int:
    """删除多维表全部旧记录（写入新核对结果前调用），返回删除数量"""
    record_ids = _list_record_ids(client, app_token, table_id)
    deleted = 0
    for i in range(0, len(record_ids), BATCH_SIZE):
        batch = record_ids[i : i + BATCH_SIZE]
        request = (
            BatchDeleteAppTableRecordRequest.builder()
            .app_token(app_token)
            .table_id(table_id)
            .request_body(
                BatchDeleteAppTableRecordRequestBody.builder().records(batch).build()
            )
            .build()
        )
        resp = client.bitable.v1.app_table_record.batch_delete(request)
        if not resp.success():
            raise RuntimeError(
                f"删除多维表旧记录失败: code={resp.code}, msg={resp.msg}"
            )
        deleted += len(batch)
    return deleted


def write_records_to_bitable(
    client: Any, app_token: str, table_id: str, field_records: list[dict[str, Any]]
) -> int:
    """批量写入记录到多维表，返回写入数量"""
    total = 0
    for i in range(0, len(field_records), BATCH_SIZE):
        batch = field_records[i : i + BATCH_SIZE]
        records = [AppTableRecord.builder().fields(f).build() for f in batch]
        request = (
            BatchCreateAppTableRecordRequest.builder()
            .app_token(app_token)
            .table_id(table_id)
            .request_body(
                BatchCreateAppTableRecordRequestBody.builder()
                .records(records)
                .build()
            )
            .build()
        )
        resp = client.bitable.v1.app_table_record.batch_create(request)
        if not resp.success():
            raise RuntimeError(
                f"写入多维表失败: code={resp.code}, msg={resp.msg}, log_id={resp.get_log_id()}"
            )
        total += len(batch)
        print(f"  已写入 {total}/{len(field_records)} 条记录")
    return total
