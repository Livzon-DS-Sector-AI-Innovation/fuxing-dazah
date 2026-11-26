"""模板文件查找工具 — 所有文档生成器共用。"""

from pathlib import Path


def find_hr_template(filename: str) -> Path:
    """在 assets/hr/ 目录下查找模板文件。

    搜索顺序：当前目录 → 上级目录 → 项目根目录。
    """
    candidates = [
        Path(__file__).resolve().parent.parent.parent.parent / "assets" / "hr" / filename,
        Path(f"assets/hr/{filename}"),
        Path(f"../assets/hr/{filename}"),
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(f"模板文件未找到: {filename}")


def find_hr_template_bytes(template_key: str) -> bytes:
    """按模板注册键读取仓库默认模板字节（无 DB 自定义版时生成器的回退来源）。"""
    from app.modules.hr.training_template_registry import TEMPLATES_BY_KEY

    tdef = TEMPLATES_BY_KEY.get(template_key)
    if tdef is None:
        raise FileNotFoundError(f"未知模板注册键: {template_key}")
    return find_hr_template(tdef.default_file).read_bytes()


def find_font(filename: str) -> Path:
    """在 assets/fonts/ 目录下查找字体文件（与 find_hr_template 同模式）。"""
    candidates = [
        Path(__file__).resolve().parent.parent.parent.parent / "assets" / "fonts" / filename,
        Path(f"assets/fonts/{filename}"),
        Path(f"../assets/fonts/{filename}"),
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(f"字体文件未找到: {filename}，请从 Google Fonts 下载 Noto Sans SC 放到 assets/fonts/ 目录")
