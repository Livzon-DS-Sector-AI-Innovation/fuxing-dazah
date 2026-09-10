"""视觉服务共享工具函数。

从各 service / handler / API 文件中提取的重复代码，统一到此模块。
所有函数保持原有逻辑不变，纯代码移动 + import 整理。
"""

from __future__ import annotations

import json
import logging
import os
from io import BytesIO

from app.core.storage import delete_object, get_object
from app.core.storage import is_enabled as minio_enabled
from app.modules.safety.vision.constants import IMAGE_MIME_MAP

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# 文件清理
# ═══════════════════════════════════════════════════════════════════════════


def cleanup_file(file_path: str | None) -> None:
    """删除单个文件（MinIO 或本地磁盘）。

    原实现散落在 5 个 service 文件中（hazard/safety/special_operation/regulation/knowledge），
    代码完全一致。统一后所有调用方改为 `from app.modules.safety.vision.utils import cleanup_file`。
    """
    if not file_path:
        return
    try:
        if minio_enabled():
            try:
                delete_object("safety", file_path)
            except Exception:
                pass
        else:
            abs_path = os.path.abspath(file_path)
            if os.path.exists(abs_path):
                os.remove(abs_path)
    except OSError:
        pass


def cleanup_json_array_files(json_str: str | None) -> None:
    """解析 JSON 数组中的文件路径，逐文件删除。

    原实现散落在 hazard.py 和 safety.py 中，代码完全一致。
    """
    if not json_str:
        return
    try:
        paths = json.loads(json_str)
        if isinstance(paths, list):
            for p in paths:
                if isinstance(p, str):
                    cleanup_file(p)
    except (json.JSONDecodeError, TypeError):
        pass


# ═══════════════════════════════════════════════════════════════════════════
# 照片数组合并
# ═══════════════════════════════════════════════════════════════════════════


