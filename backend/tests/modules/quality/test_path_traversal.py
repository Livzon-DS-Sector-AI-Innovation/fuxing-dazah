"""路径穿越防护回归测试（P0：模板下载/删除/上传/附件 key 曾可 .. 读任意文件）。"""

from app.modules.quality import storage as quality_storage
from app.modules.quality.storage import REPORT_TEMPLATE_DIR


def test_safe_join_blocks_traversal():
    base = REPORT_TEMPLATE_DIR
    # 正常相对路径通过
    ok = quality_storage.safe_join(base, "3205.docx")
    assert ok is not None and ok.is_relative_to(base.resolve())
    # 穿越与绝对路径全部拦截（%2F 形式的编码斜杠在 URL 层已解码为 /，此处不测）
    for evil in ["..", "../.env", "a/../../.env", "/etc/passwd", "/绝对/路径.docx"]:
        assert quality_storage.safe_join(base, evil) is None, f"未拦截: {evil!r}"


def test_ensure_template_local_rejects_traversal():
    """穿越路径返回不存在的路径（is_file() False → 调用方 404），绝不落到模板目录之外。"""
    for evil in ["../.env", "../../.env"]:
        p = quality_storage.ensure_template_local(evil)
        assert not p.is_file(), f"穿越路径不应命中文件: {evil!r}"
        assert p.is_relative_to(REPORT_TEMPLATE_DIR.resolve()), f"返回路径越界: {p}"


async def test_template_download_requires_auth(client):
    """模板下载必须鉴权（曾无权限即可读任意文件）。"""
    res = await client.get("/api/v1/quality/templates/3205.docx/download")
    assert res.status_code == 401


async def test_template_download_rejects_traversal_after_auth_missing(client):
    """未登录时穿越请求同样被 401 拦截（不会走到文件读取）。"""
    res = await client.get("/api/v1/quality/templates/..%2F.env/download")
    assert res.status_code == 401


async def test_report_download_requires_auth(client):
    """报告单下载必须鉴权。"""
    res = await client.get("/api/v1/quality/report/records/00000000-0000-0000-0000-000000000000/download")
    assert res.status_code == 401
