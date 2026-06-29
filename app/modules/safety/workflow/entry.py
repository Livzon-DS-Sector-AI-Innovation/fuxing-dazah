"""WorkflowEntry — graphon GraphEngine 的 dazah 入口。

职责：
1. 从 WorkflowDefinition.graph JSON 构造 Graph
2. 注入 dazah 适配器（DazahLLMAdapter）
3. 构造 GraphRuntimeState（含 VariablePool）
4. 调用 GraphEngine.run() 生成器 → 收集输出
5. 返回 {outputs, total_tokens, total_steps, node_results}
"""

from __future__ import annotations

import logging
import time
from typing import Any

from graphon.entities.graph_init_params import GraphInitParams
from graphon.graph.graph import Graph
from graphon.graph_engine.command_channels.in_memory_channel import InMemoryChannel
from graphon.graph_engine.config import GraphEngineConfig
from graphon.graph_engine.graph_engine import GraphEngine
from graphon.graph_events.graph import (
    GraphRunFailedEvent,
    GraphRunPartialSucceededEvent,
    GraphRunSucceededEvent,
)
from graphon.graph_events.node import (
    NodeRunFailedEvent,
    NodeRunStartedEvent,
    NodeRunStreamChunkEvent,
    NodeRunSucceededEvent,
)
from graphon.runtime.graph_runtime_state import GraphRuntimeState
from graphon.runtime.variable_pool import VariablePool
from graphon.variables.factory import build_segment, segment_to_variable

from app.modules.safety.workflow.adapters.factory import DazahNodeFactory
from app.modules.safety.workflow.adapters.llm import DazahLLMAdapter
from app.modules.safety.workflow.models import WorkflowDefinition

logger = logging.getLogger(__name__)


