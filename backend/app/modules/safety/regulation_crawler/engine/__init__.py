"""爬虫引擎：策略模式 + AI 提取。"""

from app.modules.safety.regulation_crawler.engine.base import (
    BaseCrawler,
    RegulationSource,
)
from app.modules.safety.regulation_crawler.engine.sources import DEFAULT_SOURCES

__all__ = ["BaseCrawler", "RegulationSource", "DEFAULT_SOURCES"]
