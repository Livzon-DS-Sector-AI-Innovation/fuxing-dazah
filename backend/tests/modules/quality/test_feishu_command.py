"""飞书指令解析纯逻辑测试（此前仅 _unfilled_groups 有覆盖）。"""


from app.modules.quality.feishu.fill_service import (
    _ARCHIVE_MODE,
    _BATCH_RE,
    _PAIR_RE,
    _extract_command,
)


def _text_event(text: str, chat_id: str = "oc_test", sender: str = "ou_test", chat_type: str = "group") -> dict:
    import json

    return {
        "event": {
            "message": {
                "chat_id": chat_id,
                "chat_type": chat_type,
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
            "sender": {"sender_id": {"open_id": sender}},
        }
    }


# ── _extract_command ──


def test_extract_command_parses_fields() -> None:
    ev = _text_event("批号 HAF2608001B 水分 4.5")
    chat_id, sender, text, chat_type = _extract_command(ev)
    assert chat_id == "oc_test"
    assert sender == "ou_test"
    assert text == "批号 HAF2608001B 水分 4.5"
    assert chat_type == "group"


def test_extract_command_malformed_returns_defaults() -> None:
    assert _extract_command({}) == (None, None, "", "group")
    assert _extract_command({"event": {"message": {}}}) == (None, None, "", "group")


# ── 指令正则 ──


def test_batch_re_matches_variants() -> None:
    assert _BATCH_RE.search("批号 HAF2608001B 水分 4.5").group(1) == "HAF2608001B"
    assert _BATCH_RE.search("批号:HAF2608001B").group(1) == "HAF2608001B"
    assert _BATCH_RE.search("批号： HAF-26-08").group(1) == "HAF-26-08"
    assert _BATCH_RE.search("建任务 批号 HAF2608001B").group(1) == "HAF2608001B"


def test_batch_re_requires_label() -> None:
    # 无「批号」标签的裸批号不误抓（走模糊查询路径）
    assert _BATCH_RE.search("进度 HAF2608001B") is None


def test_pair_re_matches_chinese_names() -> None:
    pairs = _PAIR_RE.findall("水分 4.5 炽灼残渣 0.10 残留溶剂(乙醇) 30")
    assert pairs == [("水分", "4.5"), ("炽灼残渣", "0.10"), ("残留溶剂(乙醇)", "30")]


# ── 归档模式清理 ──


def test_archive_mode_pop_safe() -> None:
    _ARCHIVE_MODE.pop("oc_whatever", None)  # 不存在的 key 不抛异常
    assert "oc_whatever" not in _ARCHIVE_MODE