def merge_photos_json(existing_json: str | None, new_paths: list[str]) -> str:
    """按文件名去重合并已有照片路径与新下载路径，返回 JSON 字符串。

    原实现散落在 bitable_handler.py（内联）和 bitable_ai_handler.py（_merge_photos_json）。
    """
    existing: list[str] = []
    if existing_json:
        try:
            loaded = json.loads(existing_json)
            if isinstance(loaded, list):
                existing = loaded
        except (json.JSONDecodeError, TypeError):
            existing = []
    existing_basenames = {os.path.basename(str(p).replace("\\", "/")) for p in existing}
    normalized_new = [str(p).replace("\\", "/") for p in new_paths]
    unique_new = [p for p in normalized_new if os.path.basename(p) not in existing_basenames]
    return json.dumps(existing + unique_new, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════════
# 路径解析
# ═══════════════════════════════════════════════════════════════════════════


def resolve_local_path(file_path: str) -> str | None:
    """将存储路径解析为实际存在的本地文件系统路径。

    处理三种存储约定：
      1. 干净相对路径（新）：``safety/hazard/file.jpg``
         → ``{cwd}/uploads/safety/hazard/file.jpg``
      2. 旧前缀路径：``uploads/safety/hazard/file.jpg``
         → ``{cwd}/uploads/safety/hazard/file.jpg``（剥离前缀后拼接）
      3. 绝对路径（极旧 / 跨盘）：``E:/.../uploads/...``
         → 文件存在时照原样使用

    原实现散落在 api/files.py（_resolve_local_path）、service/hazard.py
    （_parse_defect_photo_urls 内联）和 feishu/notification.py
    （_resolve_local_image_path）。
    """
    cwd = os.path.abspath(".")
    uploads_base = os.path.abspath("./uploads")

    # 1. 拼接 uploads base（处理干净路径 + 旧前缀路径）
    if file_path.startswith("uploads/"):
        relative = file_path[len("uploads/"):]
    elif file_path.startswith("uploads\\"):
        relative = file_path[len("uploads\\"):]
    else:
        relative = file_path
    candidate = os.path.normpath(os.path.join(uploads_base, relative))
    if os.path.isfile(candidate):
        return candidate

    # 2. 直接使用绝对路径
    if os.path.isabs(file_path) and os.path.isfile(file_path):
        return file_path

    # 3. 相对 CWD 直接尝试
    candidate = os.path.normpath(os.path.join(cwd, file_path))
    if os.path.isfile(candidate):
        return candidate

    return None


def resolve_image_path_variants(file_path: str) -> list[str]:
    """生成路径的所有变体（Windows/Unix 分隔符互换 + uploads 前缀拼接）。

    用于需要检查多个路径变体的场景（如 _parse_defect_photo_urls）。
    """
    check_paths = [file_path]
    # 分隔符互换
    if "\\" in file_path:
        check_paths.append(file_path.replace("\\", "/"))
    elif "/" in file_path:
        check_paths.append(file_path.replace("/", "\\"))
    # 拼接 uploads/ 前缀
    uploads_base = os.path.abspath("./uploads")
    for orig in list(check_paths):
        candidate = os.path.normpath(os.path.join(uploads_base, orig))
        if candidate not in check_paths:
            check_paths.append(candidate)
    return check_paths


# ═══════════════════════════════════════════════════════════════════════════
# 文件上传存储（MinIO / 本地双模式）
# ═══════════════════════════════════════════════════════════════════════════


def save_upload_to_storage(
    content: bytes,
    file_name: str,
    *,
    subdir: str = "hazard",
    content_type: str = "image/jpeg",
) -> str:
    """将上传文件保存到 MinIO 或本地磁盘，返回存储路径。

    MinIO 模式：返回 object_key（如 ``hazard/file.jpg``）。
    本地模式：返回相对于 uploads/ 的路径（如 ``safety/hazard/file.jpg``）。

    原 MinIO/本地分支在 4+ 个 API 端点中重复（hazards/hazard_identifications/
    knowledge/regulations）。
    """
    import time as _time

    file_ext = os.path.splitext(file_name)[1] or ".bin"
    safe_name = f"{subdir}_{_time.time()}{file_ext}"

    if minio_enabled():
        object_key = f"{subdir}/{safe_name}"
        from app.core.storage import upload_object

        upload_object("safety", object_key, content, len(content), content_type)
        return object_key

    # 本地存储
    upload_dir = os.path.join("uploads", "safety", subdir)
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, safe_name)
    with open(file_path, "wb") as f:
        f.write(content)
    # 存储相对路径（不带 uploads/ 前缀），与 resolve_local_path 的约定一致
    return os.path.join("safety", subdir, safe_name)


# ═══════════════════════════════════════════════════════════════════════════
# 图片编码（视觉模型前置处理）
# ═══════════════════════════════════════════════════════════════════════════


def encode_image_for_vision(
    raw: bytes,
    mime: str,
    path: str = "",
    *,
    max_dim: int = 2048,
    threshold_bytes: int = 2_000_000,
) -> str | None:
    """校验并将图片编码为 base64 data URI；用 Pillow 解码→JPEG 重编码。

    视觉模型（通义千问-VL）对图片有效性/体积有要求。手机原图常达 5-11MB，
    也存在下载损坏/非图文件被当作 .jpg 的情况，直接送模型会触发
    "Multimodal file size is too large" 或 "image format is illegal" 400。
    - Pillow 解码可校验有效性并归一化为模型必然支持的 JPEG；
    - 超过 max_dim 的降采样；
    - 无法解码（损坏/非图/视频误入）→ 返回 None，调用方跳过该附件，
      避免坏图阻断整条识别/初审（改走纯文本或其余有效图片）。

    原实现位于 service/hazard.py _encode_image_data_uri。
    """
    import base64

    try:
        from PIL import Image as _Image

        img = _Image.open(BytesIO(raw))
        img.load()  # 强制解码，验证文件确为有效图片（损坏文件在此抛异常）
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        out = buf.getvalue()
        if len(raw) > threshold_bytes:
            logger.info(
                "大图降采样: %s %dKB→%dKB",
                path or "?", len(raw) // 1024, len(out) // 1024,
            )
        return f"data:image/jpeg;base64,{base64.b64encode(out).decode()}"
    except Exception as exc:
        logger.warning("图片无效/无法解码，跳过不送视觉模型: %s (%s)", path or "?", exc)
        return None


