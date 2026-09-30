"""飞书对话式填报服务包（fill_service.py 1350 行拆分）。

- _common：指令解析/白名单/批号解析/临时状态（TTL）/卡片与文本辅助
- _commands：对话式指令处理（建任务/填报/修正/进度/图片归档）
- _cards：菜单事件与卡片回调（表单提交/标准文件多选）
- _push：任务提醒/不合格告警/待复核与建任务通知

导入本包即注册飞书事件处理器（main.py 原样 `import fill_service` 生效），
对外符号全部 re-export，原有 import 路径不变。
"""

from app.modules.quality.feishu.fill_service import (  # noqa: F401
    _cards,
    _commands,
    _push,
)
from app.modules.quality.feishu.fill_service._cards import (  # noqa: F401
    handle_bot_menu_event,
    handle_card_action,
)
from app.modules.quality.feishu.fill_service._commands import (  # noqa: F401
    handle_fill_command,
)
from app.modules.quality.feishu.fill_service._common import (  # noqa: F401
    _ARCHIVE_MODE,
    _BATCH_RE,
    _LAST_BATCH,
    _LAST_IMAGE,
    _PAIR_RE,
    _PENDING_DOC_SELECT,
    _allowed,
    _allowed_create,
    _doc_to_card_dict,
    _extract_command,
    _frontend_task_link,
    _norm_sop,
    _prune_stale_state,
    _resolve_docs_by_batch,
    _resolve_task_by_batch,
    _task_doc_file_nos,
    _today_str,
    _unfilled_groups,
)
from app.modules.quality.feishu.fill_service._push import (  # noqa: F401
    notify_pending_review,
    notify_task_created,
    notify_unqualified,
    push_task_reminder,
)

# 显式声明对外符号：分包拆分后各符号在本包 re-export，
# 使 `from ...fill_service import X` 的类型检查与运行时行为一致（strict 模式要求）
__all__ = [
    "_ARCHIVE_MODE",
    "_BATCH_RE",
    "_LAST_BATCH",
    "_LAST_IMAGE",
    "_PAIR_RE",
    "_PENDING_DOC_SELECT",
    "_allowed",
    "_allowed_create",
    "_cards",
    "_commands",
    "_doc_to_card_dict",
    "_extract_command",
    "_frontend_task_link",
    "_norm_sop",
    "_prune_stale_state",
    "_push",
    "_resolve_docs_by_batch",
    "_resolve_task_by_batch",
    "_task_doc_file_nos",
    "_today_str",
    "_unfilled_groups",
    "handle_bot_menu_event",
    "handle_card_action",
    "handle_fill_command",
    "notify_pending_review",
    "notify_task_created",
    "notify_unqualified",
    "push_task_reminder",
]
