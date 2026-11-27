"""COA 出具登记操作日志的逐格快照：同名项目必须各有各的格名。

值行是硬删重插，日志里的逐格 diff 就是唯一的历史；几个项目中文名相同
（都叫「杂质」）时格名不分开会互相覆盖，改其中一个的那条 diff 会整条消失。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

from app.modules.qa.service.coa.report_log import (
    diff_cells,
    item_log_labels,
    report_cells,
)


def _item(name_cn: str, code: str) -> Any:
    return SimpleNamespace(id=uuid.uuid4(), name_cn=name_cn, code=code)


def _report() -> Any:
    return SimpleNamespace(remark=None)


def _value(item_id: uuid.UUID, text: str) -> dict[str, Any]:
    return {"item_id": item_id, "value_num": None, "value_text": text, "remark": None}


def _same_named_items() -> list[Any]:
    return [
        _item("杂质", "杂质impuritya"),
        _item("杂质", "杂质impurityb"),
        _item("杂质", "杂质impurityc"),
    ]


def test_same_named_items_get_distinct_log_labels() -> None:
    first, second, third = _same_named_items()
    labels = item_log_labels([first, second, third])
    assert len(set(labels.values())) == 3
    assert labels[first.id] == "杂质（杂质impuritya）"
    assert labels[second.id] == "杂质（杂质impurityb）"


def test_change_to_second_same_named_item_still_diffs() -> None:
    first, second, third = _same_named_items()
    labels = item_log_labels([first, second, third])
    old = report_cells(
        _report(),
        batch_info={},
        fields=[],
        values=[_value(first.id, "0.1"), _value(second.id, "0.2"), _value(third.id, "0.3")],
        item_labels=labels,
    )
    new = report_cells(
        _report(),
        batch_info={},
        fields=[],
        values=[_value(first.id, "0.1"), _value(second.id, "0.9"), _value(third.id, "0.3")],
        item_labels=labels,
    )
    old_diff, new_diff = diff_cells(old, new)
    assert old_diff == {labels[second.id]: {"值": "0.2"}}
    assert new_diff == {labels[second.id]: {"值": "0.9"}}
