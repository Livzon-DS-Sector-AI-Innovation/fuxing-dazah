"""底座字段取值与时间换算（纯函数，只依赖标准库）。

统一口径（把两个旧包的分歧收敛到一处）：

1. **文本**支持三种输入：富文本数组、裸字符串、formula 包装 {"type":1,"value":[...]}。
   旧隐患实现只认前两种，遇到 formula 包装会把整个字典转成 repr 字符串。
2. **空值**在字段级取值上一律返回 None（域包如果需要空字符串，自行 ``or ""``）。
3. **毫秒时间戳**的 0 与负数按缺失处理（返回 None），不产出 1970-01-01。
   旧隐患实现有此保护，特殊作业实现没有，这里统一取更防御的一侧。
4. **多选**同时提供"原样列表"与"拼接文本"两个出口，拼接符由调用方决定
   （隐患用 ", "，特殊作业用 "、"），不把某个域的展示约定写进底座。

本模块不做任何 IO，不 import 任何重依赖，可被任意域安全复用。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

_BLANK_PERSON: dict[str, str] = {"name": "", "id": "", "email": ""}


#
# 纯值级原语（不涉及字段名）
#


def rich_text(value: Any) -> str:
    """富文本 / 文本字段 -> 纯文本。

    兼容：富文本数组（每项含 text）、裸字符串、formula 包装
    ``{"type": 1, "value": [...]}``、单个富文本节点 ``{"text": ...}``。
    其余类型按字符串处理；空值返回空字符串。
    """
    if value is None:
        return ""
    if isinstance(value, dict):
        if "value" in value:
            return rich_text(value["value"])
        if "text" in value:
            return rich_text(value["text"])
        return ""
    if isinstance(value, (list, tuple)):
        return "".join(rich_text(item) for item in value)
    if isinstance(value, str):
        return value
    return str(value) if value else ""


def _select_item_text(item: Any) -> str:
    """单个选项（str / {"name"} / {"text"} / 其他标量）-> 纯文本。"""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return str(item.get("name") or item.get("text") or "").strip()
    return str(item).strip() if item else ""


def select_values(value: Any) -> list[str]:
    """单选 / 多选字段 -> 选项文本列表（空值返回空列表，不返回 None）。

    兼容 search / GET 两种形态：裸字符串、字符串列表、以及
    ``[{"name": "..."}]`` / ``{"name": "..."}`` 这类结构化选项。
    """
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        items = list(value)
    else:
        items = [value]
    return [text for item in items if (text := _select_item_text(item))]


def _person_from_dict(item: dict[str, Any]) -> dict[str, str]:
    return {
        "name": (item.get("name") or "").strip(),
        "id": (item.get("userId") or item.get("id") or "").strip(),
        "email": (item.get("email") or "").strip(),
    }


def _first_person(items: list[Any]) -> dict[str, str]:
    for item in items:
        if isinstance(item, dict):
            return _person_from_dict(item)
    return dict(_BLANK_PERSON)


def person_info(value: Any) -> dict[str, str]:
    """人员字段 -> {"name", "id", "email"}（缺失字段为空字符串）。

    兼容两种既有格式：
    旧格式 ``[{"id": "ou_xxx", "name": "张三"}]``
    新格式 ``{"users": [{"userId": "...", "name": "张三"}]}``
    """
    if not value:
        return dict(_BLANK_PERSON)
    if isinstance(value, dict):
        users = value.get("users")
        if isinstance(users, list):
            return _first_person(users)
        if "name" in value or "id" in value or "userId" in value:
            return _person_from_dict(value)
        return dict(_BLANK_PERSON)
    if isinstance(value, (list, tuple)):
        return _first_person(list(value))
    return dict(_BLANK_PERSON)


def person_name(value: Any) -> str:
    """人员字段 -> 姓名（无姓名时回退 id）。"""
    info = person_info(value)
    return info["name"] or info["id"]


def ms_to_utc(value: Any) -> datetime | None:
    """Bitable 毫秒时间戳 -> UTC aware datetime。

    0、负数、非数字、无法解析一律返回 None（不产出 1970）。
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        millis: float = value
    elif isinstance(value, str):
        try:
            millis = int(value.strip())
        except ValueError:
            return None
    else:
        return None
    if millis <= 0:
        return None
    try:
        return datetime.fromtimestamp(millis / 1000.0, tz=UTC)
    except (OSError, ValueError, OverflowError):
        return None


def to_utc(value: datetime | None) -> datetime | None:
    """把映射产出的 datetime 归一为 UTC aware（None 原样返回）。

    映射代码常用 ``datetime.fromtimestamp(ms / 1000)`` 生成**进程本地时钟**的
    naive 值：生产容器 TZ=UTC 时它本就是 UTC，而本机（TZ=Asia/Shanghai）会整体
    平移 8 小时。这里按「naive = 本地时钟，取同一瞬时」归一，两种环境结果一致，
    同时保证下游的 aware 窗口比较不会因 naive/aware 混用抛 TypeError。
    """
    if value is None:
        return None
    return value.astimezone(UTC)


def utc_to_ms(value: datetime) -> int:
    """datetime -> 毫秒时间戳（naive 值按进程本地时钟解释）。"""
    return int(value.timestamp() * 1000)


def attachment_list(value: Any) -> list[dict[str, Any]]:
    """附件字段 -> 附件元数据列表（只保留带 file_token 的字典项）。"""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict) and item.get("file_token")]


#
# 字段级便捷取值（空值统一 None 约定）
#


def text(fields: dict[str, Any], name: str) -> str | None:
    """字段名 -> 纯文本；缺失或空返回 None。"""
    return rich_text(fields.get(name)).strip() or None


def select(fields: dict[str, Any], name: str, *, joiner: str = ", ") -> str | None:
    """字段名 -> 选项文本（多选按 ``joiner`` 拼接）；空返回 None。"""
    values = select_values(fields.get(name))
    if not values:
        return None
    return joiner.join(values).strip() or None


def multi(fields: dict[str, Any], name: str) -> list[str]:
    """字段名 -> 选项文本列表（不做拼接，展示约定留给调用方）。"""
    return select_values(fields.get(name))


def person(fields: dict[str, Any], name: str) -> str | None:
    """字段名 -> 姓名（回退 id）；空返回 None。"""
    return person_name(fields.get(name)) or None


def datetime_ms(fields: dict[str, Any], name: str) -> datetime | None:
    """字段名 -> UTC aware datetime；缺失或非法返回 None。"""
    return ms_to_utc(fields.get(name))


def attachments(fields: dict[str, Any], name: str) -> list[dict[str, Any]]:
    """字段名 -> 附件元数据列表；缺失返回空列表。"""
    return attachment_list(fields.get(name))
