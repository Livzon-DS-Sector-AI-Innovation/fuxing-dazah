"""R2 私信文案构建 —— 纯函数单测（T04）。

完成标准「提醒内容」逐条锚定：复审要求、换证要求、完成期限、逾期处理
后果四要素 + 第 N 次（共 3 次）标注（需求原文口径）。
"""

from __future__ import annotations

from app.modules.safety.service.guardian_r2.notify import build_remind_content


def _derived(**kw) -> dict:
    base = dict(
        person_name="张三", department="提炼工程一部",
        cert_category="guardian_a", node_label="第一次复审",
        deadline="2027-01-10", remaining_days=67, remind_seq=1,
    )
    base.update(kw)
    return base


def test_remind_content_four_elements() -> None:
    """四要素齐备：复审要求/换证要求/完成期限/逾期后果。"""
    content = build_remind_content(_derived())
    assert "复审要求" in content
    assert "换证" in content
    assert "完成期限" in content and "2027-01-10" in content
    assert "逾期" in content and "取消监护资格" in content and "停止发放" in content
    assert "监护人津贴" in content


def test_remind_content_nth_label() -> None:
    """第 N 次（共 3 次）标注随 remind_seq 变化。"""
    assert "第 1 次（共 3 次）" in build_remind_content(_derived(remind_seq=1))
    assert "第 3 次（共 3 次）" in build_remind_content(_derived(remind_seq=3))


def test_remind_content_person_and_node() -> None:
    """姓名/证件类型/当前节点/剩余天数齐备。"""
    content = build_remind_content(_derived())
    assert "张三" in content
    assert "A证" in content
    assert "第一次复审" in content
    assert "67" in content


def test_remind_content_renew_node_wording() -> None:
    """换证节点：节点语义切换为换证要求为主。"""
    content = build_remind_content(_derived(node_label="换证", remaining_days=20))
    assert "换证" in content
    assert "20" in content
