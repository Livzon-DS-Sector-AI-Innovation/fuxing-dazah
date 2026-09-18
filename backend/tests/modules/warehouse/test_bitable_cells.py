"""Bitable 单元格规范解析测试（V3.0 分期A 真机验证后抽出）。

真机教训：手写 str(value) 拼接遇富文本分段会把字典 repr 打进卡片。
"""

from __future__ import annotations

from app.modules.warehouse.bitable_cells import (
    cell_list,
    cell_number,
    cell_text,
    unwrap,
)


class TestCellParsing:
    def test_plain_scalar(self) -> None:
        assert cell_text("硫酸") == "硫酸"
        assert cell_text(None) == ""
        assert cell_number(3700) == 3700.0

    def test_rich_text_segments(self) -> None:
        # 富文本分段（真机 material_receipt.物料名称 实测形态）
        value = [{"text": "1-[3-氯-5-(三氟甲基)苯基]-2,2,2-三氟乙酮", "type": "text"}]
        assert cell_text(value) == "1-[3-氯-5-(三氟甲基)苯基]-2,2,2-三氟乙酮"
        assert "{'text'" not in cell_text(value)

    def test_select_array(self) -> None:
        # 单选读取为数组（读写不对称）
        assert cell_text(["放行"]) == "放行"
        assert cell_text(["A", "B"]) == "A、B"

    def test_type_wrapper(self) -> None:
        # formula/lookup 类型包裹
        assert cell_number({"type": 2, "value": [35]}) == 35.0
        assert cell_text({"type": 3, "value": ["合格"]}) == "合格"

    def test_user_field(self) -> None:
        assert cell_text([{"id": "ou_x", "name": "张三"}]) == "张三"

    def test_number_parsing(self) -> None:
        assert cell_number("1,234.5") == 1234.5
        assert cell_number("abc") is None
        assert cell_number([{"text": "42", "type": "text"}]) == 42.0
        assert cell_number(None) is None

    def test_unwrap_and_list(self) -> None:
        assert unwrap([{"text": ["x"]}]) == "x"
        assert unwrap({"link_record_ids": ["r1"]}) is None
        assert cell_list([{"text": "a", "type": "text"}, "b"]) == ["a", "b"]
