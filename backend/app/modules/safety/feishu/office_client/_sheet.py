"""office_client 电子表格（sheet）资源方法。"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.modules.safety.feishu.office_client._base import (
    OfficeResult,
    _range_for_rows,
)


class _SheetOfficeMixin:
    """sheet 读写：读 range / 创建表格 / 写 range。"""

    async def read_sheet(
        self,
        spreadsheet_token: str,
        sheet_range: str,
        *,
        max_rows: int = 500,
        max_cols: int = 50,
    ) -> OfficeResult:
        """读取电子表格指定 range 的值。"""
        try:
            url = (
                f"{self._base_url}/sheets/v2/spreadsheets/"
                f"{spreadsheet_token}/values/{quote(sheet_range, safe='')}"
            )
            resp = await self._get(
                url,
                timeout=30,
                params={
                    "valueRenderOption": "ToString",
                    "dateTimeRenderOption": "FormattedString",
                },
            )
            data = resp.json()

            if data.get("code") != 0:
                return OfficeResult.failure(
                    f"读取电子表格失败：code={data.get('code')} "
                    f"msg={data.get('msg')}"
                )

            rows = (
                (data.get("data") or {}).get("valueRange") or {}
            ).get("values") or []
            total_rows = len(rows)
            total_cols = max((len(row) for row in rows), default=0)

            truncated_rows = total_rows > max_rows
            truncated_cols = total_cols > max_cols
            sliced = [row[:max_cols] for row in rows[:max_rows]]

            return OfficeResult.data(
                sliced,
                truncated=(truncated_rows or truncated_cols),
                meta={
                    "range": (data.get("data") or {}).get("valueRange", {}).get(
                        "range", sheet_range
                    ),
                    "total_rows": total_rows,
                    "total_cols": total_cols,
                    "returned_rows": len(sliced),
                    "returned_cols": max((len(row) for row in sliced), default=0),
                    "truncated_rows": truncated_rows,
                    "truncated_cols": truncated_cols,
                },
            )
        except Exception as exc:
            return self._failure("读取电子表格", exc)

    async def create_sheet(
        self,
        title: str,
        *,
        folder_token: str | None = None,
        rows: list[list[Any]] | None = None,
    ) -> OfficeResult:
        """创建电子表格（sheets/v3/spreadsheets），可选写入初始行。"""
        try:
            body: dict[str, Any] = {"title": title}
            if folder_token:
                body["folder_token"] = folder_token

            resp = await self._post(
                f"{self._base_url}/sheets/v3/spreadsheets",
                json=body,
                timeout=60,
            )
            data = resp.json()

            if data.get("code") != 0:
                return OfficeResult.failure(
                    f"创建电子表格失败：code={data.get('code')} "
                    f"msg={data.get('msg')}"
                )

            spreadsheet = (data.get("data") or {}).get("spreadsheet") or {}
            spreadsheet_token = spreadsheet.get("spreadsheet_token") or ""
            if not spreadsheet_token:
                return OfficeResult.failure("创建电子表格成功但未返回 spreadsheet_token")

            url = spreadsheet.get("url") or self._file_url(
                spreadsheet_token, "sheet"
            )
            result = OfficeResult.link(
                url,
                file_token=spreadsheet_token,
                message=f"已创建电子表格《{title}》",
            )

            if rows:
                sheet_range = _range_for_rows(rows)
                written = await self.write_sheet(
                    spreadsheet_token, sheet_range, rows,
                )
                if written.kind == "error":
                    return OfficeResult(
                        kind="error",
                        error=(
                            f"电子表格已创建（{spreadsheet_token}）但写入数据失败："
                            f"{written.error}"
                        ),
                        url=url,
                        file_token=spreadsheet_token,
                    )
                result.message = (
                    f"已创建电子表格《{title}》并写入 {len(rows)} 行数据"
                )
            return result
        except Exception as exc:
            return self._failure("创建电子表格", exc)

    async def write_sheet(
        self,
        spreadsheet_token: str,
        sheet_range: str,
        values: list[list[Any]],
    ) -> OfficeResult:
        """向既有电子表格写入值（sheets/v2 values API）。"""
        try:
            body: dict[str, Any] = {
                "valueRange": {
                    "range": sheet_range,
                    "values": values,
                },
            }
            resp = await self._put(
                f"{self._base_url}/sheets/v2/spreadsheets/"
                f"{spreadsheet_token}/values",
                json=body,
                timeout=60,
            )
            data = resp.json()

            if data.get("code") != 0:
                return OfficeResult.failure(
                    f"写入电子表格失败：code={data.get('code')} "
                    f"msg={data.get('msg')}"
                )

            return OfficeResult.link(
                self._file_url(spreadsheet_token, "sheet"),
                file_token=spreadsheet_token,
                message=f"已写入电子表格区域 {sheet_range}",
            )
        except Exception as exc:
            return self._failure("写入电子表格", exc)
