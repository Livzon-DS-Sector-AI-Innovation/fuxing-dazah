"""速递卡条目图标：仓库内置 PNG 素材 → 飞书 image_key（磁盘 + 进程内缓存）。

素材是提交进仓库的 96×96 圆角浅底 PNG（生成脚本 .scratch/gen_digest_icons.py，
已渲染好彩色 emoji，运行时零字体依赖，服务器无 emoji 字体也能用）。
image_key 上传一次后持久缓存到 uploads/feishu_icon_keys.json，之后每天复用。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from app.modules.safety.feishu.notification import upload_image_to_feishu

logger = logging.getLogger(__name__)

# 素材目录：app/modules/safety/assets/digest_icons/
_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "digest_icons"
# image_key 缓存（运行时写入，与 hazard 照片同用 ./uploads 根）
_CACHE_FILE = Path(os.path.abspath("./uploads")) / "feishu_icon_keys.json"

# operation_type 英文枚举 → 素材名（未知类型回退 fallback ⚠️）
_TYPE_ASSETS: dict[str, str] = {
    "hot_work": "hot_work",
    "confined_space": "confined_space",
    "height_work": "height_work",
    "lifting": "lifting",
    "temporary_electricity": "temporary_electricity",
    "excavation": "excavation",
    "road_breaking": "road_breaking",
    "blind_plate": "blind_plate",
}

_keys: dict[str, str] = {}
_loaded = False


def _load_cache() -> None:
    global _loaded, _keys
    _loaded = True
    try:
        if _CACHE_FILE.exists():
            _keys = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("读取速递卡图标缓存失败，忽略（%s）", _CACHE_FILE, exc_info=True)
        _keys = {}


def _persist_cache() -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(
            json.dumps(_keys, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        logger.warning("写入速递卡图标缓存失败，忽略（%s）", _CACHE_FILE, exc_info=True)


async def get_type_icon_key(operation_type: str | None) -> str | None:
    """返回作业类型图标的飞书 image_key。

    上传失败或素材缺失返回 None，调用方降级为无图条目（不阻塞日报推送）。
    """
    asset_name = _TYPE_ASSETS.get(operation_type or "", "fallback")
    return await get_asset_icon_key(asset_name)


async def get_asset_icon_key(asset_name: str) -> str | None:
    """返回素材目录内任意图标的飞书 image_key（供安全速递总卡等复用）。

    素材缺失或上传失败返回 None，调用方降级为无图（不阻塞推送）。
    """
    if not _loaded:
        _load_cache()
    if asset_name in _keys:
        return _keys[asset_name]

    path = _ASSET_DIR / f"{asset_name}.png"
    if not path.exists():
        logger.warning("图标素材缺失: %s", path)
        return None
    key = await upload_image_to_feishu(str(path), content_type="image/png")
    if key:
        _keys[asset_name] = key
        _persist_cache()
    return key