# ═══════════════════════════════════════════════════════════════════════════
# PDF → 页面 PNG（视觉送审前渲染，PyMuPDF 懒加载）
# ═══════════════════════════════════════════════════════════════════════════


def pdf_to_page_images(
    pdf_path: str,
    out_dir: str,
    *,
    max_dim: int = 2048,
    max_pages: int | None = None,
) -> list[str]:
    """将 PDF 每页渲染为 PNG，返回按页序的 PNG 路径列表。

    PyMuPDF（fitz）函数内懒加载：该依赖仅视觉审核链路用到，不强制全局引入。
    每页在保持宽高比的前提下缩放到最长边 ≤ max_dim（与 VisionService 的
    encode_image_for_vision 降采样上限一致，避免二次缩放）。

    Args:
        pdf_path: 本地 PDF 文件路径。
        out_dir: PNG 输出目录（自动创建）。
        max_dim: 页面最长边上限（像素）。
        max_pages: 最多渲染页数（None=全部），防御异常超长文档。

    Returns:
        按页序的 PNG 路径列表；pdf 不存在/无法打开/无有效页返回 []。
    """
    if not pdf_path or not os.path.exists(pdf_path):
        logger.warning("pdf_to_page_images: pdf 不存在 %s", pdf_path)
        return []

    try:
        import fitz  # PyMuPDF，懒加载
    except ImportError:
        logger.warning("pdf_to_page_images: PyMuPDF (fitz) 未安装，无法渲染页面")
        return []

    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    out_paths: list[str] = []
    try:
        with fitz.open(pdf_path) as doc:
            total = doc.page_count
            limit = total if max_pages is None else min(total, max_pages)
            for i in range(limit):
                page = doc.load_page(i)
                pix = page.get_pixmap(dpi=150)  # ~1240×1754 A4，含中文可读
                if max(pix.width, pix.height) > max_dim:
                    scale = max_dim / max(pix.width, pix.height)
                    pix = page.get_pixmap(
                        dpi=150 * scale,
                        width=max(1, int(pix.width * scale)),
                        height=max(1, int(pix.height * scale)),
                    )
                png_path = os.path.join(out_dir, f"{base}_p{i + 1:02d}.png")
                pix.save(png_path)
                out_paths.append(png_path)
    except Exception as exc:
        logger.warning("pdf_to_page_images: 渲染失败 %s (%s)", pdf_path, exc)
        for p in out_paths:  # 失败时清理已生成的半成品
            try:
                os.remove(p)
            except OSError:
                pass
        return []
    logger.info("pdf_to_page_images: %s → %d 页 PNG", pdf_path, len(out_paths))
    return out_paths


# ═══════════════════════════════════════════════════════════════════════════
# 照片 JSON → vision-ready URL 列表
# ═══════════════════════════════════════════════════════════════════════════


