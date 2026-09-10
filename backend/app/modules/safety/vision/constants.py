"""视觉服务常量 — MIME 映射、尺寸限制、阈值等。"""

# ── 图片 MIME 类型映射（扩展名 → content-type）──
IMAGE_MIME_MAP: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}

# ── 文件 MIME 类型映射（扩展名 → content-type，供 file proxy 使用）──
FILE_MIME_MAP: dict[str, str] = {
    **IMAGE_MIME_MAP,
    ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".json": "application/json",
    ".zip": "application/zip",
}

# ── 图片预处理参数 ──
MAX_DIM = 2048           # 视觉模型最大边长（超过则等比降采样）
JPEG_QUALITY = 85        # JPEG 重编码质量
THRESHOLD_BYTES = 2_000_000  # 超过此大小的大图 INFO 日志记录

# ── 非图片扩展名（不送视觉模型，否则通义千问-VL 400）──
NON_IMAGE_EXTENSIONS: frozenset[str] = frozenset({
    ".mp4", ".mov", ".avi", ".mkv", ".webm",  # 视频
    ".mp3", ".wav", ".ogg",                    # 音频
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",  # 文档
    ".zip", ".rar", ".7z",                     # 压缩包
})
