"""R3 测试 purge —— 快照差集法（R3 三期 T1，开闸硬前置）。

旧 purge 三宗罪（开闸后跑一轮测试=毁灭观察期数据）：
1. 删全量 ``executor=r3_ops_heal`` 工单（真机工单陪葬；api 文件已收窄 short_name，
   scan/executor/repair 三文件未收）；
2. 按名删 ``safety.ops.selfheal`` / ``safety.ops.rag_inject`` 源行（真扫描源灭失
   ——dev 库两行已被历史测试删成稳态缺失，迁移 ON CONFLICT DO NOTHING 不复种）；
3. ``dedupe_key LIKE 'r3:%'`` 删全量 effect（真诊断/收口 effect 陪葬）。

快照差集：setup 记存量 id 集，teardown **只删快照外新增行**；源行永不删，
enabled/config 被测试改动按快照还原（快照里没有的源行=测试新建→连带其下
trigger 一并删）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, select

from app.platform.superagent.models import (
    AgentDecision,
    AgentEffect,
    AgentInput,
    AgentSource,
    AgentSourceCursor,
    AgentTask,
    AgentTaskSubscription,
    AgentTrigger,
)

#: R3 三源名（trigger 圈定边界：只清这三源下快照外新增）
R3_SOURCE_NAMES = ("safety.ops.selfheal", "safety.ops.rag_inject", "safety.ops.event_inject")


def _r3_effect_filter() -> ColumnElement[bool]:
    """R3 自有 effect 圈定（对齐旧 purge 口径：前缀 + 自有 kind + 历史前缀）。"""
    return (
        AgentEffect.dedupe_key.like("r3:%")
        | AgentEffect.dedupe_key.like("r3hist-%")
        | AgentEffect.kind.in_(("r3_repair", "r3_closure_card"))
    )


def _scoped(base: ColumnElement[bool], column: Any, ids: list[Any]) -> ColumnElement[bool]:
    """base 条件再排除快照存量（空快照=圈定范围内全量，即首次运行的旧语义收口）。"""
    return base & ~column.in_(ids) if ids else base


async def snapshot_r3_rows() -> dict[str, Any]:
    """快照存量 R3 行（独立会话，只读已提交态）。"""
    from tests.conftest import _test_session_factory

    async with _test_session_factory() as s:
        task_ids = list((
            await s.execute(
                select(AgentTask.id).where(AgentTask.executor == "r3_ops_heal")
            )
        ).scalars().all())
        src_rows = list((
            await s.execute(
                select(AgentSource).where(AgentSource.name.in_(R3_SOURCE_NAMES))
            )
        ).scalars().all())
        src_ids = [x.id for x in src_rows]
        trigger_ids = list((
            await s.execute(
                select(AgentTrigger.id).where(AgentTrigger.source_id.in_(src_ids))
            )
        ).scalars().all()) if src_ids else []
        effect_ids = list((
            await s.execute(select(AgentEffect.id).where(_r3_effect_filter()))
        ).scalars().all())
        cursors = {
            x.name: {
                c.name: c.value
                for c in (
                    await s.execute(
                        select(AgentSourceCursor).where(
                            AgentSourceCursor.source_id == x.id
                        )
                    )
                ).scalars().all()
            }
            for x in src_rows
        }
        return {
            "task_ids": task_ids,
            "trigger_ids": trigger_ids,
            "effect_ids": effect_ids,
            "sources": {
                x.name: {"enabled": x.enabled, "config": dict(x.config or {})}
                for x in src_rows
            },
            "cursors": cursors,
        }


async def ensure_r3_source(
    session: Any, *, name: str, kind: str, config: dict[str, Any], enabled: bool = True,
) -> AgentSource:
    """upsert-复用源行（T1）：存在只翻 enabled（快照 purge 会还原），不存在才 INSERT。

    开闸后真源行常驻 dev 库（唯一索引 uq_agent_sources_name），裸 INSERT 必撞；
    存在分支不动 config（真行 config 已是迁移播种口径，测试无需覆写）。
    """
    src = (
        await session.execute(select(AgentSource).where(AgentSource.name == name))
    ).scalar_one_or_none()
    if src is None:
        src = AgentSource(kind=kind, name=name, enabled=enabled, config=config)
        session.add(src)
    else:
        src.enabled = enabled
    await session.flush()
    return src


async def purge_new_r3_rows(snap: dict[str, Any]) -> None:
    """清快照外新增 R3 行 + 还原源行 enabled/config（独立会话，commit）。"""
    from tests.conftest import _test_session_factory

    async with _test_session_factory() as s:
        # ── 新增工单（连带 inputs/subscriptions）──
        new_tasks = list((
            await s.execute(
                select(AgentTask.id).where(
                    _scoped(AgentTask.executor == "r3_ops_heal", AgentTask.id, snap["task_ids"])
                )
            )
        ).scalars().all())
        if new_tasks:
            await s.execute(
                AgentInput.__table__.delete().where(AgentInput.task_id.in_(new_tasks))
            )
            await s.execute(
                AgentTaskSubscription.__table__.delete().where(
                    AgentTaskSubscription.task_id.in_(new_tasks)
                )
            )
            await s.execute(
                AgentTask.__table__.delete().where(AgentTask.id.in_(new_tasks))
            )

        # ── 源行：还原字段 / 清测试新建行（连带其下 trigger）──
        src_rows = list((
            await s.execute(
                select(AgentSource).where(AgentSource.name.in_(R3_SOURCE_NAMES))
            )
        ).scalars().all())
        snap_sources: dict[str, Any] = snap.get("sources") or {}
        for row in src_rows:
            saved = snap_sources.get(row.name)
            if saved is None:
                trig_ids = list((
                    await s.execute(
                        select(AgentTrigger.id).where(AgentTrigger.source_id == row.id)
                    )
                ).scalars().all())
                if trig_ids:
                    await s.execute(
                        AgentDecision.__table__.delete().where(
                            AgentDecision.trigger_id.in_(trig_ids)
                        )
                    )
                    await s.execute(
                        AgentInput.__table__.delete().where(
                            AgentInput.trigger_id.in_(trig_ids)
                        )
                    )
                    await s.execute(
                        AgentTrigger.__table__.delete().where(AgentTrigger.id.in_(trig_ids))
                    )
                await s.execute(
                    AgentSource.__table__.delete().where(AgentSource.id == row.id)
                )
            elif row.enabled != saved["enabled"] or dict(row.config or {}) != saved["config"]:
                row.enabled = saved["enabled"]
                row.config = saved["config"]

        # ── 新增 trigger（连带 decisions/inputs；源行处理后按现存源圈定）──
        src_ids = list((
            await s.execute(
                select(AgentSource.id).where(AgentSource.name.in_(R3_SOURCE_NAMES))
            )
        ).scalars().all())
        if src_ids:
            new_triggers = list((
                await s.execute(
                    select(AgentTrigger.id).where(
                        _scoped(
                            AgentTrigger.source_id.in_(src_ids),
                            AgentTrigger.id, snap["trigger_ids"],
                        )
                    )
                )
            ).scalars().all())
            if new_triggers:
                await s.execute(
                    AgentDecision.__table__.delete().where(
                        AgentDecision.trigger_id.in_(new_triggers)
                    )
                )
                await s.execute(
                    AgentInput.__table__.delete().where(
                        AgentInput.trigger_id.in_(new_triggers)
                    )
                )
                await s.execute(
                    AgentTrigger.__table__.delete().where(
                        AgentTrigger.id.in_(new_triggers)
                    )
                )

        # ── 新增 effect ──
        await s.execute(
            AgentEffect.__table__.delete().where(
                _scoped(_r3_effect_filter(), AgentEffect.id, snap["effect_ids"])
            )
        )

        # ── 读位还原（测试中途 _scan_once 提交的 job_state/last_tick 不污染真机）──
        snap_cursors: dict[str, Any] = snap.get("cursors") or {}
        for row in src_rows:
            await s.execute(
                AgentSourceCursor.__table__.delete().where(
                    AgentSourceCursor.source_id == row.id
                )
            )
            for cname, cvalue in (snap_cursors.get(row.name) or {}).items():
                await s.execute(
                    AgentSourceCursor.__table__.insert().values(
                        source_id=row.id, name=cname, value=cvalue,
                    )
                )
        await s.commit()
