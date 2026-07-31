"""template_utils 测试：模板文件查找 + 字体文件查找"""

from pathlib import Path

from app.modules.hr.template_utils import find_font, find_hr_template


class TestFindHrTemplate:
    def test_find_existing_template(self):
        """能找到 assets/hr/ 下存在的文件"""
        path = find_hr_template("company_logo.png")
        assert isinstance(path, Path)
        assert path.exists()
        assert path.suffix == ".png"

    def test_find_nonexistent_template(self):
        """找不到文件时抛 FileNotFoundError"""
        try:
            find_hr_template("不存在的文件_xyz123.docx")
            assert False, "应抛出异常"
        except FileNotFoundError as e:
            assert "不存在的文件_xyz123.docx" in str(e)


class TestFindFont:
    def test_find_existing_font(self):
        """能找到 assets/fonts/ 下的字体文件"""
        path = find_font("NotoSansSC.ttf")
        assert isinstance(path, Path)
        assert path.exists()
        assert path.suffix == ".ttf"

    def test_find_nonexistent_font(self):
        """找不到字体时抛 FileNotFoundError 并提示下载"""
        try:
            find_font("不存在的字体_xyz.ttf")
            assert False, "应抛出异常"
        except FileNotFoundError as e:
            msg = str(e)
            assert "字体文件未找到" in msg
            assert "Google Fonts" in msg
