"""QA 模块后台服务声明：文档正文提取 / AI 分析生成器 + 启动配置自检。

main.py 只认 QA_EXTENSION 实例，不再感知本模块内部细节。
"""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.modules.qa.scheduler import AI_GENERATOR, GENERATOR
from app.platform.module_lifecycle import ModuleExtension, ModuleHost

logger = logging.getLogger(__name__)


def _warn_if_md_extract_misconfigured() -> None:
    """QA_MD_EXTRACT_PROVIDER 默认 mineru，而 token 默认为空（config.py 和
    .env.example 都是）。两者不一致时，每一次上传都会在后台解析时抛
    MineruError，只留一条藏在文件详情里的失败状态，没人会逐条去翻。

    此前 main.py 在 lifespan 里直接 RuntimeError 阻断整个平台启动——一个
    模块的配置缺失不该让生产、HR 等其余模块陪葬。降级为启动告警，运维从
    启动日志即可发现并补配。
    """
    settings = get_settings()
    if (
        settings.QA_MD_EXTRACT_PROVIDER.strip().casefold() or "mineru"
    ) == "mineru" and not settings.QA_MD_EXTRACT_API_TOKEN.strip():
        logger.warning(
            "QA_MD_EXTRACT_PROVIDER=mineru 但 QA_MD_EXTRACT_API_TOKEN 未配置，"
            "所有 QA 正文解析都会失败。请配置 token，"
            "或显式设置 QA_MD_EXTRACT_PROVIDER=native。"
        )


class QaExtension(ModuleExtension):
    """QA 模块对进程生命周期的声明。"""

    code = "qa"

    def register(self, host: ModuleHost) -> None:
        _warn_if_md_extract_misconfigured()
        # 任务状态持久化在 qa.document_files，服务重启后可继续。
        host.scheduler.register_generator(GENERATOR)
        host.scheduler.register_generator(AI_GENERATOR)


QA_EXTENSION = QaExtension()
