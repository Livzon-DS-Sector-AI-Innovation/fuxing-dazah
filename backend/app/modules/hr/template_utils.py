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