def resolve_photo_urls(photos_json: str, *, logger_instance: logging.Logger | None = None) -> list[str]:
    """从照片 JSON 字段提取图片，本地路径转 base64 data URI。

    已经是 http/https/data URL 的直接保留，本地路径则：
    1. 通过 resolve_image_path_variants() 查找真实文件
    2. 通过 encode_image_for_vision() 编码为 base64 data URI
    3. 非图片扩展名跳过
    4. 本地全部 miss 且 MinIO 启用时，按 object key（去除 uploads/ 前缀）
       从 MinIO 取字节后同样编码为 data URI

    原实现位于 service/hazard.py _parse_defect_photo_urls（实例方法）。

    Args:
        photos_json: JSON 数组字符串（如 ``["path/to/img.jpg"]``）。
        logger_instance: 可选的 logger 实例，不传则使用模块级 logger。

    Returns:
        可直接传给视觉模型的 URL/URI 列表。
    """
    _log = logger_instance or logger

    try:
        photos = json.loads(photos_json)
    except (json.JSONDecodeError, TypeError):
        # Windows 反斜杠路径经 json.dumps 写入后，json.loads 会报 Invalid \escape
        try:
            photos = json.loads(photos_json.replace("\\", "/"))
        except (json.JSONDecodeError, TypeError):
            _log.warning("photos JSON 解析失败，返回空列表: raw=%s", str(photos_json)[:200])
            return []
    if isinstance(photos, str):
        photos = [photos] if photos else []
    elif not isinstance(photos, list):
        _log.warning("photos 格式异常(非 list/str)，返回空列表: type=%s", type(photos).__name__)
        return []

    urls: list[str] = []
    for p in photos:
        p_str = str(p)
        # 已经是 http/data URL，直接使用
        if p_str.startswith("http://") or p_str.startswith("https://") or p_str.startswith("data:"):
            urls.append(p_str)
            continue
        # 本地路径 → base64 data URI
        check_paths = resolve_image_path_variants(p_str)
        found_path = None
        for cp in check_paths:
            if cp and os.path.exists(cp):
                found_path = cp
                break
        if found_path:
            try:
                ext = os.path.splitext(found_path)[1].lower()
                mime = IMAGE_MIME_MAP.get(ext)
                if mime is None:
                    _log.info("跳过非图片附件(不送视觉模型): %s", found_path)
                    continue
                with open(found_path, "rb") as f:
                    raw_img = f.read()
                data_uri = encode_image_for_vision(raw_img, mime, found_path)
                if data_uri:
                    urls.append(data_uri)
                    _log.debug("转换本地图片为 data URI: %s (%s)", found_path, mime)
            except Exception as exc:
                _log.warning("无法读取图片 %s: %s", found_path, exc)
        elif minio_enabled():
            # MinIO 分支：本地全部 miss 时按 object key 取字节（去除 uploads/ 前缀的紧凑形式）
            try:
                ext = os.path.splitext(p_str)[1].lower()
                mime = IMAGE_MIME_MAP.get(ext)
                if mime is None:
                    _log.info("跳过非图片附件(不送视觉模型): %s", p_str)
                    continue
                # MinIO object key 不带 safety/ 段：旧值 uploads/safety/hazard/x.jpg
                # 需剥掉两段前缀才是 key（hazard/x.jpg）；裸 key 原样使用
                if p_str.startswith("uploads/safety/"):
                    key = p_str[len("uploads/safety/"):]
                elif p_str.startswith("uploads/"):
                    key = p_str[len("uploads/"):]
                else:
                    key = p_str
                result = get_object("safety", key)
                if result is None:
                    _log.warning(
                        "photos 存储中不存在: path=%s (checked: %s)",
                        p_str, check_paths,
                    )
                    continue
                data_uri = encode_image_for_vision(result[0], mime, p_str)
                if data_uri:
                    urls.append(data_uri)
                    _log.debug("从 MinIO 读取图片为 data URI: %s (%s)", p_str, mime)
            except Exception as exc:
                _log.warning("无法从 MinIO 读取图片 %s: %s", p_str, exc)
        else:
            _log.warning(
                "photos 本地文件不存在: path=%s (checked: %s)",
                p_str, check_paths,
            )

    _log.info(
        "resolve_photo_urls: input_count=%d output_count=%d",
        len(photos) if isinstance(photos, list) else 0, len(urls),
    )
    return urls


# ═══════════════════════════════════════════════════════════════════════════
# 图片筛选（减少视觉模型 token 消耗）
# ═══════════════════════════════════════════════════════════════════════════

_MAX_VISION_IMAGES = 4  # 视觉模型单次分析上限


def filter_relevant_images(
    image_urls: list[str],
    max_images: int = _MAX_VISION_IMAGES,
) -> list[str]:
    """限制送入视觉模型的图片数量。

    原则：取前 N 张（用户通常将最重要的图片放在前面）。
    不做 AI 筛选，避免额外 LLM 调用抵消 token 节省效果。

    Args:
        image_urls: 已编码的图片 URL/URI 列表。
        max_images: 上限数量（默认 4）。

    Returns:
        截断后的列表。长度 ≤ max_images。
    """
    if len(image_urls) <= max_images:
        return image_urls

    _log = logger
    _log.info(
        "filter_relevant_images: %d → %d (capped at %d)",
        len(image_urls), max_images, max_images,
    )
    return image_urls[:max_images]
