"""URS 对话上传上下文（菜单点击 → 后续 PDF 路由依据）。

背景：私聊文件消息中 .docx 等类型可无歧义路由到 URS 审核，但 .pdf 与
职业健康归档（体检报告单）重叠，无法按扩展名区分。用户点击机器人菜单
「📑 URS 智能审核」即明确表达 URS 意图 → 记录 open_id + TTL，窗口内
该用户私聊发来的 .pdf 按优先 URS 处理，超窗或未点击则维持 OH 归档路由。

进程内 TTL 字典（单实例 WS 事件分发，无跨进程需求）；消费型语义：
一次文件消息命中后即清除，避免长窗口内 OH 归档 PDF 被持续误路由。
"""

from __future__ import annotations

import time

# 上下文有效期（秒）：菜单引导 → 发送文档的合理操作窗口
TTL_SECONDS = 30 * 60

_context: dict[str, float] = {}


def set_urs_upload_context(open_id: str) -> None:
    """记录用户点击 URS 菜单（刷新 TTL）。"""
    if open_id:
        _context[open_id] = time.monotonic() + TTL_SECONDS


def consume_urs_upload_context(open_id: str) -> bool:
    """检查并消费 URS 上传上下文；窗口内返回 True 并清除。"""
    expiry = _context.get(open_id)
    if expiry is None:
        return False
    del _context[open_id]
    return time.monotonic() <= expiry


def has_urs_upload_context(open_id: str) -> bool:
    """只读检查（不消费），供测试与诊断。"""
    expiry = _context.get(open_id)
    return expiry is not None and time.monotonic() <= expiry


def _clear_all() -> None:
    """清空上下文（仅供测试隔离使用）。"""
    _context.clear()
