"""质量模块文件存储：MinIO 持久化 + 本地工作副本（MinIO 未启用时纯本地）。

对象键约定（bucket={prefix}-quality）：
- templates/{相对路径}   报告模板 docx（MinIO 为持久源，本地为工作副本）
- reports/{文件名}       生成的 COA 输出（本地仍落盘，MinIO 存耐久副本）

本地工作目录沿用 报告模板/（模板与 _generated 输出），开发环境无 MinIO 配置时
自动退化为纯本地磁盘，行为与改造前一致。
"""

import logging
from pathlib import Path

from app.core import storage as s3

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent  # backend/
REPORT_TEMPLATE_DIR = BASE_DIR / "报告模板"

TEMPLATE_PREFIX = "templates/"
REPORT_PREFIX = "reports/"

_synced: bool = False


def _rel(path: Path) -> str:
    """本地模板绝对路径 → 相对 REPORT_TEMPLATE_DIR 的键。"""
    return path.relative_to(REPORT_TEMPLATE_DIR).as_posix()


def upload_template(local_path: Path) -> None:
    """模板写入本地后同步到 MinIO（未启用则跳过，失败仅告警不阻断）。"""
    if not s3.is_enabled():
        return
    try:
        s3.upload_object(
            "quality",
            TEMPLATE_PREFIX + _rel(local_path),
            local_path.read_bytes(),
            local_path.stat().st_size,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    except Exception:
        logger.exception("模板同步 MinIO 失败: %s", local_path)


def delete_template_object(rel_path: str) -> None:
    """删除模板对应的 MinIO 对象（未启用则跳过）。"""
    if not s3.is_enabled():
        return
    try:
        s3.delete_object("quality", TEMPLATE_PREFIX + rel_path)
    except Exception:
        logger.exception("模板对象删除失败: %s", rel_path)


def upload_report(local_path: Path) -> None:
    """生成 COA 后同步耐久副本到 MinIO（未启用则跳过）。"""
    if not s3.is_enabled():
        return
    try:
        s3.upload_object(
            "quality",
            REPORT_PREFIX + local_path.name,
            local_path.read_bytes(),
            local_path.stat().st_size,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    except Exception:
        logger.exception("报告同步 MinIO 失败: %s", local_path)


def read_report_from_minio(filename: str) -> bytes | None:
    """从 MinIO 读生成报告；不存在或未启用返回 None。"""
    if not s3.is_enabled():
        return None
    result = s3.get_object("quality", REPORT_PREFIX + filename)
    return result[0] if result else None


def ensure_template_local(rel_path: str) -> Path:
    """确保模板本地可用：本地缺失且 MinIO 启用时从对象下载。

    返回本地绝对路径（MinIO 也未存时返回不存在路径，由调用方报 404）。
    """
    local = REPORT_TEMPLATE_DIR / rel_path
    if local.is_file() or not s3.is_enabled():
        return local
    result = s3.get_object("quality", TEMPLATE_PREFIX + rel_path)
    if result:
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(result[0])
    return local


PRODUCTS_KEY = "config/products.json"


def upload_products(data: bytes) -> None:
    """产品代码映射配置同步到 MinIO（未启用则跳过）。"""
    if not s3.is_enabled():
        return
    try:
        s3.upload_object("quality", PRODUCTS_KEY, data, len(data), content_type="application/json")
    except Exception:
        logger.exception("products.json 同步 MinIO 失败")


def read_products_from_minio() -> bytes | None:
    """从 MinIO 读产品代码映射配置；不存在或未启用返回 None。"""
    if not s3.is_enabled():
        return None
    result = s3.get_object("quality", PRODUCTS_KEY)
    return result[0] if result else None


def sync_templates_from_minio() -> None:
    """首次访问时把 MinIO 模板对象全量下载到本地工作副本（幂等，仅执行一次）。"""
    global _synced
    if _synced or not s3.is_enabled():
        return
    _synced = True
    try:
        for key in s3.list_objects("quality", TEMPLATE_PREFIX):
            rel = key[len(TEMPLATE_PREFIX):]
            if not rel:
                continue
            local = REPORT_TEMPLATE_DIR / rel
            if local.is_file():
                continue
            result = s3.get_object("quality", key)
            if result:
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(result[0])
                logger.info("模板已从 MinIO 同步到本地: %s", rel)
    except Exception:
        logger.exception("模板 MinIO 同步失败（降级本地工作副本）")
