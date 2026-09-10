"""agent.md 加载器。

将同目录下的 ``agent.md``（Agent 的软性配置：人设 / 语言习惯 / 能力清单 / 业务规则）
读入为字符串，供 Pydantic AI ``Agent(instructions=...)`` 使用。

设计要点：
- 路径基于 ``__file__`` 解析，不依赖进程 CWD（服务从别处启动也能找到）。
- 强制 UTF-8（agent.md 为中文内容）。
- 启动时读一次并缓存；提供 ``reload_instructions()`` 供显式热重载（无需重启服务）。

⚠️ agent.md 只承载**软性**规则。可强制执行的护栏（权限、写确认、输出校验、禁语拦截）
   一律在 ``rules.py`` / ``permissions.py`` 代码中实现，绝不依赖模型自觉遵守本文件。
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_AGENT_MD_PATH = Path(__file__).parent / "agent.md"

# 进程内缓存，避免每次请求都读磁盘
_cached_instructions: str | None = None


def _read_agent_md() -> str:
    """从磁盘读取 agent.md（UTF-8）。"""
    try:
        return _AGENT_MD_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.error("business_agent: agent.md 未找到，路径=%s", _AGENT_MD_PATH)
        raise
    except OSError as exc:  # 权限/编码等异常
        logger.error("business_agent: 读取 agent.md 失败: %s", exc)
        raise


def load_instructions(*, force_reload: bool = False) -> str:
    """返回 Agent 的 instructions（agent.md 全文 + 动态日期）。

    默认使用进程内缓存；``force_reload=True`` 时重新读盘。
    当前日期始终动态追加（不缓存），确保 Agent 知道"今天"是什么时候。
    """
    global _cached_instructions
    if _cached_instructions is None or force_reload:
        _cached_instructions = _read_agent_md()
        logger.info(
            "business_agent: 已加载 agent.md（%d 字符，reload=%s）",
            len(_cached_instructions),
            force_reload,
        )

    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone(timedelta(hours=8)))  # Asia/Shanghai
    weekday_names = ["一", "二", "三", "四", "五", "六", "日"]
    this_month = now.strftime("%Y年%m月")
    this_week = now.isocalendar()[1]
    today_str = now.strftime("%Y-%m-%d")
    date_hint = (
        "\n\n# 系统信息\n\n"
        f'当前日期：{now.strftime("%Y年%m月%d日")} '
        f"（{today_str}，"
        f"星期{weekday_names[now.weekday()]}，"
        f"第{this_week}周）。"
        f'\n用户提到"本月"即指 {this_month}，'
        f'"本周"即指第{this_week}周，'
        f'"今天"即指 {today_str}。'
    )
    return _cached_instructions + date_hint


def reload_instructions() -> str:
    """显式热重载 agent.md，返回最新内容。供管理接口调用。"""
    return load_instructions(force_reload=True)


def instructions_version() -> str:
    """当前生效 instructions 的版本标识（内容 sha256 前 12 位）。

    供 AI 调用审计留痕：审计记录中的 prompt_version 可与 git 中的
    agent.md 历史版本精确对应，还原"AI 当时看到的是哪版规则"。
    """
    import hashlib

    content = load_instructions()
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