class WorkflowEntry:
    """dazah 工作流引擎入口。

    封装 graphon GraphEngine 的构造和执行过程。
    同步执行（graphon 使用线程池），在 FastAPI 中用 run_in_executor 调用。
    """

    def __init__(self, ai_service: Any):
        """初始化 WorkflowEntry。

        Args:
            ai_service: dazah AIService 实例（来自 create_ai_service()）
        """
        self._ai_service = ai_service

    def run(
        self,
        workflow_def: WorkflowDefinition,
        inputs: dict[str, Any],
        workflow_run_id: str = "",
    ) -> dict[str, Any]:
        """执行工作流，返回执行结果。

        Args:
            workflow_def: DB 中的工作流定义
            inputs: 用户传入的输入变量
            workflow_run_id: 运行记录 UUID（用于日志关联）

        Returns:
            {
                "outputs": dict,          # end 节点的输出
                "total_tokens": int,      # LLM token 总计
                "total_steps": int,       # 执行的节点数
                "node_results": {         # 每个节点的执行详情
                    node_id: {
                        "status": "succeeded"|"failed",
                        "output": dict,
                        "error": str|None,
                        "tokens": int,
                        "elapsed": float,
                    }
                }
            }

        Raises:
            ValueError: graph JSON 无效
            RuntimeError: 工作流执行失败
        """
        graph_config = workflow_def.graph
        if not graph_config or not graph_config.get("nodes"):
            raise ValueError("工作流 graph 为空")

        workflow_id = str(workflow_def.id)

        # ── 1. 构造适配器 ──
        llm_adapter = DazahLLMAdapter(
            ai_service=self._ai_service,
            provider="deepseek",
            model_name="deepseek-v4-flash",
            temperature=0.05,
            max_tokens=4096,
        )
        node_factory = DazahNodeFactory(llm_adapter=llm_adapter)

        # ── 2. 初始化 VariablePool ──
        variable_pool = self._build_variable_pool(inputs)

        # ── 3. 构造 Graph ──
        root_node_id = self._find_root_node_id(graph_config)
        graph = Graph.init(
            graph_config=graph_config,
            node_factory=node_factory,
            root_node_id=root_node_id,
            skip_validation=False,
        )

        # ── 4. 构造 GraphRuntimeState ──
        runtime_state = GraphRuntimeState(
            variable_pool=variable_pool,
            start_at=time.time(),
            total_tokens=0,
            node_run_steps=0,
        )

        # ── 5. 构造 GraphEngine ──
        graph_init = GraphInitParams(
            workflow_id=workflow_id,
            graph_config=graph_config,
            run_context={
                "workflow_id": workflow_id,
                "workflow_run_id": workflow_run_id,
                "inputs": inputs,
            },
            call_depth=0,
        )
        node_factory.set_run_context(graph_init, runtime_state)

        command_channel = InMemoryChannel()
        engine_config = GraphEngineConfig()

        engine = GraphEngine(
            workflow_id=workflow_id,
            graph=graph,
            graph_runtime_state=runtime_state,
            command_channel=command_channel,
            config=engine_config,
        )

        # ── 6. 执行并收集事件 ──
        node_results: dict[str, dict[str, Any]] = {}
        outputs: dict[str, Any] = {}
        total_tokens = 0
        total_steps = 0
        node_timers: dict[str, float] = {}

        try:
            for event in engine.run():
                if isinstance(event, NodeRunStartedEvent):
                    node_timers[event.node_id] = time.monotonic()
                    logger.debug(
                        "[%s] 节点开始: %s (type=%s)",
                        workflow_id, event.node_id, event.node_type,
                    )

                elif isinstance(event, NodeRunSucceededEvent):
                    elapsed = time.monotonic() - node_timers.get(
                        event.node_id, time.monotonic(),
                    )
                    node_results[event.node_id] = {
                        "status": "succeeded",
                        "output": event.outputs or {},
                        "error": None,
                        "tokens": event.total_tokens or 0,
                        "elapsed": round(elapsed, 3),
                    }
                    total_tokens += event.total_tokens or 0
                    total_steps += 1
                    logger.debug(
                        "[%s] 节点完成: %s (tokens=%d, elapsed=%.2fs)",
                        workflow_id, event.node_id,
                        event.total_tokens or 0, elapsed,
                    )

                elif isinstance(event, NodeRunFailedEvent):
                    elapsed = time.monotonic() - node_timers.get(
                        event.node_id, time.monotonic(),
                    )
                    node_results[event.node_id] = {
                        "status": "failed",
                        "output": {},
                        "error": str(event.error),
                        "tokens": 0,
                        "elapsed": round(elapsed, 3),
                    }
                    total_steps += 1
                    logger.error(
                        "[%s] 节点失败: %s (error=%s)",
                        workflow_id, event.node_id, event.error,
                    )

                elif isinstance(event, NodeRunStreamChunkEvent):
                    # 流式 chunk — 收集到对应节点的输出
                    pass

                elif isinstance(event, GraphRunSucceededEvent):
                    outputs = event.outputs or {}
                    total_tokens += event.total_tokens or 0
                    logger.info(
                        "[%s] 工作流执行成功 (tokens=%d, steps=%d)",
                        workflow_id, total_tokens, total_steps,
                    )

                elif isinstance(event, GraphRunPartialSucceededEvent):
                    outputs = event.outputs or {}
                    total_tokens += event.total_tokens or 0
                    logger.warning(
                        "[%s] 工作流部分成功 (exceptions=%d)",
                        workflow_id, event.exceptions_count,
                    )

                elif isinstance(event, GraphRunFailedEvent):
                    logger.error(
                        "[%s] 工作流执行失败: %s", workflow_id, event.error,
                    )
                    raise RuntimeError(
                        f"工作流执行失败: {event.error} "
                        f"(exceptions_count={event.exceptions_count})"
                    )

        except RuntimeError:
            raise
        except Exception as e:
            logger.exception("[%s] 工作流执行异常", workflow_id)
            raise RuntimeError(f"工作流执行异常: {e}") from e

        return {
            "outputs": outputs,
            "total_tokens": total_tokens,
            "total_steps": total_steps,
            "node_results": node_results,
        }

    # ── Private helpers ──

    def _build_variable_pool(self, inputs: dict[str, Any]) -> VariablePool:
        """将用户输入注入 VariablePool（sys.* 变量区）。

        graphon 的 start 节点会把变量存入 VariablePool，
        后续节点通过 {{#node_id.variable#}} 语法引用。
        """
        pool = VariablePool()
        for key, value in inputs.items():
            seg = build_segment(value)
            var = segment_to_variable(segment=seg, selector=["sys", key], name=key)
            pool.add(["sys", key], var)
        return pool

    def _find_root_node_id(self, graph_config: dict[str, Any]) -> str:
        """从 graph JSON 中查找根节点（start 节点）。

        所有节点中找出没有入边的节点作为根节点。
        优先选择 type='start' 的节点。
        """
        nodes: list[dict[str, Any]] = graph_config.get("nodes", [])
        edges: list[dict[str, Any]] = graph_config.get("edges", [])

        # 收集所有被指向的节点
        target_ids: set[str] = {e["target"] for e in edges}

        # 没有入边且 type='start' 的节点
        start_nodes = [
            n for n in nodes
            if n["id"] not in target_ids and n.get("data", {}).get("type") == "start"
        ]
        if start_nodes:
            return start_nodes[0]["id"]

        # 回退：没有入边的任意节点
        root_nodes = [n for n in nodes if n["id"] not in target_ids]
        if root_nodes:
            return root_nodes[0]["id"]

        # 最终回退：第一个节点
        if nodes:
            return nodes[0]["id"]

        raise ValueError("graph 中没有节点")
