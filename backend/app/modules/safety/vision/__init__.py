"""安全模块统一视觉服务。

提供：
- 共享工具函数（utils）—— 文件清理、路径解析、照片合并、图片编码、存储上传
- VisionService（service）—— 视觉 AI 调用统一入口
"""

from app.modules.safety.vision.service import VisionService
from app.modules.safety.vision.utils import (
    cleanup_file,
    cleanup_json_array_files,
    encode_image_for_vision,
    merge_photos_json,
    resolve_image_path_variants,
    resolve_local_path,
    resolve_photo_urls,
    save_upload_to_storage,
)

__all__ = [
    # VisionService
    "VisionService",
    # 工具函数
    "cleanup_file",
    "cleanup_json_array_files",
    "encode_image_for_vision",
    "merge_photos_json",
    "resolve_image_path_variants",
    "resolve_local_path",
    "resolve_photo_urls",
    "save_upload_to_storage",
]
